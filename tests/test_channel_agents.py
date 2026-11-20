"""Test agent Cộng đồng, agent Tăng trưởng và hàng đợi chủ đề (src/community.py, src/growth.py,
src/topics.py) — không gọi mạng, không gọi LLM.

    python -m unittest tests.test_channel_agents -v
"""
import json
import logging
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

from src import community, db, growth, learning, review, topics
from src import telegram_bot as tg
from src.analysis import learned
from src.sources import datatable as dt
from src.sources import worldbank

OWNER = "12345"
CFG = {"channel": {"name": "Thế giới qua con số"},
       "sources": {"worldbank": {
           "indicators": [{"code": "SL.UEM.TOTL.ZS", "name": "Tỷ lệ thất nghiệp"},
                          {"code": "SL.AGR.EMPL.ZS", "name": "Tỷ lệ lao động làm nông nghiệp"},
                          {"code": "NY.GDP.PCAP.CD", "name": "GDP bình quân đầu người"}],
           "races": {"indicators": [{"code": "NY.GDP.PCAP.CD", "name": "GDP bình quân đầu người"}]},
           "world": {"indicators": ["NY.GDP.PCAP.CD"]}},
           "owid": {"charts": [{"slug": "coffee-production", "name": "Sản lượng cà phê"}]}}}


class Case(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, attr, val in [(db, "DB_PATH", self.root / "t.db"),
                                  (learned, "LEARNED_PATH", self.root / "learned.yaml")]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)

    def published(self, vid, url, title="Video", yt=None, source=dt.WB_SOURCE, body=None, summary=""):
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,source_name,summary) VALUES (?,?,?,?,?,?)",
                         (vid, title, f"t{vid}", url, source, summary))
        self.con.execute("INSERT INTO scripts (id,idea_id,body,status) VALUES (?,?,?,'verified')",
                         (vid, vid, body or yaml.safe_dump([{"voice": "Hàn Quốc gấp 5 lần Việt Nam."}],
                                                           allow_unicode=True)))
        self.con.execute("INSERT INTO videos (id,script_id,file,title,status,youtube_id,published_at)"
                         " VALUES (?,?,'f',?,'published',?,?)",
                         (vid, vid, title, yt or f"yt{vid:09d}", datetime.now(timezone.utc).isoformat()))
        self.con.commit()


