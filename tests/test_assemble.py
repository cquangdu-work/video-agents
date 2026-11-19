"""Test bước lắp ráp + giọng đọc — KHÔNG gọi mạng, không cần ffmpeg/manim.

    python -m unittest discover -s tests -v
"""
import base64
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:                                  # máy thử có thể chưa cài python-dotenv
    import dotenv  # noqa: F401
except ImportError:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from src import assemble
from src.audio import tts

A = "Chỉ vỏn vẹn 15 ngày sau khi lên kệ, giá đã rớt."
B = "Từ mức giá gốc 3.199 đô la, nay chỉ còn 1.971 đô la."


class VoiceGroupTest(unittest.TestCase):
    def test_adjacent_scenes_with_same_voice_are_read_once(self):
        # Đúng ca hỏng trên VM: LLM chép một câu lời vào 3 cảnh hình liền nhau
        spec = [{"template": "intro"},
                {"voice": A}, {"voice": A}, {"voice": A + "  "},      # lệch dấu cách vẫn là một
                {"voice": B}, {"voice": B}]
        self.assertEqual(assemble.voice_groups(spec), [[0], [1, 2, 3], [4, 5]])

    def test_silent_scenes_never_merge_and_repeats_must_be_adjacent(self):
        spec = [{"template": "intro"}, {"voice": ""}, {"voice": A}, {"voice": B}, {"voice": A}]
        self.assertEqual(assemble.voice_groups(spec), [[0], [1], [2], [3], [4]])

    def test_sentences_read_in_one_breath_become_one_audio_run(self):
        spec = [{"template": "intro"}, {"voice": A}, {"voice": A}, {"voice": B}, {"voice": "C c c"}]
        groups = assemble.voice_groups(spec)                    # [[0], [1, 2], [3], [4]]
        self.assertEqual(assemble.audio_runs(groups, {}), groups)
        runs = assemble.audio_runs(groups, {3: 1})              # câu B nằm trong file của câu A
        self.assertEqual(runs, [[0], [1, 2, 3], [4]])
        self.assertEqual(assemble.audio_runs(groups, {3: 1, 4: 1}), [[0], [1, 2, 3, 4]])
        # câu A chiếm len(A) phần, chia đều cho 2 cảnh của nó; câu B chiếm len(B) phần
        self.assertEqual(assemble.scene_weights(spec, runs[1]), [len(A) / 2, len(A) / 2, len(B)])

    def test_joined_map_survives_reruns_but_not_a_missing_voice_file(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "joined.json").write_text('{"7": 6, "19": 18}')
            (d / "v_06.wav").write_bytes(b"x")
            self.assertEqual(assemble.load_joined(d / "joined.json", d), {7: 6})
            self.assertEqual(assemble.load_joined(d / "khong_co.json", d), {})

    def test_voice_cache_is_dropped_when_the_spec_text_changes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "v_01.wav").write_bytes(b"x")
            self.assertFalse(assemble.drop_stale_voice(d, [A, B]))   # thư mục đời cũ: giữ
            self.assertFalse(assemble.drop_stale_voice(d, [A, B]))   # spec y nguyên: giữ
            self.assertTrue((d / "v_01.wav").exists())
            (d / "joined.json").write_text("{}")
            self.assertTrue(assemble.drop_stale_voice(d, [B, A]))    # đổi thứ tự câu: xoá
            self.assertFalse((d / "v_01.wav").exists() or (d / "joined.json").exists())
            self.assertFalse(assemble.drop_stale_voice(d, [B, A]))

    def test_share_seconds_follows_spec_weights_and_keeps_total(self):
        self.assertEqual(assemble.share_seconds(12.0, [4, 4, 4]), [4.0, 4.0, 4.0])
        parts = assemble.share_seconds(9.0, [2, 4])
        self.assertAlmostEqual(sum(parts), 9.0)
        self.assertAlmostEqual(parts[1], 2 * parts[0])
        self.assertAlmostEqual(sum(assemble.share_seconds(5.0, [None, 0])), 5.0)   # spec thiếu seconds


