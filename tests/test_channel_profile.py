"""Hồ sơ kênh (src/channel_profile.py), danh sách phát (src/publish/playlists.py), sao lưu (src/backup.py) — không
gọi mạng thật: mọi lệnh HTTP đi qua hàm giả."""
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml

from src import backup, channel_profile as cp, db, lang
from src import telegram_bot as tg
from src.publish import facebook, playlists
from tests.test_phase4 import DbCase

ROOT = Path(__file__).resolve().parent.parent
VI = yaml.safe_load((ROOT / "config" / "channel.yaml").read_text(encoding="utf-8"))
KO = yaml.safe_load((ROOT / "config" / "channel_ko.yaml").read_text(encoding="utf-8"))


class Resp:
    def __init__(self, body=None, status=200):
        self.status_code, self._body = status, body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class YouTubeProfileTest(DbCase):
    CH = {"id": "UC1", "snippet": {"title": "K", "customUrl": "@숫자세계"},
          "brandingSettings": {"channel": {"title": "K", "country": "KR"}}}

    def test_plan_quotes_multiword_keywords_and_adds_contact_only_when_set(self):
        plan = cp.youtube_plan(VI)
        self.assertIn('"số liệu"', plan["keywords"])
        self.assertIn(" infographic", plan["keywords"])
        self.assertEqual((plan["defaultLanguage"], plan["country"]), ("vi", "KR"))
        self.assertNotIn("📩", plan["description"])
        cfg = json.loads(json.dumps(VI)); cfg["profile"]["contact_email"] = "kenh@example.com"
        self.assertTrue(cp.youtube_plan(cfg)["description"].endswith("📩 Liên hệ hợp tác: kenh@example.com"))

    def test_apply_keeps_existing_fields_uploads_banner_once(self):
        sent = {}
        get = lambda url, **kw: Resp({"items": [self.CH]})
        post = lambda url, **kw: (sent.setdefault("banner", url), Resp({"url": "https://yt3/banner"}))[1]
        put = lambda url, **kw: (sent.setdefault("body", kw["json"]), Resp({}))[1]
        dry = cp.apply_youtube(self.con, VI, apply=False, token="T", get=get, post=post, put=put)
        self.assertIn("YouTube: ảnh bìa", dry)
        self.assertNotIn("body", sent)                                       # xem trước: không gửi gì
        cp.apply_youtube(self.con, VI, apply=True, token="T", get=get, post=post, put=put)
        ch = sent["body"]["brandingSettings"]["channel"]
        self.assertEqual(ch["title"], "K")                                    # giữ trường đang có
        self.assertEqual(ch["defaultLanguage"], "vi")
        self.assertEqual(sent["body"]["brandingSettings"]["image"]["bannerExternalUrl"], "https://yt3/banner")
        # lần sau: ảnh bìa đã có + cùng file -> không tải lại
        self.CH = json.loads(json.dumps(self.CH))
        self.CH["brandingSettings"].update(channel={**ch}, image={"bannerExternalUrl": "https://yt3/banner"})
        get2 = lambda url, **kw: Resp({"items": [self.CH]})
        self.assertEqual(cp.apply_youtube(self.con, VI, apply=False, token="T", get=get2), [])

    def test_channel_url_encodes_korean_handle(self):
        self.assertEqual(cp.channel_url(self.CH), "https://www.youtube.com/@%EC%88%AB%EC%9E%90%EC%84%B8%EA%B3%84")


