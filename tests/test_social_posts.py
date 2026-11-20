"""Test bài viết Facebook kèm video (kênh Việt, src/fb_post.py) và Instagram Reels (kênh Hàn,
src/publish/instagram.py) — không gọi mạng, không gọi LLM.

    python -m unittest tests.test_social_posts -v
"""
import json
import os
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import db, fb_post, review
from src import telegram_bot as tg
from src.publish import facebook, instagram
from tests.test_phase4 import CFG, DbCase, cb, text

SUMMARY = ("지표: x. Tỷ lệ che phủ rừng (%). Năm 2024: Việt Nam 47,2%; Hàn Quốc 64,4%.\n"
           "Việt Nam theo năm: 1990: 28,8; 2024: 47,2.\nHàn Quốc theo năm: 1990: 67,9; 2024: 64,4.")
IDEA = {"title": "Tỷ lệ che phủ rừng: Việt Nam và Hàn Quốc", "summary": SUMMARY, "source_name": "World Bank Open Data"}
VOICES = ["Rừng Việt Nam tăng từ 28,8% lên 47,2% trong 34 năm.", "Hàn Quốc vẫn cao hơn: 64,4%."]
GOOD = ("Rừng Việt Nam tăng từ 28,8% năm 1990 lên 47,2% năm 2024 — gần gấp rưỡi chỉ sau một thế hệ.\n\n"
        "Trong cùng thời gian, Hàn Quốc vẫn giữ mức 64,4%, cao hơn Việt Nam. Nghĩa là cứ 10 mét vuông đất ở Việt Nam"
        " thì gần 5 mét vuông là rừng.\n\nBạn nghĩ nơi bạn sống đã xanh hơn so với 10 năm trước chưa?\n\n"
        "Nguồn: World Bank Open Data")


def resp(body, status=200):
    return types.SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body)


class FbPostTextTest(unittest.TestCase):
    def test_gates(self):
        self.assertEqual(fb_post.problems(GOOD, IDEA, VOICES), [])
        bad = fb_post.problems(GOOD.replace("47,2% năm 2024", "52,9% năm 2024"), IDEA, VOICES)
        self.assertTrue(any("không có trong nguồn" in p for p in bad))
        self.assertTrue(any("link" in p for p in fb_post.problems(GOOD + " https://x.com", IDEA, VOICES)))
        self.assertTrue(any("độ dài" in p for p in fb_post.problems("Ngắn quá.", IDEA, VOICES)))

    def test_draft_retries_then_gives_up(self):
        answers = iter([GOOD.replace("47,2%", "99%"), GOOD + "\n#rung #moitruong"])
        got = fb_post.draft(IDEA, VOICES, {"channel": {"name": "K", "description": "d"}},
                            run=lambda **k: next(answers))
        self.assertEqual(got, GOOD)                              # dòng hashtag model tự chèn bị gọt
        self.assertEqual(fb_post.draft(IDEA, VOICES, {"channel": {"name": "K", "description": "d"}},
                                       run=lambda **k: "Sai lầm! 99% người không biết."), "")

    def test_hashtags_and_frame_choice(self):
        cfg = {"publish": {"hashtags_fixed": ["#thegioiquaconso", "#Shorts"]}}
        self.assertTrue(fb_post.with_hashtags("Bài", cfg).endswith("#thegioiquaconso"))
        props = {"duration": 30, "scenes": [{"kind": "statement", "start": 0, "end": 3},
                                            {"kind": "big_number", "start": 3, "end": 7},
                                            {"kind": "map", "start": 7, "end": 13}]}
        self.assertEqual(fb_post.pick_frame(props), (381, "map"))      # (13 - 0,3) * 30


class FacebookPhotoApiTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        p = mock.patch.object(facebook, "TOKEN_PATH", self.dir / "fb.json"); p.start(); self.addCleanup(p.stop)
        facebook._save({"id": "123", "name": "Kênh", "access_token": "PAGE"})
        self.img = self.dir / "a.jpg"; self.img.write_bytes(b"\xff\xd8x")

    def test_scheduled_photo_post_follows_the_documented_flow(self):
        calls = []

        def post(url, data=None, files=None, **kw):
            calls.append((url, data, files))
            return resp({"id": "PH1"} if url.endswith("/photos") else {"id": "123_999"})
        at = int(time.time()) + 3600
        res = facebook.post_photo(self.img, "Bài viết", at, post=post)
        self.assertEqual(res, {"id": "123_999", "scheduled": True})
        (u1, d1, f1), (u2, d2, _) = calls
        self.assertTrue(u1.endswith("/123/photos") and "source" in f1)
        self.assertEqual((d1["published"], d1["temporary"]), ("false", "true"))
        self.assertTrue(u2.endswith("/123/feed"))
        self.assertEqual(json.loads(d2["attached_media"]), [{"media_fbid": "PH1"}])
        self.assertEqual((d2["scheduled_publish_time"], d2["unpublished_content_type"]), (at, "SCHEDULED"))

    def test_immediate_post_and_bad_time(self):
        res = facebook.post_photo(self.img, "Bài", None, post=lambda u, **k: resp({"id": "PH", "post_id": "123_1"}))
        self.assertEqual(res, {"id": "123_1", "scheduled": False})
        with self.assertRaises(ValueError):
            facebook.post_photo(self.img, "Bài", int(time.time()) + 60, post=lambda *a, **k: resp({}))


class BotPostTest(DbCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("send_message", "send_video", "send_photo", "send_document", "answer_callback",
                     "clear_buttons"):
            p = mock.patch.object(tg, name, side_effect=lambda *a, _n=name, **k: self.sent.append((_n, a, k)) or 77)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"FACEBOOK_APP_ID": "a", "TIKTOK_CLIENT_KEY": ""}); p.start(); self.addCleanup(p.stop)
        facebook._save({"id": "123", "name": "Kênh", "access_token": "PAGE"})
        self.vid = self.new_video()
        self.img = self.root / "post.jpg"; self.img.write_bytes(b"x")
        self.cfg = json.loads(json.dumps(CFG))
        self.cfg["publish"]["facebook"] = {"enabled": True, "video_state": "PUBLISHED", "utc_offset_hours": 7,
                                           "posts": {"enabled": True, "post_time_local": "11:30"}}

    def msgs(self):
        return [c[1][0] for c in self.sent if c[0] == "send_message"]

    def test_preview_edit_and_publish_once(self):
        with mock.patch.object(fb_post, "draft", return_value="Bài gốc"), \
                mock.patch.object(fb_post, "image", return_value=self.img):
            review.prepare_fb_post(self.con, self.vid, 6, {"title": "t", "summary": "s"}, [{"voice": "v"}], self.cfg, 50)
        v = db.get_video(self.con, self.vid)
        self.assertTrue(v["fb_post"].startswith("Bài gốc"))
        self.assertIn("send_photo", [c[0] for c in self.sent])
        # Du trả lời tin xem trước bằng câu khác -> thành nội dung bài
        review.handle_update(self.con, text("Bài Du viết lại", reply_to=v["fb_post_msg"]), self.cfg)
        self.assertTrue(db.get_video(self.con, self.vid)["fb_post"].startswith("Bài Du viết lại"))
        with mock.patch.object(facebook, "upload_reel", return_value={"video_id": "R", "url": "u", "state": "PUBLISHED",
                                                                      "status": "ready"}), \
                mock.patch.object(facebook, "post_photo", return_value={"id": "123_9", "scheduled": True}) as pp:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), self.cfg)
            review.handle_update(self.con, cb(f"fp:{self.vid}"), self.cfg)          # bấm lại: không đăng đôi
        self.assertEqual(pp.call_count, 1)
        self.assertTrue(pp.call_args.args[1].startswith("Bài Du viết lại"))
        self.assertGreater(pp.call_args.args[2], time.time() + 600)
        self.assertEqual(db.get_video(self.con, self.vid)["fb_post_id"], "123_9")
        self.assertIn("hẹn đăng lúc 11:30", self.msgs()[-1])

    def test_no_post_when_disabled_or_gates_fail(self):
        self.cfg["publish"]["facebook"]["posts"]["enabled"] = False
        with mock.patch.object(fb_post, "draft") as d:
            review.prepare_fb_post(self.con, self.vid, 6, {}, [], self.cfg, 50)
        d.assert_not_called()
        self.cfg["publish"]["facebook"]["posts"]["enabled"] = True
        with mock.patch.object(fb_post, "draft", return_value=""), mock.patch.object(fb_post, "image") as im:
            review.prepare_fb_post(self.con, self.vid, 6, {}, [], self.cfg, 50)
        im.assert_not_called()
        self.assertIn("chỉ đăng Reel", self.msgs()[-1])


