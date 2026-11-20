"""Test agent Facebook (src/fb_insights.py), bình luận Facebook trong agent Cộng đồng và các hàm đọc của
src/publish/facebook.py — không gọi mạng, không gọi LLM.

    python -m unittest tests.test_fb_agents -v
"""
import json
import types
from collections import Counter
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import community, db, fb_insights, learning
from src.analysis import learned
from src.publish import facebook
from tests.test_channel_agents import CFG, Case

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
ALL_PERMS = list(facebook.NEEDED) + list(facebook.OPTIONAL)


def resp(body):
    return types.SimpleNamespace(status_code=200, text=json.dumps(body), json=lambda: body)


class FbCase(Case):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(facebook, "TOKEN_PATH", self.root / "fb.json"); p.start(); self.addCleanup(p.stop)

    def connect(self, perms=ALL_PERMS):
        facebook._save({"id": "123", "name": "Kênh", "access_token": "PAGE"}, permissions=perms)

    def reel(self, vid, days_ago=7, slot="19:00", title="Tuổi thọ trung bình: Việt Nam và Hàn Quốc"):
        self.published(vid, f"https://data.worldbank.org/indicator/SP.DYN.LE00.IN?locations=VN-KR&end={2000 + vid}",
                       title=title, summary="Tuổi thọ Việt Nam 74,6 năm; Hàn Quốc 83,5 năm.")
        db.update_video(self.con, vid, facebook_id=f"fb{vid}", facebook_slot=slot,
                        facebook_at=(NOW - timedelta(days=days_ago)).isoformat(timespec="seconds"))

    def stats(self, vid, plays, age=7.0, avg=20.0, dur=40.0, slot=None, followers=1):
        self.con.execute("INSERT OR REPLACE INTO fb_stats (video_id, facebook_id, fetched_at, age_days, duration_s,"
                         " plays, avg_watch_s, followers) VALUES (?,?,?,?,?,?,?,?)",
                         (vid, f"fb{vid}", NOW.isoformat(), age, dur, plays, avg, followers))
        if slot:
            db.update_video(self.con, vid, facebook_slot=slot)
        self.con.commit()


class ApiTest(FbCase):
    def test_connect_records_permissions_and_names_the_missing_optional_ones(self):
        def get(url, params=None, **kw):
            if url.endswith("/oauth/access_token"):
                return resp({"access_token": "LONG"})
            if url.endswith("/me/permissions"):
                return resp({"data": [{"permission": p, "status": "granted"} for p in facebook.NEEDED + ("read_insights",)]})
            return resp({"data": [{"id": "123", "name": "Kênh", "access_token": "PAGE", "tasks": ["CREATE_CONTENT"]}]})
        with mock.patch.dict("os.environ", {"FACEBOOK_APP_ID": "a", "FACEBOOK_APP_SECRET": "s"}), \
                mock.patch.object(facebook.requests, "get", side_effect=get):
            who = facebook.connect("x" * 40)
        self.assertEqual(who["missing_optional"], ["pages_read_user_content", "pages_manage_engagement"])
        self.assertTrue(facebook.can("read_insights"))
        self.assertFalse(facebook.can("pages_manage_engagement"))

    def test_reel_insights_and_page_insights_are_parsed(self):
        self.connect()
        reel = {"data": [{"name": "blue_reels_play_count", "values": [{"value": 1234}]},
                         {"name": "post_video_avg_time_watched", "values": [{"value": 18500}]},
                         {"name": "post_video_likes_by_reaction_type", "values": [{"value": {"LIKE": 30, "LOVE": 5}}]},
                         {"name": "post_video_retention_graph", "values": [{"value": {"0": 1.0, "10": 0.42}}]}]}
        m = facebook.reel_insights("fb1", get=lambda url, params=None, **kw: resp(reel))
        row = fb_insights.parse(m)
        self.assertEqual((row["plays"], row["avg_watch_s"], row["reactions"], row["hold_quarter"]),
                         (1234, 18.5, 35, 42.0))

        def get(url, params=None, **kw):
            if url.endswith("/insights"):
                if params["metric"] == "page_media_view":
                    return resp({"data": [{"values": [{"value": 5000}]}]})
                raise facebook.FacebookUploadError("Trang dưới 100 lượt thích")      # chỉ số khác chưa có
            return resp({"followers_count": 87, "name": "Kênh"})
        page = facebook.page_insights(get=get)
        self.assertEqual((page["followers"], page["page_media_view"]), (87, 5000))
        self.assertNotIn("page_video_views", page)

    def test_comments_paging_and_reply(self):
        self.connect()
        body = {"data": [{"id": "1_2", "message": "hay"}], "paging": {"cursors": {"after": "C"}, "next": "u"}}
        got = facebook.comments("fb1", get=lambda url, params=None, **kw: resp(body))
        self.assertEqual(got["next"], "C")
        sent = {}
        posted = facebook.reply_comment("1_2", "Cảm ơn bạn", post=lambda url, data=None, **kw: (
            sent.update(url=url, data=data), resp({"id": "1_9"}))[1])
        self.assertEqual(posted, "1_9")
        self.assertTrue(sent["url"].endswith("/1_2/comments"))
        self.assertEqual(sent["data"]["message"], "Cảm ơn bạn")


