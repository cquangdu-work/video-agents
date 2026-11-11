"""Test agent Kiểm định — không gọi mạng, không cần ffmpeg.

    python -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import qc


class NarrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = mock.patch.object(qc, "ROOT", self.root); p.start(); self.addCleanup(p.stop)

    def meta(self, spoken, heard, script=None, sid=1):
        d = self.root / "data" / "render" / f"audio_{sid}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"spoken_words": spoken, "heard_words": heard}))
        p = mock.patch.object(qc, "script_tokens", return_value=script)
        p.start(); self.addCleanup(p.stop)
        return qc.check_narration(sid)

    def test_good_video_passes(self):
        c = self.meta(spoken=198, heard=202, script=198)
        self.assertTrue(c["ok"]); self.assertEqual(c["value"], "202/198 từ")

    def test_repeated_narration_is_caught(self):
        # Ca thật trên VM 11/11/2026: mỗi câu bị đọc 2-3 lần, các phép kiểm cũ đều cho qua
        c = self.meta(spoken=121, heard=252, script=121)
        self.assertFalse(c["ok"]); self.assertIn("nghe được 252 từ, lẽ ra 121", c["value"])

    def test_truncated_narration_is_caught(self):
        self.assertFalse(self.meta(spoken=200, heard=140, script=200)["ok"])

    def test_spec_that_dropped_sentences_is_caught(self):
        c = self.meta(spoken=80, heard=82, script=121)
        self.assertFalse(c["ok"]); self.assertIn("kịch bản có 121", c["value"])

    def test_script_missing_from_db_still_checks_the_audio(self):
        self.assertTrue(self.meta(spoken=100, heard=101, script=None)["ok"])
        self.assertFalse(self.meta(spoken=100, heard=210, script=None)["ok"])

    def test_video_built_by_old_code_is_not_blocked(self):
        c = qc.check_narration(77)
        self.assertTrue(c["ok"]); self.assertIn("không có số liệu", c["value"])


class VisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "data" / "render").mkdir(parents=True)
        (root / "data" / "render" / "qc_frame.png").write_bytes(b"png")
        for target, attr, val in [(qc, "ROOT", root), (qc.subprocess, "run", mock.Mock())]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.spec = [{"template": "intro", "seconds": 1.2}] + [
            {"template": "statement", "seconds": 4, "voice": f"câu {i}"} for i in range(12)]

    def answers(self, *items):
        """items: dict = phán quyết của model, Exception = lỗi gọi model."""
        def fake(url, **kw):
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            r = mock.Mock()
            r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(item)}]}}]}
            return r
        queue = list(items)
        p = mock.patch.object(qc.requests, "post", side_effect=fake)
        self.post = p.start(); self.addCleanup(p.stop)

    def test_samples_are_spread_over_the_whole_video(self):
        self.assertEqual(qc.spread(list(range(12)), 6), [0, 2, 4, 7, 9, 11])
        self.assertEqual(qc.spread([1, 2], 6), [1, 2])
        self.answers(*[{"ok": True}] * 6)
        c = qc.check_visuals_match(Path("v.mp4"), self.spec, 49.2)
        self.assertEqual(self.post.call_count, 6)
        self.assertEqual(c, {"name": "Hình khớp lời (AI soát)", "value": "đã soát 6/6 cảnh", "ok": True})
        asked = [call.kwargs["json"]["contents"][0]["parts"][1]["text"] for call in self.post.call_args_list]
        self.assertIn("câu 11", asked[-1])               # cảnh CUỐI cũng được nhìn

    def test_failed_model_calls_are_reported_not_counted_as_checked(self):
        self.answers({"ok": True}, RuntimeError("503"), {"ok": True}, {"ok": True},
                     ValueError("không phải JSON"), {"ok": True})
        c = qc.check_visuals_match(Path("v.mp4"), self.spec, 49.2)
        self.assertTrue(c["ok"])                         # không chặn video vì model sập
        self.assertIn("đã soát 4/6 cảnh", c["value"])
        self.assertIn("2 cảnh model không trả lời", c["value"])

    def test_mismatch_confirmed_twice_blocks_the_video(self):
        bad = {"ok": False, "kind": "number", "image_number": "54.000",
               "note": "hình ghi 54.000, lời nói 540.000"}
        self.answers(bad, bad, *[{"ok": True}] * 5)
        c = qc.check_visuals_match(Path("v.mp4"), self.spec, 49.2)
        self.assertFalse(c["ok"]); self.assertIn("54.000", c["value"])
        self.assertEqual(self.post.call_count, 7)        # cảnh bị nghi được hỏi 2 lần

    def test_one_off_false_alarm_does_not_block_the_video(self):
        self.answers({"ok": False, "kind": "clipped", "note": "chữ bị cắt"}, {"ok": True},
                     *[{"ok": True}] * 5)
        c = qc.check_visuals_match(Path("v.mp4"), self.spec, 49.2)
        self.assertEqual(c["value"], "đã soát 6/6 cảnh"); self.assertTrue(c["ok"])

    def test_nitpicks_outside_the_three_error_kinds_are_ignored(self):
        # Ca thật (video #4): "lời đọc có thêm từ 'nữa'", "chữ bị đảo" — hình chỉ tóm ý, không phải lỗi
        self.answers({"ok": False, "note": "lời đọc có thêm từ 'nữa'"},
                     {"ok": False, "kind": "other", "note": "chữ bị đảo"}, *[{"ok": True}] * 4)
        c = qc.check_visuals_match(Path("v.mp4"), self.spec, 49.2)
        self.assertTrue(c["ok"]); self.assertEqual(self.post.call_count, 6)   # không cần hỏi lại

    def test_number_claims_are_rechecked_by_code(self):
        voice = "Có trung bình 540.000 người tử vong mỗi năm, tăng 38,4%."
        claim = lambda n: {"ok": False, "kind": "number", "image_number": n, "note": "số khác"}
        self.assertTrue(qc.real_issue(claim("54.000"), voice))       # sai thật
        self.assertFalse(qc.real_issue(claim("540.000"), voice))     # model đọc nhầm: số có trong lời
        self.assertFalse(qc.real_issue(claim("38,4%"), voice))
        self.assertFalse(qc.real_issue(claim("8.030"), "Có đúng tám nghìn không trăm ba mươi hệ thống."))
        self.assertTrue(qc.real_issue({"ok": False, "kind": "opposite"}, voice))
        self.assertFalse(qc.real_issue({"ok": True, "kind": "clipped"}, voice))


if __name__ == "__main__":
    unittest.main()
