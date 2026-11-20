"""Test agent Hiểu YouTube và agent Tin YouTube (src/yt_insights.py, src/yt_news.py) — không gọi mạng,
không gọi LLM. Số liệu giả lấy theo số đo THẬT trên VM ngày 19/11/2026.

    python -m unittest tests.test_yt_agents -v
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import db, review, yt_insights, yt_news
from src import telegram_bot as tg
from src.analysis import learned
from tests.test_channel_agents import CFG, OWNER

NOW = datetime(2026, 11, 20, 3, tzinfo=timezone.utc)


class Case(unittest.TestCase):
    def setUp(self):
        import logging
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, attr, val in [(db, "DB_PATH", self.root / "t.db"),
                                  (learned, "LEARNED_PATH", self.root / "learned.yaml")]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)


def fake_report(token, start, end, metrics, dimensions=None, **extra):
    f = extra.get("filters", "")
    if dimensions == "insightTrafficSourceType":
        return [{"insightTrafficSourceType": "SHORTS", "views": 1237}, {"insightTrafficSourceType": "YT_SEARCH", "views": 13},
                {"insightTrafficSourceType": "YT_OTHER_PAGE", "views": 4}, {"insightTrafficSourceType": "NO_LINK_OTHER", "views": 0}]
    if dimensions == "insightTrafficSourceDetail" and "YT_SEARCH" in f:
        return [{"insightTrafficSourceDetail": "xsmb", "views": 6}, {"insightTrafficSourceDetail": "gdp việt nam", "views": 2},
                {"insightTrafficSourceDetail": "tình không bằng tiền", "views": 1}]
    if dimensions == "insightTrafficSourceDetail" and "RELATED_VIDEO" in f:
        return [{"insightTrafficSourceDetail": "vidA", "views": 30}, {"insightTrafficSourceDetail": "vidB", "views": 10},
                {"insightTrafficSourceDetail": "ownvid", "views": 5}]
    if dimensions == "country":
        return [{"country": "VN", "views": 1177}]
    if dimensions == "subscribedStatus":
        raise RuntimeError("Analytics API 500: internal error")          # đo thật 19/11
    if dimensions == "day":
        d0 = datetime.fromisoformat(start).date()
        views = [600, 300, 50, 30, 20]
        return [{"day": (d0 + timedelta(days=k)).isoformat(), "views": v} for k, v in enumerate(views)]
    return []


def fake_channels(ids):
    known = {"vidA": ("C1", "Kênh A"), "vidB": ("C2", "Kênh B"), "ownvid": ("OWN", "Thế giới qua con số")}
    return {i: {"channel_id": known[i][0], "channel": known[i][1], "title": "x"} for i in ids if i in known}


class InsightsTest(Case):
    def setUp(self):
        super().setUp()
        pub = (NOW - timedelta(days=10)).isoformat(timespec="seconds")
        self.con.execute("INSERT INTO videos (id, script_id, file, title, status, youtube_id, published_at)"
                         " VALUES (1, 1, 'f', 'T', 'published', 'yt1', ?)", (pub,))
        self.con.commit()

    def run_update(self):
        return yt_insights.update(self.con, CFG, "AT", NOW, report=fake_report, channels=fake_channels,
                                  own_channel="OWN")

    def test_measures_and_learns_what_youtube_does_with_the_channel(self):
        text = "\n".join(self.run_update())
        snap = learned.load_learned()["platform"]["latest"]
        self.assertEqual(snap["traffic"][0], {"source": "SHORTS", "views": 1237, "pct": 98.6})
        self.assertNotIn("NO_LINK_OTHER", [t["source"] for t in snap["traffic"]])
        self.assertEqual(snap["keywords"], [{"term": "gdp việt nam", "views": 2}])   # "xsmb" lạc đề: bỏ
        self.assertEqual(snap["lifecycle"], {"videos": 1, "first2_pct": 90.0, "days_to_90": 2.0})
        self.assertEqual(list(snap["neighbors"]), ["C1", "C2"])                      # kênh của mình bị loại
        self.assertNotIn("subscribed_pct", snap)                                     # chiều lỗi 500: bỏ qua
        self.assertIn("luồng Shorts 98,6%", text)
        self.assertIn("“xsmb” (lạc đề — bỏ)", text)
        self.assertIn("“gdp việt nam”,", text)
        self.assertIn("gần như chỉ qua luồng Shorts (98,6%)", text)
        self.assertIn("đẩy chủ yếu trong 2 ngày đầu (90%", text)
        self.assertIn("VN 100%", text)
        self.assertIn("Kênh A, Kênh B", text)
        # điều học được tới đúng chỗ dùng
        self.assertIn("gdp việt nam", yt_insights.metadata_block())
        self.assertNotIn("xsmb", yt_insights.metadata_block())
        self.assertEqual(yt_insights.neighbor_channels(), {"C1": "Kênh A", "C2": "Kênh B"})
        self.assertIn("Lần đo gần nhất", yt_insights.status_text())

    def test_no_token_measures_nothing(self):
        self.assertEqual(yt_insights.update(self.con, CFG, None, NOW), [])
        self.assertFalse((self.root / "learned.yaml").exists())
        self.assertIn("Chưa có lần đo nào", yt_insights.status_text())
        self.assertEqual(yt_insights.metadata_block(), "")

    def test_lifecycle_math(self):
        self.assertEqual(yt_insights.lifecycle([0, 0, 0]), {})
        self.assertEqual(yt_insights.lifecycle([10, 10, 10, 10, 10, 10, 10, 10, 10, 10]),
                         {"views": 100, "first2_pct": 20.0, "days_to_90": 9})

    def test_metadata_writer_and_competitor_scan_use_what_was_learned(self):
        self.run_update()
        from src import crew
        seen = []
        with mock.patch.object(crew, "_run_single_task", lambda **kw: seen.append(kw["description"]) or "{}"):
            crew.write_metadata({"title": "GDP"}, [{"voice": "GDP Việt Nam 4.000 USD."}], ["h"],
                                {"channel": {"name": "K", "description": "d"}, "policy_rules": "p"})
        self.assertIn("gdp việt nam", seen[0])
        from src.analysis import competitors
        cfg = {"competitor_analysis": {"seed_queries": [], "months_back": 6, "min_subs": 1, "max_subs": 10,
                                       "max_channels": 5, "outlier_ratio": 5}}
        got = {}
        with mock.patch.object(competitors, "find_candidate_channels", return_value={}), \
                mock.patch.object(competitors, "filter_channels", side_effect=lambda ch, a, b: got.update(ch) or []), \
                mock.patch.object(competitors, "DATA_PATH", self.root / "competitors.json"):
            competitors.run_scan(cfg)
        self.assertEqual(got["C1"]["found_via"], "YouTube đặt cạnh video của kênh")


RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>YouTube Official Blog</title>
<item><title>Shorts monetization update</title><link>https://blog.youtube/news/shorts-update/</link>
<description>&lt;p&gt;Changes to YPP for Shorts&lt;/p&gt;</description><pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Old post</title><link>https://blog.youtube/news/old/</link><description>old</description>
<pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Creator Insider</title>
<entry><id>yt:video:abc</id><title>New live features</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
<published>2026-11-18T12:00:00+00:00</published><summary>Livestream tools</summary></entry></feed>"""
FEEDS = [("YouTube Official Blog", "rss"), ("Creator Insider", "atom")]