class FitTempoTest(unittest.TestCase):
    """Giọng chậm hôm đó làm video vượt trần: đọc nhanh lên VỪA ĐỦ (ca thật #37: 95,3 giây)."""

    def test_no_speed_up_when_the_video_already_fits(self):
        self.assertEqual(assemble.fit_tempo([30.0, 40.0], [3, 4], 1.2, 90), 1.0)

    def test_speeds_up_just_enough(self):
        secs = [4.0] * 22                       # 22 câu x (4 + 0,35) + intro 1,2 = 96,9 giây
        t = assemble.fit_tempo(secs, [1] * 22, 1.2, 90)
        total = lambda tempo: 1.2 + sum(assemble.run_seconds(d, 1, tempo) for d in secs)
        self.assertTrue(1.0 < t <= assemble.MAX_TEMPO)
        self.assertLessEqual(total(t), 90.0)
        self.assertGreater(total(t - 0.002), 90.0)            # không nhanh hơn mức cần

    def test_never_faster_than_the_cap(self):
        self.assertEqual(assemble.fit_tempo([200.0], [1], 0.0, 90), assemble.MAX_TEMPO)

    def test_short_scenes_keep_their_minimum_length(self):
        # 3 cảnh hình cho 1 câu 3 giây: phải giữ 3 x MIN_SCENE dù đọc nhanh cỡ nào
        self.assertEqual(assemble.run_seconds(3.0, 3, 1.1), 3 * assemble.MIN_SCENE)
        self.assertAlmostEqual(assemble.run_seconds(8.8, 2, 1.1), 8.0 + assemble.VOICE_TAIL)


def resp(status, payload=None, text=""):
    r = mock.Mock(status_code=status, text=text)
    r.json.return_value = payload if payload is not None else {}
    return r


OK = resp(200, {"candidates": [{"content": {"parts": [
    {"inlineData": {"data": base64.b64encode(b"RIFFdata").decode()}}]}}]})
DAY_LIMIT = resp(429, {"error": {"message": "quota", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
    {"retryDelay": "40s"}]}})
MINUTE_LIMIT = resp(429, {"error": {"message": "quota", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"retryDelay": "12s"}]}})
OPAQUE_429 = resp(429, {"error": {"message": "Resource has been exhausted"}})


class TtsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "a" / "v.wav"
        env = {"TTS_MODEL": "lite", "TTS_MODEL_FALLBACKS": "main, old", "GEMINI_API_KEY": "k"}
        p = mock.patch.dict("os.environ", env); p.start(); self.addCleanup(p.stop)
        self.slept = []
        p = mock.patch.object(tts.time, "sleep", side_effect=self.slept.append)
        p.start(); self.addCleanup(p.stop)
        tts._spent.clear(); self.addCleanup(tts._spent.clear)

    def post(self, answers):
        """Giả lập API: answers = {tên model: [phản hồi lần 1, lần 2, ...]} (hết thì lặp cái cuối)."""
        self.calls = []

        def fake(url, **kw):
            model = url.rsplit("/", 1)[-1].split(":")[0]
            self.calls.append(model)
            queue = answers[model]
            return queue.pop(0) if len(queue) > 1 else queue[0]
        p = mock.patch.object(tts.requests, "post", side_effect=fake)
        p.start(); self.addCleanup(p.stop)


