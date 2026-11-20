"""Test đăng Reels lên Trang Facebook (src/publish/facebook.py) và chỗ bot Telegram dùng nó.
Không gọi mạng: mọi lời gọi Graph API đều giả lập theo khuôn trong tài liệu Reels Publishing API.

    python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from src import db, review
from src import telegram_bot as tg
from src.publish import facebook
from tests.test_phase4 import CFG, DbCase, cb, text

ENV = {"FACEBOOK_APP_ID": "app1", "FACEBOOK_APP_SECRET": "sec1"}


def resp(status=200, body=None):
    body = {} if body is None else body
    return types.SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body)


class FbCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.tok = self.dir / "fb.json"
        for p in (mock.patch.object(facebook, "TOKEN_PATH", self.tok), mock.patch.dict(os.environ, ENV),
                  mock.patch.object(facebook.time, "sleep")):
            p.start(); self.addCleanup(p.stop)


class ConnectTest(FbCase):
    def graph(self, perms=("pages_show_list", "pages_read_engagement", "pages_manage_posts"), pages=None):
        pages = pages if pages is not None else [{"id": "123", "name": "Thế giới qua con số",
                                                   "access_token": "PAGE", "tasks": ["CREATE_CONTENT"]}]

        def get(url, params=None, **kw):
            if url.endswith("/oauth/access_token"):
                self.assertEqual(params["grant_type"], "fb_exchange_token")
                self.assertEqual(params["client_secret"], "sec1")
                return resp(body={"access_token": "LONG"})
            self.assertEqual(params["access_token"], "LONG")      # mọi bước sau dùng token dài hạn
            if url.endswith("/me/permissions"):
                return resp(body={"data": [{"permission": p, "status": "granted"} for p in perms]})
            if url.endswith("/me/accounts"):
                return resp(body={"data": pages})
            raise AssertionError(url)
        return mock.patch.object(facebook.requests, "get", side_effect=get)

    def test_short_token_becomes_a_saved_page_token(self):
        with self.graph():
            who = facebook.connect("x" * 40)
        self.assertEqual(who, {"page_id": "123", "page_name": "Thế giới qua con số"})
        saved = json.loads(self.tok.read_text(encoding="utf-8"))
        self.assertEqual((saved["page_id"], saved["page_token"]), ("123", "PAGE"))
        self.assertTrue(facebook.connected())

    def test_missing_permission_is_named(self):
        with self.graph(perms=("pages_show_list",)), self.assertRaises(facebook.FacebookAuthError) as e:
            facebook.connect("x" * 40)
        self.assertIn("pages_manage_posts", str(e.exception))
        self.assertFalse(self.tok.exists())

    def test_page_choice(self):
        a = {"id": "1", "name": "A", "access_token": "t", "tasks": ["CREATE_CONTENT"]}
        b = {"id": "2", "name": "B", "access_token": "t", "tasks": ["ANALYZE"]}
        self.assertEqual(facebook.pick_page([a, b], "1")["name"], "A")
        with self.assertRaisesRegex(facebook.FacebookAuthError, "nhiều Trang"):
            facebook.pick_page([a, b])
        with self.assertRaisesRegex(facebook.FacebookAuthError, "không có quyền đăng"):
            facebook.pick_page([b])
        with self.assertRaisesRegex(facebook.FacebookAuthError, "không quản lý Trang nào"):
            facebook.pick_page([])

    def test_no_app_keys(self):
        with mock.patch.dict(os.environ, {"FACEBOOK_APP_ID": ""}), self.assertRaises(facebook.FacebookAuthError):
            facebook.connect("x" * 40)

    def test_oauth_error_is_an_auth_error(self):
        with self.assertRaises(facebook.FacebookAuthError):
            facebook._check(resp(400, {"error": {"message": "Session expired", "type": "OAuthException", "code": 190}}))
        with self.assertRaises(facebook.FacebookUploadError):
            facebook._check(resp(500, {"error": {"message": "boom", "code": 1}}))


class UploadTest(FbCase):
    def setUp(self):
        super().setUp()
        facebook._save({"id": "123", "name": "Kênh", "access_token": "PAGE"})
        self.video = self.dir / "v.mp4"
        self.video.write_bytes(b"\0" * 1000)
        self.posts = []

    def fake(self, statuses=({"video_status": "ready"},)):
        seq = list(statuses)

        def post(url, json=None, data=None, headers=None, **kw):
            self.posts.append((url, json, data, headers))
            if url.endswith("/123/video_reels") and json:
                return resp(body={"video_id": "999", "upload_url": "https://rupload.facebook.com/video-upload/999"})
            if "rupload.facebook.com" in url:
                self.assertEqual(headers["Authorization"], "OAuth PAGE")
                self.assertEqual((headers["offset"], headers["file_size"]), ("0", "1000"))
                return resp(body={"success": True})
            if url.endswith("/123/video_reels"):
                return resp(body={"success": True})
            raise AssertionError(url)

        def get(url, params=None, **kw):
            return resp(body={"status": seq.pop(0) if len(seq) > 1 else seq[0]})
        return mock.patch.object(facebook.requests, "post", side_effect=post), \
            mock.patch.object(facebook.requests, "get", side_effect=get)

    def test_three_steps_then_scheduled_publish_with_ai_label(self):
        at = int(time.time()) + 3600
        p, g = self.fake([{"video_status": "processing"}, {"video_status": "ready"}])
        with p, g:
            res = facebook.upload_reel(self.video, "Chú thích", "SCHEDULED", at)
        self.assertEqual(res["url"], "https://www.facebook.com/reel/999")
        self.assertEqual(res["status"], "ready")
        self.assertEqual(len(self.posts), 3)
        finish = self.posts[2][2]
        self.assertEqual(finish["upload_phase"], "finish")
        self.assertEqual((finish["video_id"], finish["video_state"]), ("999", "SCHEDULED"))
        self.assertEqual(finish["scheduled_publish_time"], at)
        self.assertEqual(finish["is_ai_generated"], "true")

    def test_bad_schedule_is_refused_before_uploading(self):
        p, g = self.fake()
        with p, g, self.assertRaises(ValueError):
            facebook.upload_reel(self.video, "x", "SCHEDULED", int(time.time()) + 60)   # dưới 10 phút
        self.assertEqual(self.posts, [])

    def test_processing_error_is_reported(self):
        p, g = self.fake([{"video_status": "processing",
                           "processing_phase": {"status": "error", "error": {"message": "codec"}}}])
        with p, g, self.assertRaisesRegex(facebook.FacebookUploadError, "processing_phase"):
            facebook.upload_reel(self.video, "x")

    def test_caption_drops_the_youtube_only_hashtag(self):
        cap = facebook.caption({"title": "Tiêu đề", "description": "Tóm tắt.\n\n#thegioiquaconso #Shorts #GDP"})
        self.assertEqual(cap, "Tiêu đề\n\nTóm tắt.\n\n#thegioiquaconso #GDP")


class BotTest(DbCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("send_message", "send_video", "send_document", "answer_callback", "clear_buttons",
                     "delete_message"):
            p = mock.patch.object(tg, name, side_effect=lambda *a, _n=name, **k: self.sent.append((_n, a, k)) or 77)
            p.start(); self.addCleanup(p.stop)
        for p in (mock.patch.dict(os.environ, {**ENV, "TIKTOK_CLIENT_KEY": ""}),
                  mock.patch.object(facebook, "TOKEN_PATH", self.root / "fb.json")):
            p.start(); self.addCleanup(p.stop)
        self.vid = self.new_video()
        db.update_video(self.con, self.vid, tg_message_id=50, description="Tóm tắt.\n\n#thegioiquaconso #Shorts")
        self.cfg = json.loads(json.dumps(CFG))
        self.cfg["publish"]["facebook"] = {"enabled": True, "video_state": "SCHEDULED",
                                           "publish_time_local": "19:00", "utc_offset_hours": 7}

    def msgs(self):
        return [c[1][0] for c in self.sent if c[0] == "send_message"]

    def connect(self):
        facebook._save({"id": "123", "name": "Kênh", "access_token": "PAGE"})

    def test_approved_video_becomes_a_scheduled_reel_once(self):
        self.connect()
        res = {"video_id": "999", "url": "https://www.facebook.com/reel/999", "state": "SCHEDULED", "status": "ready"}
        with mock.patch.object(facebook, "upload_reel", return_value=res) as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
            review.handle_update(self.con, cb(f"fb:{self.vid}"), self.cfg)     # bấm lại: không đăng đôi
        self.assertEqual(up.call_count, 1)
        args = up.call_args.args
        self.assertEqual(args[2], "SCHEDULED")
        self.assertGreater(args[3], time.time() + 600)
        self.assertNotIn("#Shorts", args[1])
        self.assertIn("facebook.com/reel/999", self.msgs()[-1])
        self.assertIn("19:00", self.msgs()[-1])

    def test_not_connected_is_mentioned_once_a_day(self):
        with mock.patch.object(facebook, "upload_reel") as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
            review.push_facebook(self.con, db.get_video(self.con, self.vid), self.cfg)
        up.assert_not_called()
        self.assertEqual(sum("/facebook" in m for m in self.msgs()), 1)

    def test_error_frees_the_lock_and_offers_a_retry(self):
        self.connect()
        with mock.patch.object(facebook, "upload_reel", side_effect=facebook.FacebookUploadError("503")):
            with self.assertLogs("review", level="ERROR"):
                review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        self.assertEqual(self.sent[-1][2]["buttons"], [[("🔁 Thử lại Facebook", f"fb:{self.vid}")]])
        self.assertFalse(db.get_state(self.con, f"fb_publish_{self.vid}"))

    def test_no_facebook_app_yet_means_silence(self):
        with mock.patch.dict(os.environ, {"FACEBOOK_APP_ID": ""}), mock.patch.object(facebook, "upload_reel") as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        up.assert_not_called()
        self.assertFalse(any("Facebook" in m for m in self.msgs()))

    def test_long_videos_are_not_sent_as_reels(self):
        self.connect()
        with mock.patch("src.assemble.ffprobe_duration", return_value=95.0), \
                mock.patch.object(facebook, "upload_reel") as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
        up.assert_not_called()
        self.assertIn("tối đa 90 giây", self.msgs()[-1])

    def test_connect_command_deletes_the_token_message(self):
        review.handle_update(self.con, text("/facebook"), self.cfg)
        self.assertIn("Graph API Explorer", self.msgs()[-1])
        with mock.patch.object(facebook, "connect", return_value={"page_id": "123", "page_name": "Kênh"}) as c:
            review.handle_update(self.con, text("/facebook EAAB" + "x" * 40), self.cfg)
        self.assertEqual(c.call_args.args[0], "EAAB" + "x" * 40)
        self.assertIn(("delete_message", (99,), {}), self.sent)
        self.assertIn("Đã kết nối Trang Facebook: Kênh", self.msgs()[-1])


if __name__ == "__main__":
    unittest.main()