class FacebookProfileTest(DbCase):
    def test_about_website_and_cover(self):
        facebook._save({"id": "123", "name": "Trang", "access_token": "PAGE"},
                       permissions=["pages_manage_metadata"])
        calls = []

        def get(url, params=None, **kw):
            return Resp({"id": "123"})                                       # chưa có giới thiệu, chưa có ảnh bìa

        def post(url, data=None, files=None, **kw):
            calls.append((url.rsplit("/", 1)[-1], dict(data or {})))
            return Resp({"id": "PHOTO9"} if url.endswith("/photos") else {"success": True})
        changes = cp.apply_facebook(self.con, VI, "https://www.youtube.com/@thegioiquaconso", apply=True,
                                    get=get, post=post)
        self.assertIn("Facebook: ảnh bìa", changes)
        self.assertEqual(calls[0][0], "photos")
        self.assertEqual(calls[0][1]["published"], "false")                  # ảnh bìa không lên dòng thời gian
        page = calls[1][1]
        self.assertEqual(page["about"], VI["profile"]["facebook_about"])
        self.assertEqual(page["website"], "https://www.youtube.com/@thegioiquaconso")
        self.assertEqual((page["cover"], page["no_feed_story"]), ("PHOTO9", "true"))

    def test_not_connected_does_nothing(self):
        self.assertEqual(cp.apply_facebook(self.con, VI, None, apply=True), [])


class KitTest(DbCase):
    def test_vietnamese_kit(self):
        with lang.using("vi"):
            text = cp.kit_text(VI, "https://www.youtube.com/@thegioiquaconso", "https://www.facebook.com/1472",
                               None, {"madeForKids": False, "longUploadsStatus": "allowed"})
        self.assertIn(VI["profile"]["tiktok_bio"], text)
        self.assertIn("@thegioiquaconso", text)                              # gợi ý tên người dùng cho Trang
        self.assertIn("Gmail riêng", text)
        self.assertNotIn("trẻ em", text)                                     # kênh Việt đã đặt

    def test_korean_kit(self):
        with lang.using("ko"):
            text = cp.kit_text(KO, "https://www.youtube.com/@x", "https://www.facebook.com/1419", "sujaworld_du",
                               {"longUploadsStatus": "eligible"})
        self.assertIn("instagram.com/sujaworld_du", text)
        self.assertIn("숫자세계 | 데이터로 보는 세계", text)
        self.assertIn("không dành cho trẻ em", text)
        self.assertNotIn("TikTok", text)
        self.assertNotIn("tên người dùng", text)                             # Trang kênh Hàn chỉ để liên kết
        # ca thật 21/11: chỉ có Shorts -> không đòi xác minh số điện thoại (số của Du đã dùng đủ 2 kênh/năm)
        self.assertNotIn("số điện thoại", text)
        with lang.using("ko"):
            text = cp.kit_text(KO, None, None, None, {"longUploadsStatus": "eligible"}, long_videos=True)
        self.assertIn("số điện thoại", text)