class TtsQuotaTest(TtsCase):
    def test_daily_quota_jumps_to_fallback_without_waiting(self):
        self.post({"lite": [DAY_LIMIT], "main": [OK]})
        tts.synth("xin chào", self.out)
        self.assertEqual(self.out.read_bytes(), b"RIFFdata")
        self.assertEqual(self.calls, ["lite", "main"])
        self.assertEqual(self.slept, [])               # quota ngày: chờ vô ích -> không chờ
        # Câu sau trong cùng lượt chạy: bỏ qua luôn model đã cạn
        tts.synth("câu hai", self.out)
        self.assertEqual(self.calls, ["lite", "main", "main"])

    def test_minute_quota_waits_as_told_then_succeeds_on_same_model(self):
        self.post({"lite": [MINUTE_LIMIT, OK]})
        tts.synth("xin chào", self.out)
        self.assertEqual(self.calls, ["lite", "lite"])
        self.assertEqual(self.slept, [14.0])           # retryDelay 12s + 2s dư
        self.assertEqual(tts._spent, set())

    def test_unreadable_429_backs_off_then_gives_up_on_that_model(self):
        self.post({"lite": [OPAQUE_429], "main": [OK]})
        tts.synth("xin chào", self.out)
        self.assertEqual(self.calls, ["lite"] * 3 + ["main"])
        self.assertEqual(self.slept, [45, 90])
        self.assertIn("lite", tts._spent)

    def test_all_models_out_of_quota_raises_retry_later_error(self):
        self.post({"lite": [DAY_LIMIT], "main": [DAY_LIMIT], "old": [resp(404, text="not found")]})
        with self.assertRaises(tts.QuotaExhausted) as cm:
            tts.synth("xin chào", self.out)
        self.assertIn("lite, main", str(cm.exception))   # model sai tên không che mất lý do thật
        self.assertFalse(self.out.exists())

    def test_real_failure_is_not_reported_as_quota(self):
        self.post({"lite": [resp(400, text="API key not valid")], "main": [resp(503)],
                   "old": [resp(404, text="not found")]})
        with self.assertRaises(RuntimeError) as cm:
            tts.synth("xin chào", self.out)
        self.assertNotIsInstance(cm.exception, tts.QuotaExhausted)
        self.assertEqual(self.calls, ["lite"] + ["main"] * 3 + ["old"])   # 4xx không thử lại

    def test_empty_200_answer_is_retried_instead_of_crashing(self):
        self.post({"lite": [resp(200, {"candidates": [{"finishReason": "OTHER"}]}), OK]})
        tts.synth("xin chào", self.out)
        self.assertEqual(self.calls, ["lite", "lite"])
        self.assertEqual(self.out.read_bytes(), b"RIFFdata")

    def test_network_error_does_not_leak_api_key_into_log(self):
        boom = tts.requests.ConnectionError("https://x/models/lite:generateContent?key=SECRET")
        with mock.patch.object(tts.requests, "post", side_effect=boom), \
                self.assertLogs(tts.log, "WARNING") as logs, self.assertRaises(RuntimeError) as cm:
            tts.synth("xin chào", self.out)
        self.assertNotIn("SECRET", " ".join(logs.output) + str(cm.exception))


def isolate(case, root: Path) -> None:
    """assemble.main gán phong cách dựng (src/style.py) vào DB: test phải dùng DB + learned.yaml tạm,
    không thì ghi vào data/pipeline.db thật (trên VM là DB đang chạy)."""
    from src import db
    from src.analysis import learned
    for target, attr, val in [(db, "DB_PATH", root / "t.db"), (learned, "LEARNED_PATH", root / "learned.yaml")]:
        p = mock.patch.object(target, attr, val); p.start(); case.addCleanup(p.stop)