class NewsTest(Case):
    def llm(self, **kw):
        self.prompts.append(kw["description"])
        return json.dumps([{"i": 1, "relevant": True, "impact": "cao", "summary": "YouTube đổi điều kiện kiếm tiền Shorts.",
                            "action": "Đọc kỹ điều kiện mới"},
                           {"i": 2, "relevant": False, "impact": "rất cao", "summary": "Tính năng livestream."}])

    def run_news(self, **kw):
        return yt_news.run(self.con, NOW, feeds=FEEDS, get=lambda url: {"rss": RSS, "atom": ATOM}[url],
                           llm=self.llm, send=self.sent.append, **kw)

    def setUp(self):
        super().setUp()
        self.prompts, self.sent = [], []

    def test_reads_filters_alerts_once(self):
        got = self.run_news()
        self.assertEqual([it["title"] for it in got], ["Shorts monetization update"])
        self.assertEqual(len(self.prompts), 1)
        self.assertNotIn("Old post", self.prompts[0])                 # tin cũ hơn 30 ngày: không hỏi model
        self.assertEqual(len(self.sent), 1)                           # tin ảnh hưởng lớn: báo Du ngay
        self.assertIn("Shorts monetization update", self.sent[0])
        self.assertIn("Nên làm: Đọc kỹ điều kiện mới", self.sent[0])
        self.assertIn("Luật của hệ thống KHÔNG tự đổi", self.sent[0])
        rows = {r["title"]: (r["relevant"], r["impact"]) for r in self.con.execute("SELECT * FROM yt_news")}
        self.assertEqual(rows, {"Shorts monetization update": (1, "cao"), "New live features": (0, "thap"),
                                "Old post": (0, "thap")})             # mức chấm sai khuôn -> "thap"
        self.assertEqual(self.run_news(), [])                         # lượt sau: không tin mới, không báo lại
        self.assertEqual(len(self.sent), 1)
        text = "\n".join(yt_news.report_lines(self.con, NOW))
        self.assertIn("❗ Shorts monetization update: YouTube đổi điều kiện kiếm tiền Shorts. → Đọc kỹ điều kiện mới", text)
        self.assertNotIn("live", text)

    def test_dry_run_writes_and_sends_nothing(self):
        with mock.patch("builtins.print"):
            self.assertEqual(len(self.run_news(dry_run=True)), 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM yt_news").fetchone()[0], 0)
        self.assertEqual(self.sent, [])

    def test_bad_model_answers_mean_nothing_is_flagged(self):
        items = [{"source": "s", "title": "t", "summary": "x"}]
        self.assertEqual(yt_news.classify(items, run=lambda **kw: "không phải JSON")[0]["relevant"], False)
        self.assertEqual(yt_news.classify(items, run=lambda **kw: '[{"i": 1, "relevant": true, "summary": ""}]')[0]
                         ["relevant"], False)                         # không tóm tắt được thì không tính


class TelegramTest(Case):
    def test_youtube_command(self):
        sent = []
        with mock.patch.object(tg, "send_message", side_effect=lambda t, **k: sent.append(t) or 1), \
                mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER}), \
                mock.patch("src.main.load_config", return_value=CFG):
            msg = {"update_id": 1, "message": {"message_id": 9, "chat": {"id": int(OWNER)}, "from": {"id": int(OWNER)},
                                               "text": "/youtube"}}
            review.handle_update(self.con, msg, {})
            self.con.execute("INSERT INTO yt_news (id, title, link, published, relevant, impact, summary)"
                             " VALUES ('x', 'Tin A', 'https://l', '2026-11-18', 1, 'vua', 'Tóm tắt A')")
            self.con.commit()
            review.handle_update(self.con, msg, {})
        self.assertIn("Chưa có lần đo nào", sent[0])
        self.assertIn("Tin YouTube gần nhất", sent[1])
        self.assertIn("Tin A: Tóm tắt A", sent[1])


if __name__ == "__main__":
    unittest.main()