class PlaylistTest(DbCase):
    def setUp(self):
        super().setUp()
        self.con.execute("UPDATE ideas SET title='Bản đồ thế giới: điện', source_name='World Bank Open Data'")
        self.con.commit()
        self.vid = self.new_video()
        db.update_video(self.con, self.vid, youtube_id="abc123")
        self.cfg = {"publish": {"youtube": {"playlists": VI["publish"]["youtube"]["playlists"]}}}

    def http(self, existing=()):
        calls = []

        class H:
            @staticmethod
            def get(url, params=None, **kw):
                calls.append(("get", url, params))
                return Resp({"items": [{"id": i, "snippet": {"title": t}} for i, t in existing]})

            @staticmethod
            def post(url, params=None, json=None, **kw):
                calls.append(("post", url, json))
                return Resp({"id": "PLnew"} if url.endswith("/playlists") else {"id": "item"})
        return H, calls

    def test_kind_and_creation_and_no_duplicates(self):
        with mock.patch("src.learning.video_kind", return_value="ban-do"):
            self.assertEqual(playlists.kind_of(self.con, db.get_video(self.con, self.vid)), "ban-do")
            h, calls = self.http()
            pid = playlists.add(self.con, db.get_video(self.con, self.vid), self.cfg, "T", h)
            self.assertEqual(pid, "PLnew")
            made = [c for c in calls if c[0] == "post" and c[1].endswith("/playlists")][0][2]
            self.assertEqual(made["status"]["privacyStatus"], "public")
            self.assertTrue(made["snippet"]["title"].startswith("Việt Nam đứng thứ mấy"))
            item = [c for c in calls if c[1].endswith("/playlistItems")][0][2]["snippet"]
            self.assertEqual((item["playlistId"], item["position"], item["resourceId"]["videoId"]), ("PLnew", 0, "abc123"))
            n = len(calls)
            playlists.add(self.con, db.get_video(self.con, self.vid), self.cfg, "T", h)   # lần hai: không gọi gì
            self.assertEqual(len(calls), n)
            self.assertEqual(playlists.pending(self.con), [])

    def test_reuses_playlist_with_same_title(self):
        title = self.cfg["publish"]["youtube"]["playlists"]["bieu-do"]["title"]
        with mock.patch("src.learning.video_kind", return_value="bieu-do"):
            h, calls = self.http(existing=[("PLold", title)])
            self.assertEqual(playlists.add(self.con, db.get_video(self.con, self.vid), self.cfg, "T", h), "PLold")
        self.assertFalse([c for c in calls if c[1].endswith("/playlists") and c[0] == "post"])

    def test_long_video_and_disabled(self):
        long_id = db.upsert_video(self.con, None, "output/long.mp4", "Tuần", "D", [], [])
        self.assertEqual(playlists.kind_of(self.con, db.get_video(self.con, long_id)), playlists.LONG)
        self.assertIsNone(playlists.add(self.con, db.get_video(self.con, self.vid), {"publish": {}}, "T"))
        self.assertEqual(playlists.backfill(self.con, {"publish": {}}), 0)


class BackupTest(DbCase):
    def test_snapshot_rotates_and_weekly_bundle_is_sent(self):
        for day in range(1, 18):
            backup.snapshot(datetime(2026, 11, day, tzinfo=timezone.utc))
        snaps = sorted(backup.backup_dir().glob("pipeline-*.db"))
        self.assertEqual(len(snaps), backup.KEEP)
        self.assertEqual(snaps[-1].name, "pipeline-20261117.db")
        con = sqlite3.connect(snaps[-1])
        self.assertEqual(con.execute("SELECT count(*) FROM scripts").fetchone()[0], 1)    # bản chụp đọc được
        con.close()
        from src.analysis import learned
        Path(learned.LEARNED_PATH).write_text("x: 1\n", encoding="utf-8")
        with mock.patch.object(tg, "send_document", return_value=1) as send:
            self.assertTrue(backup.send_weekly(datetime(2026, 11, 22, tzinfo=timezone.utc)))
        path = send.call_args[0][0]
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()), ["learned.yaml", "pipeline.db"])
        self.assertNotIn(".secrets", str(path))