class AssembleQuotaExitTest(unittest.TestCase):
    def test_quota_exhausted_exits_with_retry_later_code_and_keeps_cache(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "specs").mkdir(parents=True)
        (root / "data" / "specs" / "script_9.yaml").write_text(
            "- {template: intro, seconds: 1.2, params: {}}\n"
            f"- {{template: statement, seconds: 4, voice: '{A}', params: {{text: x}}}}\n"
            f"- {{template: statement, seconds: 4, voice: '{A}', params: {{text: y}}}}\n"
            f"- {{template: statement, seconds: 4, voice: '{B}', params: {{text: z}}}}\n",
            encoding="utf-8")
        asked = []

        def fake_synth(text, wav, timeout=120):
            asked.append(text)
            if len(asked) == 2:
                raise tts.QuotaExhausted("hết quota")
            wav.write_bytes(b"x")

        engine = types.SimpleNamespace(concat=None, render_scene=None)   # khỏi cần cài manim
        isolate(self, root)
        with mock.patch.object(assemble, "ROOT", root), \
                mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "0"}), \
                mock.patch.object(assemble, "RENDER", root / "data" / "render"), \
                mock.patch.dict(sys.modules, {"src.render.engine": engine}), \
                mock.patch.object(tts, "synth", fake_synth), \
                mock.patch.object(tts, "wav_duration", lambda p: 8.0), \
                mock.patch.object(assemble.time, "sleep"), \
                mock.patch.object(sys, "argv", ["assemble", "9"]), \
                self.assertRaises(SystemExit) as cm:
            assemble.main()
        self.assertEqual(cm.exception.code, assemble.EXIT_RETRY_LATER)
        self.assertEqual(asked, [A, B])                # câu lặp ở 2 cảnh chỉ đọc MỘT lần
        self.assertTrue((root / "data" / "render" / "audio_9" / "v_01.wav").exists())

    def test_quota_exhausted_during_batch_reading_also_exits_retry_later(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "specs").mkdir(parents=True)
        (root / "data" / "specs" / "script_9.yaml").write_text(
            "- {template: intro, seconds: 1.2, params: {}}\n"
            f"- {{template: statement, seconds: 4, voice: '{A}', params: {{text: x}}}}\n"
            f"- {{template: statement, seconds: 4, voice: '{B}', params: {{text: z}}}}\n",
            encoding="utf-8")
        asked = []

        def fake_synth(text, wav, timeout=120):
            asked.append(text)
            raise tts.QuotaExhausted("hết quota")

        engine = types.SimpleNamespace(concat=None, render_scene=None)
        isolate(self, root)
        patches = [mock.patch.object(assemble, "ROOT", root),
                   mock.patch.object(assemble, "RENDER", root / "data" / "render"),
                   mock.patch.dict(sys.modules, {"src.render.engine": engine}),
                   mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "300"}),
                   mock.patch.object(tts, "synth", fake_synth),
                   mock.patch.object(sys, "argv", ["assemble", "9"])]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        with self.assertRaises(SystemExit) as cm:
            assemble.main()
        self.assertEqual(cm.exception.code, assemble.EXIT_RETRY_LATER)
        self.assertEqual(asked, [A + "\n\n" + B])      # cả bài trong MỘT lần gọi


class TrialRunTest(unittest.TestCase):
    def test_trial_run_never_touches_the_release_spec_or_style(self):
        # Ca thật 19/11: `assemble 59 --out ...` (dựng thử phong cách đọc nhanh) ghi đè spec final của bản
        # phát hành -> Kiểm định và agent Phân tích đọc sai mốc thời gian của video thật
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data" / "specs").mkdir(parents=True)
        (root / "data" / "specs" / "script_9.yaml").write_text(
            f"- {{template: statement, seconds: 4, voice: '{A}', params: {{text: x}}}}\n"
            f"- {{template: statement, seconds: 4, voice: '{B}', params: {{text: z}}}}\n", encoding="utf-8")
        isolate(self, root)

        class Stop(Exception):
            pass
        engine = types.SimpleNamespace(concat=None, render_scene=None)
        from src.audio import music
        patches = [mock.patch.object(assemble, "ROOT", root),
                   mock.patch.object(assemble, "RENDER", root / "data" / "render"),
                   mock.patch.dict(sys.modules, {"src.render.engine": engine}),
                   mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "0"}),
                   mock.patch.object(tts, "synth", lambda text, wav, timeout=120: wav.write_bytes(b"x")),
                   mock.patch.object(tts, "wav_duration", lambda p: 8.0),
                   mock.patch.object(assemble.time, "sleep"),
                   mock.patch.object(music, "select", side_effect=Stop),     # dừng ngay sau khi ghi spec final
                   mock.patch("src.assets_db.init_assets", mock.Mock()),
                   mock.patch.object(sys, "argv", ["assemble", "9", "--out", str(root / "tmp" / "x.mp4")])]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        (root / "tmp").mkdir()
        with self.assertRaises(Stop):
            assemble.main()
        self.assertTrue((root / "tmp" / "x.final.yaml").exists())
        self.assertFalse((root / "data" / "specs" / "script_9_final.yaml").exists())
        from src import db, style
        con = db.connect(); self.addCleanup(con.close)
        self.assertIsNone(style.get(con, 9))                 # chạy thử không gán phong cách mới


if __name__ == "__main__":
    unittest.main()
