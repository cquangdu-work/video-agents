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

    def test_share_seconds_follows_spec_weights_and_keeps_total(self):
        self.assertEqual(assemble.share_seconds(12.0, [4, 4, 4]), [4.0, 4.0, 4.0])
        parts = assemble.share_seconds(9.0, [2, 4])
        self.assertAlmostEqual(sum(parts), 9.0)
        self.assertAlmostEqual(parts[1], 2 * parts[0])
        self.assertAlmostEqual(sum(assemble.share_seconds(5.0, [None, 0])), 5.0)   # spec thiếu seconds


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

        def fake_synth(text, wav):
            asked.append(text)
            if len(asked) == 2:
                raise tts.QuotaExhausted("hết quota")
            wav.write_bytes(b"x")

        engine = types.SimpleNamespace(concat=None, render_scene=None)   # khỏi cần cài manim
        with mock.patch.object(assemble, "ROOT", root), \
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


if __name__ == "__main__":
    unittest.main()