class LongThumbTest(DbCase):
    """Hình thu nhỏ video dài hằng tuần (src/longform.py + render-web/src/Thumb.tsx)."""

    def test_cards_prefer_richest_scenes_and_strip_captions(self):
        from src import longform
        stories = [{"duration": 30, "words": [{"w": "x"}], "scenes": [{"kind": k, "start": 0, "end": 10}]}
                   for k in ("big_number", "map", "statement", "bar_race", "line_solo")]
        seen = {}

        def run(cmd, **kw):
            seen["props"] = json.loads(Path(cmd[[i for i, c in enumerate(cmd) if c.startswith("--props=")][0]]
                                            .split("=", 1)[1]).read_text(encoding="utf-8"))
        out = self.root / "w.thumb.jpg"
        with mock.patch("src.longform.subprocess.run", side_effect=run), lang.using("vi"):
            self.assertEqual(longform.thumbnail(stories, 5, "15/11–21/11", out), out)
        p = seen["props"]
        kinds = [c["story"]["scenes"][0]["kind"] for c in p["cards"]]
        self.assertEqual(kinds, ["map", "bar_race", "line_solo"])            # giàu hình nhất trước, tối đa 3
        self.assertTrue(all(c["story"]["words"] == [] for c in p["cards"]))   # không phụ đề
        self.assertEqual((p["count"], p["span"], p["series"]), (5, "15/11–21/11", "TUẦN QUA CON SỐ"))
        self.assertFalse(out.with_suffix(".props.json").exists())

    def test_backfill_reads_count_and_span_from_title(self):
        from src import longform
        v = {"title": "7 câu chuyện qua con số tuần 15/11–21/11 | Việt Nam, Hàn Quốc và thế giới",
             "created_at": "2026-11-21T01:00:00+00:00", "file": "output/weekly_2026-11-21.mp4"}
        with mock.patch.object(longform, "week_videos", return_value=[]), \
                mock.patch.object(longform, "thumbnail", return_value="T") as th:
            longform.thumbnail_for(v)
        self.assertEqual(th.call_args[0][1:3], (7, "15/11–21/11"))
        # Shorts đăng SAU video dài không được vào hình của tuần đó
        week = [{"script_id": 1, "published_at": "2026-11-20T10:00:00+00:00"},
                {"script_id": 2, "published_at": "2026-11-22T10:00:00+00:00"}]
        with mock.patch.object(longform, "week_videos", return_value=week), \
                mock.patch.object(longform, "RENDER", self.root), \
                mock.patch.object(longform, "thumbnail", return_value="T") as th:
            for sid in (1, 2):
                (self.root / f"web_{sid}.props.json").write_text(json.dumps({"id": sid}), encoding="utf-8")
            longform.thumbnail_for(v)
        self.assertEqual(th.call_args[0][0], [{"id": 1}])
        v["title"] = "숫자로 본 이번 주 이야기 7편 (11.15–11.21) | 한국과 세계"
        with mock.patch.object(longform, "week_videos", return_value=[]), \
                mock.patch.object(longform, "thumbnail", return_value="T") as th:
            longform.thumbnail_for(v)
        self.assertEqual(th.call_args[0][1:3], (7, "11.15–11.21"))

    def test_long_video_upload_attaches_thumbnail(self):
        from src import review
        from src.publish import youtube
        long_id = db.upsert_video(self.con, None, "output/weekly_x.mp4", "Tuần", "D", [], [])
        db.transition_video(self.con, long_id, "pending_review", "approved")
        (self.root / "output").mkdir()
        (self.root / "output" / "weekly_x.thumb.jpg").write_bytes(b"jpg")
        res = {"id": "LONG1", "url": "u", "privacy": "private", "requested_privacy": "private", "publish_at": None}
        cfg = {"publish": {"youtube": {"mode": "api"}}}
        with mock.patch.object(review, "ROOT", self.root), mock.patch.object(youtube, "upload", return_value=res), \
                mock.patch.object(youtube, "can_set_thumbnails", return_value=True), \
                mock.patch.object(youtube, "set_thumbnail") as st, \
                mock.patch.object(tg, "send_message", return_value=1) as sm:
            review._publish_api(self.con, db.get_video(self.con, long_id), cfg)
        st.assert_called_once_with("LONG1", self.root / "output" / "weekly_x.thumb.jpg")
        self.assertIn("hình thu nhỏ", sm.call_args[0][0])

    def test_unverified_channel_skips_thumbnail_and_says_why(self):
        """Kênh Hàn chưa xác minh số điện thoại (số của Du đã dùng đủ 2 kênh/năm): không thử gắn, báo cách gắn sau."""
        from src import review
        from src.publish import youtube
        long_id = db.upsert_video(self.con, None, "output/weekly_y.mp4", "Tuần", "D", [], [])
        db.transition_video(self.con, long_id, "pending_review", "approved")
        (self.root / "output").mkdir()
        (self.root / "output" / "weekly_y.thumb.jpg").write_bytes(b"jpg")
        res = {"id": "LONG2", "url": "u", "privacy": "private", "requested_privacy": "private", "publish_at": None}
        with mock.patch.object(review, "ROOT", self.root), mock.patch.object(youtube, "upload", return_value=res), \
                mock.patch.object(youtube, "can_set_thumbnails", return_value=False), \
                mock.patch.object(youtube, "set_thumbnail") as st, \
                mock.patch.object(tg, "send_message", return_value=1) as sm:
            review._publish_api(self.con, db.get_video(self.con, long_id), {"publish": {"youtube": {"mode": "api"}}})
        st.assert_not_called()
        self.assertIn("xác minh số điện thoại", sm.call_args[0][0])
        self.assertIn(f"--thumb {long_id} --upload", sm.call_args[0][0])

    def test_can_set_thumbnails_reads_channel_status(self):
        from src.publish import youtube
        with mock.patch.object(youtube, "access_token", return_value="T"):
            for status, want in (({"longUploadsStatus": "allowed"}, True), ({"longUploadsStatus": "eligible"}, False),
                                 ({}, None)):
                get = lambda url, **kw: Resp({"items": [{"status": status}]})
                self.assertIs(youtube.can_set_thumbnails(get), want)