class TopicsTest(Case):
    def test_catalog_and_keyword_match(self):
        self.assertEqual(topics.catalog(CFG)["owid:coffee-production"], "Sản lượng cà phê")
        self.assertEqual(len(topics.catalog(CFG)), 4)                  # GDP có ở hai danh sách: một khoá
        self.assertEqual(topics.match(CFG, "Thất nghiệp"), ["wb:SL.UEM.TOTL.ZS"])
        self.assertEqual(topics.match(CFG, "làm về cà phê đi"), ["owid:coffee-production"])
        self.assertEqual(topics.match(CFG, "lương"), [])                # chưa có nguồn
        self.assertEqual(set(topics.match(CFG, "nông nghiệp thất nghiệp")), {"wb:SL.AGR.EMPL.ZS", "wb:SL.UEM.TOTL.ZS"})
        self.assertEqual(topics.key_of_url("https://data.worldbank.org/indicator/SP.DYN.LE00.IN?locations=VN-KR"),
                         "wb:SP.DYN.LE00.IN")
        self.assertEqual(topics.key_of_url("https://ourworldindata.org/grapher/coffee-production?tab=map"),
                         "owid:coffee-production")
        self.assertIsNone(topics.key_of_url("https://www.sciencedaily.com/x"))

    def test_requests_jump_the_rotation_once(self):
        self.assertEqual(topics.request(self.con, "wb:SL.UEM.TOTL.ZS", "thất nghiệp", "du"), "pending")
        self.assertEqual(topics.request(self.con, "wb:SL.UEM.TOTL.ZS", "thất nghiệp", "viewer"), "duplicate")
        self.assertEqual(topics.request(self.con, None, "lương", "viewer"), "wish")
        self.assertEqual(topics.request(self.con, "owid:coffee-production", "cà phê", "viewer"), "pending")
        got = topics.with_requests(CFG, self.con)
        wb = got["sources"]["worldbank"]
        self.assertEqual(wb["priority"], ["SL.UEM.TOTL.ZS"])
        self.assertEqual(wb["races"]["priority"], ["SL.UEM.TOTL.ZS"])  # mọi dạng World Bank đều được ưu tiên
        self.assertEqual(got["sources"]["owid"]["priority"], ["coffee-production"])
        self.assertNotIn("priority", CFG["sources"]["worldbank"])       # cấu hình gốc không bị sửa
        self.assertIs(topics.with_requests(CFG, self.con), CFG)          # đã dùng -> lần sau không lấy lại
        # nguồn lấy chỉ số được yêu cầu TRƯỚC xoay vòng; không yêu cầu thì xoay vòng như cũ
        inds = CFG["sources"]["worldbank"]["indicators"]
        day = date(2026, 11, 20)
        plain = worldbank.todays_indicators(inds, 1, day)
        self.assertEqual(worldbank.todays_indicators(inds, 1, day, ["SL.AGR.EMPL.ZS"])[0]["code"], "SL.AGR.EMPL.ZS")
        self.assertEqual(worldbank.todays_indicators(inds, 1, day, []), plain)
        self.assertEqual(len(worldbank.todays_indicators(inds, 2, day, ["SL.AGR.EMPL.ZS"])), 2)
        text = "\n".join(topics.weekly_lines(self.con))
        self.assertIn("lương (người xem) — CHƯA CÓ NGUỒN", text)
        self.assertIn("đã đưa vào lượt săn ý tưởng", text)

    def test_covered_topic_points_to_the_existing_video(self):
        self.published(5, "https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS?locations=VN-KR&end=2024", yt="abcdefghijk")
        self.assertEqual(topics.covered(self.con, "wb:SL.UEM.TOTL.ZS"), [(5, "abcdefghijk", "Video")])
        self.assertEqual(topics.covered(self.con, "owid:coffee-production"), [])


def thread(cid, text, author="An"):
    return {"id": cid, "snippet": {"topLevelComment": {"snippet": {
        "textOriginal": text, "authorDisplayName": author, "publishedAt": "2026-11-19T01:00:00Z", "likeCount": 2}}}}