class AgentTest(FbCase):
    def test_not_connected_does_nothing(self):
        self.assertEqual(fb_insights.update(self.con, CFG, NOW), [])

    def test_weekly_run_measures_learns_and_reports(self):
        self.connect()
        for k, plays in enumerate([400, 500, 450, 6000], 1):
            self.reel(k, days_ago=7, slot=("12:00" if k % 2 else "21:00"))
        self.reel(9, days_ago=-1)                                           # còn hẹn giờ: chưa đo
        metrics = {f"fb{k}": {"blue_reels_play_count": p, "post_video_avg_time_watched": 15000 + k * 1000,
                              "post_video_followers": k} for k, p in enumerate([400, 500, 450, 6000], 1)}
        page = {"followers": 120, "page_media_view": 9000, "page_daily_follows_unique": 30}
        with mock.patch.object(facebook, "reel_insights", side_effect=lambda fid, get=None: metrics[fid]) as ri, \
                mock.patch.object(facebook, "page_insights", return_value=page), \
                mock.patch.object(fb_insights, "_duration", return_value=40.0):
            fb_insights.update(self.con, CFG, NOW - timedelta(days=7))      # tuần trước: chỉ để có lịch sử
            page["followers"] = 150
            text = "\n".join(fb_insights.update(self.con, CFG, NOW))
        self.assertNotIn(("fb9",), [c.args[:1] for c in ri.call_args_list])
        self.assertIn("Trang: 150 người theo dõi (+30 so với tuần trước)", text)
        self.assertIn("9.000 lượt xem nội dung", text)
        self.assertIn("30 ngày qua đăng 4/15 Reels", text)
        self.assertIn("#4", text.split("Kiếm tiền")[1].splitlines()[1])      # Reel nhiều lượt nhất đứng đầu
        self.assertIn("Giờ đăng đang thử (giờ VN): 12:00: 2 Reel", text)
        self.assertIn("🚀 Đột biến: #4", text)
        prefs = learning.preferences("fb_preferences")
        self.assertEqual((prefs["based_on"], prefs["metric"]), (4, "avg_view_pct+sub"))
        self.assertEqual(learning.preferences(), {})                       # sở thích YouTube không bị ghi đè
        self.assertEqual(learned.load_learned()["facebook"]["latest"]["cm"], [4, 1])

    def test_missing_insights_permission_is_reported_not_fatal(self):
        self.connect(perms=list(facebook.NEEDED))
        with mock.patch.object(facebook, "page_insights", return_value={"followers": 5}), \
                mock.patch.object(facebook, "reel_insights") as ri:
            text = "\n".join(fb_insights.update(self.con, CFG, NOW))
        ri.assert_not_called()
        self.assertIn("Chưa có quyền read_insights", text)

    def test_monetization_cadence_counts_vietnam_days(self):
        for k, hours in enumerate([1, 2, 30, 24 * 31], 1):
            self.published(k, f"u{k}")
            db.update_video(self.con, k, facebook_id=f"fb{k}",
                            facebook_at=(NOW - timedelta(hours=hours)).isoformat(timespec="seconds"))
        self.assertEqual(fb_insights.cm_progress(self.con, NOW), (3, 2))   # Reel 31 ngày trước không tính

    def test_slot_choice_is_stable_and_follows_the_data(self):
        fcfg = {"publish_time_local": "19:00", "slots": ["12:00", "19:00", "21:00"]}
        self.assertEqual(fb_insights.choose_slot(self.con, {"publish_time_local": "20:00"}, 1), "20:00")
        self.assertEqual(fb_insights.choose_slot(self.con, fcfg, 7), fb_insights.choose_slot(self.con, fcfg, 7))
        k = 0

        def add(slot, per_day, n):
            nonlocal k
            for _ in range(n):
                k += 1
                self.reel(k, slot=slot)
                self.stats(k, per_day * 7, age=7.0)
        for slot, per_day in (("12:00", 120), ("19:00", 100), ("21:00", 90)):
            add(slot, per_day, 2)                    # ít dữ liệu, chênh nhỏ: khung nào cũng còn được thử
        picks = Counter(fb_insights.choose_slot(self.con, fcfg, seed) for seed in range(60))
        self.assertTrue(all(picks[s] > 0 for s in fcfg["slots"]), picks)
        add("12:00", 3000, 6)                         # khung 12:00 hơn hẳn và chắc chắn: gần như luôn chọn
        picks = Counter(fb_insights.choose_slot(self.con, fcfg, seed) for seed in range(60))
        self.assertGreater(picks["12:00"], 50)

    def test_status_text(self):
        self.assertIn("chưa đo lần nào", fb_insights.status_text(self.con))