class InstagramIntroTest(DbCase):
    def test_posts_once_and_only_when_applied(self):
        posted = []
        fake = lambda image, text: (posted.append((image.name, text)), {"id": "IG1", "url": "https://ig/p/1"})[1]
        with lang.using("ko"), mock.patch.object(cp, "asset", return_value=self.root / "instagram_intro.jpg"):
            (self.root / "instagram_intro.jpg").write_bytes(b"jpg")
            self.assertEqual(cp.instagram_intro(self.con, KO, apply=False, post_image=fake),
                             ["Instagram: bài giới thiệu"])
            self.assertEqual(posted, [])                                     # xem trước: không đăng
            cp.instagram_intro(self.con, KO, apply=True, post_image=fake)
            self.assertEqual(cp.instagram_intro(self.con, KO, apply=True, post_image=fake), [])   # chỉ một lần
        self.assertEqual(len(posted), 1)
        self.assertIn("숫자세계에 오신 것을 환영합니다", posted[0][1])
        self.assertIn("AI", posted[0][1])

    def test_vietnamese_channel_has_no_intro(self):
        self.assertEqual(cp.instagram_intro(self.con, VI, apply=True, post_image=lambda *a: 1 / 0), [])

    def test_post_image_hosts_on_facebook_cdn_then_publishes(self):
        from src.publish import instagram
        facebook._save({"id": "PAGE1", "name": "Trang", "access_token": "PAGE"},
                       permissions=list(instagram.NEEDED))
        img = self.root / "a.jpg"
        img.write_bytes(b"jpg")
        calls = []

        def get(url, params=None, **kw):
            calls.append(("get", url.rsplit("/", 1)[-1], params))
            if url.endswith("/PAGE1"):
                return Resp({"instagram_business_account": {"id": "IGU", "username": "sujaworld_du"}})
            if url.endswith("/PH1"):
                return Resp({"images": [{"width": 640, "source": "https://cdn/small"},
                                        {"width": 1080, "source": "https://cdn/big"}]})
            if url.endswith("/C1"):
                return Resp({"status_code": "FINISHED"})
            return Resp({"permalink": "https://www.instagram.com/p/X/"})

        def post(url, data=None, files=None, **kw):
            calls.append(("post", url.rsplit("/", 1)[-1], dict(data or {})))
            if url.endswith("/photos"):
                return Resp({"id": "PH1"})
            if url.endswith("/media"):
                return Resp({"id": "C1"})
            return Resp({"id": "M1"})
        res = instagram.post_image(img, "chào", get=get, post=post)
        self.assertEqual(res, {"id": "M1", "url": "https://www.instagram.com/p/X/"})
        photo = [c for c in calls if c[1] == "photos"][0][2]
        self.assertEqual((photo["published"], photo["temporary"]), ("false", "true"))   # ảnh tạm, không lên Trang
        media = [c for c in calls if c[1] == "media"][0][2]
        self.assertEqual(media["image_url"], "https://cdn/big")                      # bản lớn nhất