class CommunityTest(Case):
    SUMMARY = "Tỷ lệ thất nghiệp Việt Nam năm 2024 là 1,6 %; Hàn Quốc 2,8 %."

    def setUp(self):
        super().setUp()
        self.published(1, "https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS?locations=VN-KR&end=2024",
                       title="Thất nghiệp Việt–Hàn", yt="vid1aaaaaaa", summary=self.SUMMARY)
        self.pages = {"vid1aaaaaaa": [
            {"items": [thread("c5", "Số này sai rồi, Việt Nam phải 2,3% chứ"),
                       thread("c4", "Hàn Quốc bao nhiêu phần trăm vậy ad?"),
                       thread("c3", "Làm video về giá cà phê đi kênh"),
                       thread("c2", "Kênh hay quá"), thread("c1", "Làm về lương đi")],
             "nextPageToken": None}]}

    def fetch(self, video_id, token=None, api_key=None, page_token=None):
        return self.pages.get(video_id, [{"items": []}])[0]

    def llm(self, role, goal, description, expected_output, models=None):
        if "Phân loại" in description:
            return json.dumps([{"i": 1, "kind": "bao_loi", "claim": "tỷ lệ thất nghiệp 1,6%"},
                               {"i": 2, "kind": "cau_hoi"},
                               {"i": 3, "kind": "de_xuat", "topic": "cà phê", "match": "owid:coffee-production"},
                               {"i": 4, "kind": "khen"},
                               {"i": 5, "kind": "de_xuat", "topic": "lương", "match": "wb:BIA.RA"},  # khoá bịa
                               {"i": 9, "kind": "cau_hoi"}, "rác"])
        return "Năm 2024 Hàn Quốc là 2,8%, cao hơn Việt Nam 1,6% nhé."

    def send(self, text, buttons=None, **kw):
        self.sent.append((text, buttons))
        return 100 + len(self.sent)                                      # message_id giả

    def test_one_run_end_to_end(self):
        self.sent = []
        from src.publish import youtube
        with mock.patch.object(youtube, "has_scope", return_value=False):     # token thật trên VM đã có quyền
            got = community.run(CFG, self.con, fetch=self.fetch, llm=self.llm, send=self.send)
        self.assertEqual([c["kind"] for c in got], ["bao_loi", "cau_hoi", "de_xuat", "khen", "de_xuat"])
        self.assertEqual(got[4]["match"], None)                          # khoá không có thật -> bỏ
        self.assertEqual(got[1]["reply"], "Năm 2024 Hàn Quốc là 2,8%, cao hơn Việt Nam 1,6% nhé.")
        summary, cards = self.sent[0][0], self.sent[1:]
        self.assertIn("5 bình luận mới", summary)
        self.assertIn("4 bình luận cần xử lý gửi riêng", summary)
        self.assertIn("Bot chưa có quyền đăng trả lời: gửi /capquyen", summary)
        self.assertEqual(len(cards), 4)                                 # khen: chỉ đếm, không gửi riêng
        self.assertIn("Báo SAI số liệu", cards[0][0])                   # báo sai lên đầu
        self.assertEqual(cards[0][1], [[("❌ Bỏ qua", "cno:c5")]])        # chưa có nháp: chỉ có nút bỏ qua
        self.assertIn("✍️ Nháp trả lời: Năm 2024 Hàn Quốc là 2,8%", cards[1][0])
        self.assertEqual(cards[1][1], [[("✅ Đăng trả lời", "cok:c4"), ("❌ Bỏ qua", "cno:c4")]])
        self.assertIn("đã xếp hàng ưu tiên", cards[2][0])
        self.assertIn("chưa có nguồn số liệu", cards[3][0])
        reqs = [tuple(r) for r in self.con.execute("SELECT key, origin, status FROM topic_requests ORDER BY id")]
        self.assertEqual(reqs, [("owid:coffee-production", "viewer", "pending"), (None, "viewer", "wish")])
        rows = {r["id"]: (r["status"], r["tg_message_id"]) for r in self.con.execute("SELECT * FROM comments")}
        self.assertEqual(rows["c4"], ("new", 103))
        self.assertEqual(rows["c2"], ("done", None))                     # khen
        kinds = [r[0] for r in self.con.execute("SELECT kind FROM learning_events WHERE source='viewer'")]
        self.assertEqual(kinds, ["bao_loi"])
        # lượt sau: không có bình luận mới -> không gửi gì, không trùng
        self.assertEqual(community.run(CFG, self.con, fetch=self.fetch, llm=self.llm, send=self.send), [])
        self.assertEqual(len(self.sent), 5)
        self.assertIn("báo sai số liệu 1 · câu hỏi 1 · đề xuất chủ đề 2 · khen 1",
                      "\n".join(community.weekly_lines(self.con)))

    def test_reply_drafts_never_carry_numbers_outside_the_data(self):
        video = {"title": "Thất nghiệp", "summary": self.SUMMARY}
        q = {"id": "q", "text": "Hàn Quốc bao nhiêu?"}
        made_up = lambda **kw: "Hàn Quốc là 3,7% nhé."
        self.assertIsNone(community.draft_reply(q, video, CFG, run=lambda *a, **k: made_up()))
        self.assertIsNone(community.draft_reply(q, video, CFG, run=lambda *a, **k: community.NO_ANSWER))
        self.assertIsNone(community.draft_reply(q, {"title": "x", "summary": ""}, CFG, run=lambda *a, **k: "ok"))
        self.assertEqual(community.draft_reply(q, video, CFG, run=lambda *a, **k: "Hàn Quốc 2,8% nhé."),
                         "Hàn Quốc 2,8% nhé.")

    def test_covered_request_gets_a_link_instead_of_a_queue_entry(self):
        self.published(2, "https://ourworldindata.org/grapher/coffee-production?tab=map&time=2023",
                       title="Bản đồ thế giới: cà phê", yt="coffeeaaaaa", source=dt.OWID_SOURCE)
        self.sent = []
        got = community.run(CFG, self.con, fetch=self.fetch, llm=self.llm, send=self.send)
        self.assertEqual(got[2]["reply"], "Kênh đã có video về chủ đề này nè: https://youtube.com/shorts/coffeeaaaaa")
        self.assertEqual([r[0] for r in self.con.execute("SELECT key FROM topic_requests")], [None])

    def test_paging_stops_at_the_first_comment_already_seen(self):
        self.con.execute("INSERT INTO comments (id) VALUES ('c3')"); self.con.commit()
        got = community.fetch_new(self.con, [{"id": 1, "youtube_id": "vid1aaaaaaa", "title": "t"}], fetch=self.fetch)
        self.assertEqual([c["id"] for c in got], ["c5", "c4"])

    def test_one_unreadable_video_does_not_sink_the_run(self):
        def fetch(video_id, **kw):
            if video_id == "private0000":
                raise RuntimeError("403 forbidden")
            return self.fetch(video_id, **kw)
        videos = [{"id": 9, "youtube_id": "private0000", "title": "x"}, {"id": 1, "youtube_id": "vid1aaaaaaa", "title": "t"}]
        self.assertEqual(len(community.fetch_new(self.con, videos, fetch=fetch)), 5)

    def test_without_an_api_key_the_agent_skips_quietly(self):
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            self.assertEqual(community.run(CFG, self.con, llm=self.llm, send=self.never), [])

    def never(self, *a, **k):
        raise AssertionError("không được gửi gì")