class FbCommentTest(FbCase):
    def llm(self, role, goal, description, expected_output, models=None):
        if "Phân loại" in description:
            return json.dumps([{"i": 1, "kind": "cau_hoi"}, {"i": 2, "kind": "khen"}])
        return "Tuổi thọ Hàn Quốc là 83,5 năm nhé."

    def test_facebook_comments_become_cards_and_replies_go_to_facebook(self):
        self.connect(perms=list(facebook.NEEDED))
        self.reel(1, days_ago=3)
        pages = {"fb1": {"data": [{"id": "fb1_c2", "message": "Hàn Quốc bao nhiêu năm vậy?", "from": {"name": "An"}},
                                  {"id": "fb1_c1", "message": "Hay quá"}], "next": None}}
        sent = []
        with mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}):
            got = community.run(CFG, self.con, llm=self.llm, fb_fetch=lambda fid, after: pages[fid],
                                send=lambda t, buttons=None, **k: sent.append((t, buttons)) or 500 + len(sent))
        self.assertEqual(len(got), 2)
        digest, card = sent[0][0], sent[1][0]
        self.assertIn("pages_manage_engagement", digest)                   # thiếu quyền trả lời: nói rõ
        self.assertIn("📘 Facebook https://www.facebook.com/reel/fb1", card)
        self.assertIn("83,5", card)
        row = self.con.execute("SELECT platform, link, status FROM comments WHERE id='fb1_c2'").fetchone()
        self.assertEqual(tuple(row), ("facebook", "https://www.facebook.com/reel/fb1", "new"))
        with mock.patch.object(facebook, "reply_comment", return_value="fb1_r") as rc:
            self.assertEqual(community.post_reply(self.con, "fb1_c2"), "fb1_r")
        self.assertEqual(rc.call_args.args[0], "fb1_c2")
        # lượt sau: bình luận đã lưu thì dừng, không phân loại lại
        with mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}):
            self.assertEqual(community.run(CFG, self.con, llm=self.llm, fb_fetch=lambda fid, after: pages[fid],
                                           send=lambda *a, **k: 1), [])
