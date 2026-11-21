"""Khoá Gemini dự phòng (src/gemini_key.py) — ca thật 22/11/2026: khoá kênh Hàn bị Google chặn (403), lượt sáng mất
video. Không gọi mạng: requests.post giả."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import gemini_key
from src import telegram_bot as tg


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


BLOCKED = Resp(403, {"error": {"status": "PERMISSION_DENIED",
                               "message": "The Gemini API free tier is not available for this project."}})


class GeminiKeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(gemini_key, "NOTICE", Path(self.tmp.name) / "notice.txt"); p.start(); self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "MAIN", "GEMINI_API_KEY_FALLBACK": "SPARE"})
        env.start(); self.addCleanup(env.stop)
        os.environ.pop("GEMINI_KEY_CHECKED", None)
        self.sent = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.sent.append(t) or 1)
        p.start(); self.addCleanup(p.stop)

    def post(self, by_key):
        return lambda url, params=None, **kw: by_key[params["key"]]

    def test_blocked_main_key_switches_to_fallback_and_tells_du_once_a_day(self):
        post = self.post({"MAIN": BLOCKED, "SPARE": Resp(200)})
        self.assertEqual(gemini_key.ensure(post=post), "fallback")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "SPARE")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("khoá dự phòng", self.sent[0])
        # tiến trình con của daily: không kiểm lại
        self.assertEqual(gemini_key.ensure(post=post), "skip")
        # lượt khác trong cùng ngày: không báo lại
        os.environ.pop("GEMINI_KEY_CHECKED"); os.environ["GEMINI_API_KEY"] = "MAIN"
        gemini_key.ensure(post=post)
        self.assertEqual(len(self.sent), 1)

    def test_other_errors_keep_the_main_key(self):
        for resp in (Resp(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), Resp(503), Resp(200)):
            os.environ.pop("GEMINI_KEY_CHECKED", None); os.environ["GEMINI_API_KEY"] = "MAIN"
            self.assertEqual(gemini_key.ensure(post=self.post({"MAIN": resp, "SPARE": Resp(200)})), "primary")
            self.assertEqual(os.environ["GEMINI_API_KEY"], "MAIN")
        self.assertEqual(self.sent, [])

    def test_no_fallback_configured_or_both_blocked(self):
        os.environ.pop("GEMINI_API_KEY_FALLBACK")
        self.assertEqual(gemini_key.ensure(post=self.post({"MAIN": BLOCKED})), "skip")
        os.environ.pop("GEMINI_KEY_CHECKED"); os.environ["GEMINI_API_KEY_FALLBACK"] = "SPARE"
        self.assertEqual(gemini_key.ensure(post=self.post({"MAIN": BLOCKED, "SPARE": BLOCKED})), "primary")
        self.assertEqual(os.environ["GEMINI_API_KEY"], "MAIN")


if __name__ == "__main__":
    unittest.main()