class ReplyApprovalTest(Case):
    """Kênh CHỈ đăng trả lời bình luận khi Du bấm ✅; mỗi bình luận đúng một lần."""

    def setUp(self):
        super().setUp()
        self.published(1, "https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS?locations=VN-KR&end=2024",
                       yt="vid1aaaaaaa")
        self.con.execute("INSERT INTO comments (id, youtube_id, video_id, author, text, kind, reply, status,"
                         " tg_message_id) VALUES ('Ugx123abc', 'vid1aaaaaaa', 1, 'An', 'Hàn Quốc bao nhiêu?',"
                         " 'cau_hoi', 'Hàn Quốc 2,8% nhé.', 'new', 77)")
        self.con.commit()
        self.calls = []
        for name in ("send_message", "answer_callback", "clear_buttons"):
            p = mock.patch.object(tg, name, side_effect=self._rec(name)); p.start(); self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER}); env.start(); self.addCleanup(env.stop)
        from src.publish import youtube
        self.youtube = youtube
        p = mock.patch.object(youtube, "access_token", return_value="AT"); p.start(); self.addCleanup(p.stop)

    def _rec(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
            return 200 + len(self.calls)
        return f

    def press(self, data, mid=77):
        review.handle_update(self.con, {"update_id": 1, "callback_query": {
            "id": "cb", "data": data, "from": {"id": int(OWNER)},
            "message": {"message_id": mid, "chat": {"id": int(OWNER)}}}}, {})

    def status(self):
        return self.con.execute("SELECT status FROM comments WHERE id='Ugx123abc'").fetchone()[0]

    def said(self):
        return [c[1][0] for c in self.calls if c[0] == "send_message"]

    def test_approve_posts_exactly_once(self):
        with mock.patch.object(self.youtube, "reply_comment", return_value="Ugx123abc.reply1") as post:
            self.press("cok:Ugx123abc")
            self.press("cok:Ugx123abc")                                 # bấm lặp / Telegram gửi lặp
        post.assert_called_once_with("Ugx123abc", "Hàn Quốc 2,8% nhé.", "AT")
        row = self.con.execute("SELECT status, posted_id FROM comments").fetchone()
        self.assertEqual(tuple(row), ("posted", "Ugx123abc.reply1"))
        self.assertIn(("clear_buttons", (77,), {}), self.calls)
        self.assertIn("Kênh đã trả lời An", self.said()[0])
        self.assertIn("đã xử lý rồi", self.said()[1])

    def test_without_the_comment_permission_nothing_is_posted_and_buttons_stay(self):
        refused = mock.Mock(status_code=403, text='{"error": {"status": "PERMISSION_DENIED", "message":'
                                                  ' "Request had insufficient authentication scopes."}}')
        with mock.patch.object(self.youtube.requests, "post", return_value=refused):
            self.press("cok:Ugx123abc")
        self.assertEqual(self.status(), "new")                          # bấm lại được sau /capquyen
        self.assertIn("/capquyen", self.said()[0])
        self.assertNotIn("clear_buttons", [c[0] for c in self.calls])

    def test_skip(self):
        self.press("cno:Ugx123abc")
        self.assertEqual(self.status(), "skipped")
        self.assertIn(("clear_buttons", (77,), {}), self.calls)

    def test_du_rewrites_the_reply_and_still_confirms_before_posting(self):
        own = "Cảm ơn bạn! Xem thêm: https://youtube.com/shorts/abcdefghijk"
        review.handle_update(self.con, {"update_id": 2, "message": {
            "message_id": 90, "chat": {"id": int(OWNER)}, "from": {"id": int(OWNER)}, "text": own,
            "reply_to_message": {"message_id": 77}}}, {})
        row = self.con.execute("SELECT reply, status, tg_message_id FROM comments").fetchone()
        self.assertEqual((row["reply"], row["status"]), (own, "new"))   # chưa đăng: chờ ✅
        card = [c for c in self.calls if c[0] == "send_message"][0]
        self.assertIn("Nháp mới — bấm ✅ để đăng", card[1][0])
        self.assertEqual(card[2]["buttons"][0][0], ("✅ Đăng trả lời", "cok:Ugx123abc"))
        self.assertEqual(row["tg_message_id"], 201)                     # tin mới thay tin cũ
        self.assertIn(("clear_buttons", (77,), {}), self.calls)
        # link YouTube trong câu trả lời không bị hiểu thành "gắn link cho video"
        self.assertEqual(self.con.execute("SELECT youtube_id FROM videos WHERE id=1").fetchone()[0], "vid1aaaaaaa")
        with mock.patch.object(self.youtube, "reply_comment", return_value="r2") as post:
            self.press("cok:Ugx123abc", mid=201)
        post.assert_called_once_with("Ugx123abc", own, "AT")

    def test_youtube_reply_call_and_scope_check(self):
        yt = self.youtube
        ok = mock.Mock(status_code=200, text="{}"); ok.json.return_value = {"id": "new1"}
        with mock.patch.object(yt.requests, "post", return_value=ok) as post:
            self.assertEqual(yt.reply_comment("Ugx1", "chào", "AT"), "new1")
        self.assertEqual(post.call_args.kwargs["json"], {"snippet": {"parentId": "Ugx1", "textOriginal": "chào"}})
        with mock.patch.object(yt.requests, "post", return_value=mock.Mock(status_code=500, text="lỗi")):
            with self.assertRaises(yt.YouTubeUploadError):
                yt.reply_comment("Ugx1", "chào", "AT")
        token = self.root / "tok.json"
        with mock.patch.object(yt, "TOKEN_PATH", token):
            self.assertFalse(yt.has_scope(yt.FORCE_SSL))                # chưa có token
            token.write_text(json.dumps({"scope": " ".join(yt.SCOPES[:3])}), encoding="utf-8")
            self.assertFalse(yt.has_scope(yt.FORCE_SSL))                # token cũ: thiếu quyền bình luận
            token.write_text(json.dumps({"scope": " ".join(yt.SCOPES)}), encoding="utf-8")
            self.assertTrue(yt.has_scope(yt.FORCE_SSL))


class GrowthTest(Case):
    def rows(self, views):
        out = []
        for k, v in enumerate(views, 1):
            self.published(k, f"https://data.worldbank.org/indicator/SP.DYN.LE00.IN?locations=VN-KR&end={2000 + k}",
                           title="Tuổi thọ trung bình: Việt Nam và Hàn Quốc")
            out.append({"id": k, "script_id": k, "title": f"V{k}", "views": v, "age_days": 7, "subs_gained": k})
        return out

    def test_breakout_is_detected_once_and_boosts_its_family_and_format(self):
        rows = self.rows([100, 120, 90, 110, 1500])
        found = growth.find_breakouts(rows)
        self.assertEqual([(r["id"], x) for r, x in found], [(5, 13.6)])
        self.assertEqual(growth.find_breakouts(rows[:3]), [])              # chưa đủ video để so
        notes = growth.apply_breakouts(self.con, found)
        self.assertIn("🚀 Đột biến: #5", notes[0])
        self.assertIn("đã xếp hàng làm tiếp chỉ số này", notes[0])
        self.assertEqual(growth.apply_breakouts(self.con, found), [])     # mỗi video chỉ một lần
        self.assertEqual(growth.boost_for("viet-han", "bieu-do"), 1.0)
        self.assertEqual(growth.boost_for("viet-han", "ban-do"), 0.5)
        self.assertEqual(growth.boost_for("the-gioi", "ban-do"), 0.0)
        later = (datetime.now(timezone.utc) + timedelta(days=growth.BOOST_DAYS + 1)).date().isoformat()
        self.assertEqual(growth.boost_for("viet-han", "bieu-do", today=later), 0.0)   # hết hạn
        req = self.con.execute("SELECT key, origin FROM topic_requests").fetchone()
        self.assertEqual(tuple(req), ("wb:SP.DYN.LE00.IN", "breakout"))

    def test_small_channel_noise_is_not_a_breakout(self):
        self.assertEqual(growth.find_breakouts(self.rows([10, 12, 9, 11, 120])), [])   # gấp 10 lần mà 120 lượt

    def test_report_lines_and_forecast(self):
        snap = {"date": "2026-11-22", "subscribers": 312, "views_28d": 18420, "shorts_views_28d": 17170,
                "long_hours_28d": 3.5, "net_subs_28d": 41, "shorts_views_90d": 25000, "long_hours_365d": 37.0}
        rows = [{"id": 7, "views": 1000, "subs_gained": 4}, {"id": 8, "views": 2000, "subs_gained": 2},
                {"id": 9, "views": 50, "subs_gained": 9}]                  # 50 lượt: quá ít để tính
        text = "\n".join(growth.report_lines(snap, rows, [], {}))
        self.assertIn("Người đăng ký: 312 (+41 trong 28 ngày)", text)
        self.assertIn("28 ngày: 18.420 lượt xem (Shorts 17.170) · video dài 3,5 giờ xem", text)
        self.assertIn("giờ xem video dài 365 ngày 37/8.000", text)
        self.assertIn("lượt xem Shorts 90 ngày 25.000/20.000.000", text)
        self.assertIn("Kéo người đăng ký tốt nhất: #7 (4,0 sub / 1.000 lượt xem), #8 (1,0", text)
        self.assertNotIn("#9", text)
        self.assertIsNone(growth.forecast_weeks({"subscribers": 10, "net_subs_28d": 0}, 1000))
        self.assertIn("chưa đo được cả kênh", "\n".join(growth.report_lines({}, [], [], {})))
        # kênh mới (đo thật trên VM 19/11: 3 sub, +1/28 ngày): nói mục tiêu mỗi tuần, không nói "3.988 tuần"
        tiny = dict(snap, subscribers=3, net_subs_28d=1)
        text = "\n".join(growth.report_lines(tiny, [], [], {}))
        self.assertIn("cần ~19 người mới mỗi tuần (28 ngày qua: +0,2/tuần)", text)
        self.assertNotIn("tuần nếu giữ nhịp", text)

    def test_snapshot_reads_channel_reports(self):
        from src.publish import youtube
        rep = {"all": {"views": 900, "minutes": 1200, "subs_gained": 12, "subs_lost": 2},
               "shorts": {"views": 800, "minutes": 600, "subs_gained": 10, "subs_lost": 2},
               "long": {"views": 100, "minutes": 600, "subs_gained": 2, "subs_lost": 0}}
        with mock.patch.object(youtube, "channel_report", return_value=rep), \
                mock.patch.object(youtube, "channel_stats", return_value={"subscribers": 55, "views": 1, "videos": 3}):
            snap = growth.snapshot("AT", datetime(2026, 11, 22, tzinfo=timezone.utc))
        self.assertEqual((snap["subscribers"], snap["net_subs_28d"], snap["long_hours_365d"], snap["shorts_views_90d"]),
                         (55, 10, 10.0, 800))

    def test_subscriber_pull_is_blended_into_viewer_preferences(self):
        rows = self.rows([1000, 1000, 1000, 1000])
        for r, pct, subs in zip(rows, (50, 50, 50, 50), (0, 0, 0, 12)):
            r.update(engaged_pct=pct, subs_gained=subs)
        prefs = learning.update_preferences(self.con, rows)
        self.assertEqual(prefs["metric"], "engaged_pct+sub")
        self.assertIn("kéo người đăng ký", learning.viewer_block({**prefs, "hook": {
            "doi-lap": {"n": 2, "mean": 0.5, "score": 0.3}, "cau-hoi": {"n": 2, "mean": -0.5, "score": -0.3}}}))


class TelegramTest(Case):
    def setUp(self):
        super().setUp()
        self.sent = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.sent.append(t) or 1)
        p.start(); self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER}); env.start(); self.addCleanup(env.stop)
        p = mock.patch("src.main.load_config", return_value=CFG); p.start(); self.addCleanup(p.stop)

    def say(self, text):
        review.handle_update(self.con, {"update_id": 1, "message": {
            "message_id": 9, "chat": {"id": int(OWNER)}, "from": {"id": int(OWNER)}, "text": text}}, {})
        return self.sent[-1]

    def test_du_requests_topics_and_checks_the_channel(self):
        self.assertIn("Tỷ lệ thất nghiệp: đã xếp hàng", self.say("/chude thất nghiệp"))
        self.assertIn("đã có trong hàng đợi", self.say("/chủ đề Thất Nghiệp"))
        self.assertIn("chưa có nguồn số liệu cho “lương”", self.say("/chude lương"))
        self.assertIn("Gửi kèm chủ đề", self.say("/chude"))
        self.assertIn("Chưa có lần đo cả kênh nào", self.say("/kenh"))
        learned.save_learned({"growth": {"latest": {"date": "2026-11-22", "subscribers": 3, "views_28d": 868,
                                                    "shorts_views_28d": 868, "long_hours_28d": 0.0, "net_subs_28d": 1,
                                                    "shorts_views_90d": 868, "long_hours_365d": 0.0}}})
        text = self.say("/kenh")
        self.assertIn("Lần đo gần nhất: 2026-11-22", text)
        self.assertIn("Người đăng ký: 3 (+1 trong 28 ngày)", text)
        self.assertEqual([r[0] for r in self.con.execute("SELECT origin FROM topic_requests")], ["du", "du"])


class DailyBoostTest(unittest.TestCase):
    def test_breakout_family_and_format_go_first(self):
        from src import daily
        from tests.test_daily import CFG as DAILY_CFG, DailyCase

        class Probe(DailyCase):
            def runTest(self):
                pass
        case = Probe()
        case.setUp()
        try:
            case.script(1, 26.0)
            case.script(2, 25.0)                     # ưu tiên đột biến = PREF_WEIGHT × 1,0 = +2 điểm
            case.con.execute("UPDATE ideas SET source_name=?, title='Bản đồ thế giới: cà phê' WHERE id=2",
                             (dt.OWID_SOURCE,))
            case.con.commit()
            self.assertEqual([c["id"] for c in daily.pick_candidates(case.con, DAILY_CFG)], [1, 2])
            until = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
            learned.save_learned({"growth": {"boosts": [{"family": "the-gioi", "kind": "ban-do", "until": until,
                                                         "video_id": 9, "ratio": 3.0}]}})
            picked = daily.pick_candidates(case.con, DAILY_CFG)
            self.assertEqual([c["id"] for c in picked], [2, 1])
            self.assertEqual(picked[0]["boost"], 1.0)
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