class InstagramTest(DbCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("send_message", "answer_callback", "clear_buttons"):
            p = mock.patch.object(tg, name, side_effect=lambda *a, _n=name, **k: self.sent.append((_n, a, k)) or 77)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(instagram.time, "sleep"); p.start(); self.addCleanup(p.stop)
        facebook._save({"id": "123", "name": "Trang", "access_token": "PAGE"},
                       permissions=list(facebook.NEEDED) + list(instagram.NEEDED))
        self.vid = self.new_video()
        (self.root / "output").mkdir(exist_ok=True)

    def test_upload_flow(self):
        video = self.root / "v.mp4"; video.write_bytes(b"\0" * 500)
        posts, polls = [], iter(["IN_PROGRESS", "FINISHED"])

        def get(url, params=None, **kw):
            if url.endswith("/123"):
                return resp({"instagram_business_account": {"id": "IG1", "username": "sujasegye"}})
            if "fields" in (params or {}) and params["fields"].startswith("status_code"):
                return resp({"status_code": next(polls)})
            return resp({"permalink": "https://www.instagram.com/reel/abc/"})

        def post(url, data=None, headers=None, **kw):
            posts.append((url, data if isinstance(data, dict) else None, headers))
            if url.endswith("/IG1/media"):
                return resp({"id": "C1"})
            if "rupload" in url:
                return resp({"success": True})
            return resp({"id": "M1"})
        res = instagram.upload_reel(video, "Chú thích", get=get, post=post)
        self.assertEqual(res, {"id": "M1", "url": "https://www.instagram.com/reel/abc/"})
        create, upload, publish = posts
        self.assertEqual((create[1]["media_type"], create[1]["upload_type"], create[1]["is_ai_generated"]),
                         ("REELS", "resumable", "true"))
        self.assertTrue(upload[0].endswith("/ig-api-upload/v27.0/C1"))
        self.assertEqual((upload[2]["Authorization"], upload[2]["file_size"]), ("OAuth PAGE", "500"))
        self.assertEqual(publish[1]["creation_id"], "C1")

    def test_not_linked_account(self):
        with self.assertRaisesRegex(instagram.InstagramError, "chưa liên kết"):
            instagram.account(get=lambda url, params=None, **kw: resp({}))

    def test_scheduled_by_the_bot_and_posted_once(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["publish"]["instagram"] = {"enabled": True, "publish_time_local": "19:00", "utc_offset_hours": 9}
        db.transition_video(self.con, self.vid, "pending_review", "approved")
        review.schedule_instagram(self.con, db.get_video(self.con, self.vid), cfg)
        due = db.get_video(self.con, self.vid)["instagram_due"]
        self.assertTrue(due)
        with mock.patch.object(instagram, "upload_reel", return_value={"id": "M1", "url": "u"}) as up:
            self.assertEqual(review.publish_instagram_due(self.con, cfg, datetime.now(timezone.utc)), [])   # chưa tới giờ
            later = datetime.fromisoformat(due.replace("Z", "+00:00")) + timedelta(minutes=1)
            self.assertEqual(review.publish_instagram_due(self.con, cfg, later), [self.vid])
            self.assertEqual(review.publish_instagram_due(self.con, cfg, later), [])                        # một lần
        self.assertEqual(up.call_count, 1)
        self.assertEqual(db.get_video(self.con, self.vid)["instagram_id"], "M1")

    def test_not_ready_is_mentioned_once_a_day(self):
        facebook._save({"id": "123", "name": "Trang", "access_token": "PAGE"}, permissions=list(facebook.NEEDED))
        cfg = json.loads(json.dumps(CFG))
        cfg["publish"]["instagram"] = {"enabled": True, "publish_time_local": "19:00", "utc_offset_hours": 9}
        for _ in range(2):
            review.schedule_instagram(self.con, db.get_video(self.con, self.vid), cfg)
        self.assertEqual(sum("instagram_content_publish" in c[1][0] for c in self.sent), 1)
        self.assertIsNone(db.get_video(self.con, self.vid)["instagram_due"])


class FacebookAccessReminderTest(DbCase):
    def test_expiry_is_saved_and_reminded_once_a_day_in_the_last_week(self):
        facebook._save({"id": "123", "name": "Trang", "access_token": "PAGE"})
        expires = int(time.time()) + 5 * 86400

        def get(url, params=None, **kw):
            if url.endswith("/oauth/access_token"):
                return resp({"access_token": "APP"})
            return resp({"data": {"type": "PAGE", "expires_at": 0, "data_access_expires_at": expires}})
        with mock.patch.dict(os.environ, {"FACEBOOK_APP_ID": "a", "FACEBOOK_APP_SECRET": "s"}):
            facebook.remember_data_access_expiry(get)
        self.assertAlmostEqual(facebook.data_access_days_left(), 5, delta=0.1)
        sent = []
        with mock.patch.object(tg, "send_message", side_effect=lambda t, **k: sent.append(t) or 1):
            self.assertTrue(review.remind_facebook_access(self.con))
            self.assertFalse(review.remind_facebook_access(self.con))          # cùng ngày: không nhắc lại
            later = datetime.now(timezone.utc) - timedelta(days=30)            # còn 35 ngày: chưa nhắc
            self.assertFalse(review.remind_facebook_access(self.con, later))
        self.assertIn("/facebook", sent[0])


class InstagramAgentTest(DbCase):
    def setUp(self):
        super().setUp()
        from src.analysis import learned
        self.learned = learned

    def test_weekly_measure_and_learn(self):
        from src import ig_insights, learning
        facebook._save({"id": "123", "name": "Trang", "access_token": "PAGE"},
                       permissions=list(facebook.NEEDED) + list(instagram.NEEDED) + ["instagram_manage_insights"])
        cfg = {"publish": {"instagram": {"enabled": True}}}
        now = datetime.now(timezone.utc)
        for k in range(101, 105):                             # 4 Reel đã đăng 5 ngày trước
            self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,source_name) VALUES (?,?,?,?,?)",
                             (k, f"세계 지도: x{k}", f"x{k}", f"u{k}", "World Bank Open Data"))
            self.con.execute("INSERT INTO scripts (id,idea_id,body,status) VALUES (?,?,?,'verified')",
                             (k, k, "- voice: 한국 23위입니다\n"))
            self.con.execute("INSERT INTO videos (id,script_id,file,title,status,instagram_id,instagram_due)"
                             " VALUES (?,?,?,?,'published',?,?)",
                             (k, k, "f", f"V{k}", f"IG{k}", (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")))
        self.con.commit()
        views = {"IG101": 300, "IG102": 400, "IG103": 350, "IG104": 9000}

        def get(url, params=None, **kw):
            if url.endswith("/123"):
                return resp({"instagram_business_account": {"id": "U1", "username": "sujasegye"}})
            if url.endswith("/U1"):
                return resp({"followers_count": 210, "media_count": 4, "username": "sujasegye"})
            mid = url.rsplit("/", 2)[-2]
            return resp({"data": [{"name": "views", "values": [{"value": views[mid]}]},
                                  {"name": "reels_skip_rate", "values": [{"value": 40.0}]},
                                  {"name": "ig_reels_avg_watch_time", "values": [{"value": 15000}]},
                                  {"name": "total_interactions", "values": [{"value": 12}]}]})
        with mock.patch("src.fb_insights._duration", return_value=30.0):
            text = "\n".join(ig_insights.update(self.con, cfg, now, get=get))
        self.assertIn("@sujasegye: 210 người theo dõi", text)
        self.assertIn("#104 “V104”: 9.000 lượt xem", text)
        self.assertIn("Lướt qua trong 3 giây đầu: trung bình 40,0%", text)
        self.assertIn("🚀 Đột biến: #104", text)
        prefs = learning.preferences("ig_preferences")
        self.assertEqual(prefs["metric"], "engaged_pct")          # 100 - tỷ lệ lướt qua 3 giây đầu
        self.assertEqual(ig_insights.watch_seconds(15000, 30.0), 15.0)  # mili giây đoán ra từ độ dài video

    def test_off_or_not_ready(self):
        from src import ig_insights
        self.assertEqual(ig_insights.update(self.con, {"publish": {}}), [])
        self.assertEqual(ig_insights.update(self.con, {"publish": {"instagram": {"enabled": True}}}), [])


if __name__ == "__main__":
    unittest.main()
