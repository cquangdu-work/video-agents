"""Test đẩy video vào hộp thư TikTok (src/publish/tiktok.py) và chỗ bot Telegram dùng nó.
Không gọi mạng: mọi lời gọi TikTok đều giả lập theo đúng khuôn trong tài liệu chính thức.

    python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import types
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import db, review
from src import telegram_bot as tg
from src.publish import tiktok
from tests.test_phase4 import CFG, DbCase, cb, text

ENV = {"TIKTOK_CLIENT_KEY": "ck", "TIKTOK_CLIENT_SECRET": "cs"}
CB = "https://cquangdu-work.github.io/thegioiquaconso/tiktok-callback.html"


def resp(status=200, body=None):
    return types.SimpleNamespace(status_code=status, content=b"x", text=json.dumps(body or {}),
                                 json=lambda: body or {})


class TikTokCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.tok = Path(d.name) / "tt.json"
        for p in (mock.patch.object(tiktok, "TOKEN_PATH", self.tok), mock.patch.dict(os.environ, ENV)):
            p.start(); self.addCleanup(p.stop)

    def save(self, expires_in=7200, now=None):
        return tiktok._save({"access_token": "AT", "refresh_token": "RT", "open_id": "u1",
                             "scope": "user.info.basic,video.upload", "expires_in": expires_in,
                             "refresh_expires_in": 180 * 86400}, now)


class AuthTest(TikTokCase):
    def test_link_carries_client_scopes_redirect_and_state(self):
        a = tiktok.start_auth()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(a["url"]).query)
        self.assertEqual(q["client_key"], ["ck"])
        self.assertEqual(q["scope"], ["user.info.basic,video.upload"])
        self.assertEqual(q["redirect_uri"], [CB])
        self.assertEqual(q["state"], [a["state"]])

    def test_pasted_address_is_checked_then_exchanged(self):
        with self.assertRaisesRegex(tiktok.TikTokAuthError, "đã cũ"):
            tiktok.finish_auth(f"{CB}?code=x&scopes=video.upload&state=cu", "moi")
        with self.assertRaisesRegex(tiktok.TikTokAuthError, "video.upload"):
            tiktok.finish_auth(f"{CB}?code=x&scopes=user.info.basic&state=S", "S")
        post = mock.Mock(return_value=resp(200, {"access_token": "AT", "refresh_token": "RT", "open_id": "u1",
                                                 "expires_in": 86400, "refresh_expires_in": 15552000,
                                                 "scope": "user.info.basic,video.upload"}))
        with mock.patch.object(tiktok.requests, "post", post):
            tiktok.finish_auth(f"Đây nè: {CB}?code=abc%2Adef%21&scopes=user.info.basic%2Cvideo.upload&state=S", "S")
        data = post.call_args.kwargs["data"]
        self.assertEqual((data["code"], data["grant_type"], data["redirect_uri"]),
                         ("abc*def!", "authorization_code", CB))     # mã đã được giải mã URL
        saved = json.loads(self.tok.read_text())
        self.assertEqual((saved["access_token"], saved["refresh_token"]), ("AT", "RT"))

    def test_expired_access_token_is_refreshed_and_the_new_refresh_token_kept(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.save(expires_in=7200, now=now)
        self.assertEqual(tiktok.access_token(now + timedelta(minutes=30)), "AT")       # còn hạn
        post = mock.Mock(return_value=resp(200, {"access_token": "AT2", "refresh_token": "RT2",
                                                 "expires_in": 7200, "refresh_expires_in": 15552000}))
        with mock.patch.object(tiktok.requests, "post", post):
            self.assertEqual(tiktok.access_token(now + timedelta(hours=3)), "AT2")
        self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "RT")
        self.assertEqual(json.loads(self.tok.read_text())["refresh_token"], "RT2")    # token xoay vòng
        bad = mock.Mock(return_value=resp(400, {"error": "invalid_grant"}))
        with mock.patch.object(tiktok.requests, "post", bad), \
                self.assertRaisesRegex(tiktok.TikTokAuthError, "/tiktok"):
            tiktok.access_token(now + timedelta(days=3))


class UploadTest(TikTokCase):
    def test_chunk_rules(self):
        self.assertEqual(tiktok.chunk_plan(4_000_000), (4_000_000, 1))                 # < 5 MB: gửi nguyên
        self.assertEqual(tiktok.chunk_plan(6_000_000), (6_000_000, 1))                 # video kênh ~6 MB
        self.assertEqual(tiktok.chunk_plan(61_000_123), (10_000_000, 6))               # dư dồn vào khúc cuối

    def run_upload(self, size, statuses=("PROCESSING_UPLOAD", "SEND_TO_USER_INBOX")):
        self.save()
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.mp4"; f.write_bytes(b"\0" * size)
            calls = list(statuses)

            def api(method, url, **kw):
                if url.endswith("/inbox/video/init/"):
                    self.init_body = kw["json"]
                    return resp(200, {"data": {"publish_id": "p1", "upload_url": "https://up/1"},
                                      "error": {"code": "ok"}})
                return resp(200, {"data": {"status": calls.pop(0)}, "error": {"code": "ok"}})
            put = mock.Mock(return_value=resp(201))
            with mock.patch.object(tiktok.requests, "request", api), \
                    mock.patch.object(tiktok.requests, "put", put), mock.patch.object(tiktok.time, "sleep"):
                res = tiktok.upload_draft(f)
        return res, put

    def test_single_chunk_upload_reaches_the_inbox(self):
        res, put = self.run_upload(1000)
        self.assertEqual(res, {"publish_id": "p1", "status": "SEND_TO_USER_INBOX"})
        self.assertEqual(self.init_body["source_info"], {"source": "FILE_UPLOAD", "video_size": 1000,
                                                         "chunk_size": 1000, "total_chunk_count": 1})
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Range"], "bytes 0-999/1000")

    def test_large_file_is_sent_in_order_with_the_rest_in_the_last_chunk(self):
        with mock.patch.object(tiktok, "SINGLE_CHUNK_MAX", 100), mock.patch.object(tiktok, "CHUNK", 40):
            _, put = self.run_upload(130)
        self.assertEqual([c.kwargs["headers"]["Content-Range"] for c in put.call_args_list],
                         ["bytes 0-39/130", "bytes 40-79/130", "bytes 80-129/130"])   # 130 // 40 = 3 khúc

    def test_processing_failure_is_reported(self):
        with self.assertRaisesRegex(tiktok.TikTokUploadError, "lỗi"):
            self.run_upload(1000, statuses=("FAILED",))


class BotTest(DbCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("send_message", "send_video", "send_document", "answer_callback", "clear_buttons"):
            p = mock.patch.object(tg, name, side_effect=lambda *a, _n=name, **k: self.sent.append((_n, a, k)) or 77)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, ENV); p.start(); self.addCleanup(p.stop)
        self.vid = self.new_video()
        db.update_video(self.con, self.vid, tg_message_id=50,
                        description="Tóm tắt.\n\nNguồn: World Bank — https://data\n\nNhạc nền: New Land — ALBIS"
                                    " (YouTube Audio Library)\n\nGiọng AI.\n\n#thegioiquaconso #Shorts")
        self.cfg = json.loads(json.dumps(CFG))
        self.cfg["publish"]["tiktok"] = {"enabled": True}

    def msgs(self):
        return [c[1][0] for c in self.sent if c[0] == "send_message"]

    def test_approved_video_goes_to_the_tiktok_inbox_once_with_a_caption(self):
        with mock.patch.object(tiktok, "upload_draft", return_value={"publish_id": "p1",
                                                                     "status": "SEND_TO_USER_INBOX"}) as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
            review.handle_update(self.con, cb(f"tt:{self.vid}"), self.cfg)      # bấm lại: không đẩy trùng
        self.assertEqual(up.call_count, 1)
        last = self.msgs()[-1]
        self.assertIn("hộp thư", last)
        for part in ("Tiêu đề", "Nguồn: World Bank", "Nhạc nền: New Land", "#thegioiquaconso"):
            self.assertIn(part, last)
        self.assertNotIn("Giọng AI", last)

    def test_not_connected_is_mentioned_once_a_day_and_never_blocks_youtube(self):
        err = tiktok.TikTokAuthError("Chưa kết nối TikTok — gửi /tiktok")
        with mock.patch.object(tiktok, "upload_draft", side_effect=err):
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
            review.push_tiktok(self.con, db.get_video(self.con, self.vid), self.cfg)
        self.assertEqual(sum("/tiktok" in m for m in self.msgs()), 1)
        self.assertEqual(db.get_video(self.con, self.vid)["status"], "approved")   # gói YouTube vẫn gửi

    def test_upload_error_offers_a_retry(self):
        with mock.patch.object(tiktok, "upload_draft", side_effect=tiktok.TikTokUploadError("503")):
            with self.assertLogs("review", level="ERROR"):
                review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        self.assertEqual(self.sent[-1][2]["buttons"], [[("🔁 Thử lại TikTok", f"tt:{self.vid}")]])

    def test_no_tiktok_app_yet_means_silence(self):
        with mock.patch.dict(os.environ, {"TIKTOK_CLIENT_KEY": ""}), \
                mock.patch.object(tiktok, "upload_draft") as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        up.assert_not_called()
        self.assertFalse(any("TikTok" in m for m in self.msgs()))

    def test_video_left_in_the_inbox_is_reminded_once(self):
        # Ca thật 27/11/2026 (kênh Hàn): bot đẩy đủ 11 video, #6 nằm trong hộp thư từ 25/11 mà Du không thấy
        from datetime import datetime, timedelta, timezone
        with mock.patch.object(tiktok, "upload_draft", return_value={"publish_id": "p1",
                                                                     "status": "SEND_TO_USER_INBOX"}):
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        pushed = datetime.fromisoformat(db.get_state(self.con, f"tt_pushed_at_{self.vid}"))
        inbox = lambda pid: {"status": "SEND_TO_USER_INBOX"}
        self.sent.clear()
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, pushed + timedelta(hours=2), inbox), [])
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, pushed + timedelta(hours=7), inbox),
                         [self.vid])
        self.assertIn("vẫn nằm trong hộp thư", self.msgs()[-1])
        self.assertIn("#thegioiquaconso", self.msgs()[-1])                 # kèm lại chú thích
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, pushed + timedelta(hours=30), inbox), [])
        # Du đã đăng thì thôi hỏi; TikTok báo lỗi thì nút đẩy lại dùng được
        other = db.upsert_video(self.con, 7, "output/final_7.mp4", "T7", "D", ["a"], [])
        db.set_state(self.con, f"tt_publish_{other}", "p2")                # lần đẩy cũ (chưa có mốc giờ)
        done = lambda pid: {"status": "PUBLISH_COMPLETE"}
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, None, done), [])
        self.assertEqual(db.get_state(self.con, f"tt_done_{other}"), "PUBLISH_COMPLETE")
        third = db.upsert_video(self.con, 8, "output/final_8.mp4", "T8", "D", ["a"], [])
        db.set_state(self.con, f"tt_publish_{third}", "p3")
        failed = lambda pid: {"status": "FAILED", "fail_reason": "file_format_check_failed"}
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, None, failed), [third])
        self.assertEqual(self.sent[-1][2]["buttons"], [[("🔁 Đẩy lại TikTok", f"tt:{third}")]])
        self.assertEqual(db.get_state(self.con, f"tt_publish_{third}"), "")
        self.cfg["publish"]["tiktok"]["enabled"] = False
        self.assertEqual(review.remind_tiktok_inbox(self.con, self.cfg, None, failed), [])

    def test_connect_command_and_pasted_callback(self):
        review.handle_update(self.con, text("/tiktok"), self.cfg)
        self.assertIn("tiktok.com/v2/auth/authorize", self.msgs()[-1])
        state = db.get_state(self.con, "tt_auth_state")
        with mock.patch.object(tiktok, "finish_auth") as fin, \
                mock.patch.object(tiktok, "whoami", return_value={"display_name": "thegioiquaconso"}):
            review.handle_update(self.con, text(f"{CB}?code=c&scopes=video.upload&state={state}"), self.cfg)
        self.assertEqual(fin.call_args.args[1], state)
        self.assertIn("Đã kết nối TikTok: thegioiquaconso", self.msgs()[-1])
        self.assertEqual(db.get_state(self.con, "tt_auth_state"), "")


if __name__ == "__main__":
    unittest.main()
