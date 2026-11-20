"""Test agent Học kênh lớn (src/analysis/big_channels.py) — không gọi mạng, không gọi LLM.
Tình huống giả theo số đo THẬT 20/11/2026: tìm theo lượt xem kéo về cả kênh nấu ăn rất lớn lẫn kênh dữ liệu.

    python -m unittest tests.test_big_channels -v
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import db, review
from src import telegram_bot as tg
from src.analysis import big_channels as big
from src.analysis import learned
from tests.test_channel_agents import CFG, OWNER

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
CHANNELS = {
    "UCdata0000000000000000000": ("Data World", 2_000_000, [
        "Population of countries 2025", "GDP ranking Asia", "Richest countries in the world", "USA vs China economy",
        "Map of world religions", "Top 10 largest countries", "Japan vs Korea GDP", "Countries by happiness",
        "World population 1950-2025", "Poorest countries ranking"], [1000] * 9 + [12000]),
    "UCcook0000000000000000000": ("Cooking Star", 40_000_000, [
        "Making pasta", "Best burger ever", "Netherlands or Japan food?", "Cake in 60 seconds", "Street food",
        "Sushi at home", "Spicy noodles", "Perfect steak", "Pizza trick", "Taco Tuesday"], [5000] * 9 + [90000]),
    "UCtiny0000000000000000000": ("Tiny Data", 10_000, ["GDP map"] * 10, [100] * 10),
}


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def __call__(self, endpoint, **p):
        self.calls.append(endpoint)
        if endpoint == "search":
            return {"items": [{"id": {"videoId": f"v{k}"}, "snippet": {"channelId": cid, "channelTitle": c[0]}}
                              for k, (cid, c) in enumerate(CHANNELS.items())]}
        if endpoint == "channels":
            ids = p["id"].split(",") if p.get("id") else (["UCdata0000000000000000000"] if p.get("forHandle") else [])
            return {"items": [{"id": i, "snippet": {"title": CHANNELS[i][0]},
                               "statistics": {"subscriberCount": str(CHANNELS[i][1])},
                               "contentDetails": {"relatedPlaylists": {"uploads": "UU" + i[2:]}}}
                              for i in ids if i in CHANNELS]}
        if endpoint == "playlistItems":
            cid = "UC" + p["playlistId"][2:]
            return {"items": [{"contentDetails": {"videoId": f"{cid}-{k}"}} for k in range(10)]}
        if endpoint == "videos":
            out = []
            for vid in p["id"].split(","):
                cid, k = vid.rsplit("-", 1)
                title, _, titles, views = CHANNELS[cid]
                out.append({"id": vid, "snippet": {"title": titles[int(k)],
                                                   "publishedAt": (NOW - timedelta(days=3 * int(k))).isoformat()},
                            "statistics": {"viewCount": str(views[int(k)])}, "contentDetails": {"duration": "PT45S"}})
            return {"items": out}
        return {}


def gemini(answer):
    """requests.post giả trả lời của Gemini (Gemini đọc video YouTube công khai)."""
    def post(url, **kw):
        post.bodies.append(kw["json"])
        r = mock.Mock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}
        return r
    post.bodies = []
    return post


WATCHED = {"first_line": "Japan's GDP is now smaller than Germany's.", "hook_type": "so_sanh",
           "first_second": "two flags and a number", "cuts": 14, "on_screen_text": True, "ending": "quay_lai_dau",
           "topic": "GDP các nước"}


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
        self.cfg = {**CFG, "big_channels": {"queries": [{"q": "country comparison", "lang": "en"}],
                                            "min_subs": 300_000, "max_channels": 5}}


class BigChannelTest(Case):
    def test_scan_finds_outliers_niche_share_and_pace(self):
        yt = FakeYouTube()
        s = big.scan_channel({"id": "UCdata0000000000000000000", "title": "Data World", "subs": 2_000_000,
                              "uploads": "UUdata0000000000000000000"}, 3.0, yt, NOW)
        self.assertEqual((s["median_views"], s["niche"], s["per_week"]), (1000, 1.0, 2.5))
        self.assertEqual([(o["title"], o["ratio"], o["number"]) for o in s["outliers"]],
                         [("Poorest countries ranking", 12.0, False)])
        self.assertEqual(big.title_features("Japan vs Korea GDP 2025?"),
                         {"number": True, "question": True, "compare": True})

    def test_weekly_run_learns_structure_from_the_right_channels_only(self):
        yt, post = FakeYouTube(), gemini(WATCHED)
        text = "\n".join(big.update(self.con, self.cfg, NOW, get=yt, post=post))
        data = learned.load_learned()["big_channels"]
        self.assertEqual([c["title"] for c in data["channels"]], ["Data World"])   # nấu ăn: lạc ngách; Tiny: nhỏ
        pb = data["playbook"]
        self.assertEqual((pb["channels"], pb["outliers"], pb["watched"]), (1, 1, 1))
        self.assertEqual(pb["hook_types"], {"so_sanh": 1})
        self.assertEqual(pb["seconds_per_shot"], 3.0)                               # 45 giây / (14 + 1) hình
        self.assertIn("youtube.com/watch?v=UCdata0000000000000000000-9",
                      post.bodies[0]["contents"][0]["parts"][0]["file_data"]["file_uri"])
        self.assertIn("Học từ kênh lớn (1 kênh, 1 video đột biến, đã xem 1)", text)
        self.assertIn("Data World (2.000k)", text)
        self.assertIn("đối lập / so sánh con số 1", text)
        self.assertIn("đã xếp hàng: GDP các nước", text)                           # chủ đề khớp nguồn của kênh
        req = self.con.execute("SELECT key, origin FROM topic_requests").fetchone()
        self.assertEqual(tuple(req), ("wb:NY.GDP.PCAP.CD", "big_channel"))
        # Biên kịch học CẤU TRÚC, được dặn không chép
        block = big.writer_block()
        self.assertIn("Đổi hình ~3 giây/lần", block)
        self.assertIn("Japan's GDP is now smaller than Germany's.", block)
        self.assertIn("KHÔNG dịch / chép", block)
        # tuần sau: không tìm lại kênh (tốn quota), không xem lại video đã xem
        yt2, post2 = FakeYouTube(), gemini(WATCHED)
        big.update(self.con, self.cfg, NOW + timedelta(days=7), get=yt2, post=post2)
        self.assertNotIn("search", yt2.calls)
        self.assertEqual(post2.bodies, [])

    def test_model_answers_are_clamped(self):
        bad = gemini([{"first_line": "x", "hook_type": "viral!!", "cuts": 500, "ending": "?", "on_screen_text": "yes"}])
        w = big.watch("vid", 45, bad)
        self.assertEqual((w["hook_type"], w["cuts"], w["ending"], w["on_screen_text"]), ("khac", None, "khac", False))

        def broken(url, **kw):
            raise RuntimeError("400 Unsupported MIME type")
        self.assertEqual(big.watch("vid", 45, broken), {})

    def test_titles_too_close_to_a_big_channel_are_sent_back(self):
        learned.save_learned({"big_channels": {"titles": ["GDP Việt Nam vượt Thái Lan năm 2025"]}})
        self.assertTrue(big.too_similar("GDP Việt Nam vượt Thái Lan năm 2025!"))
        self.assertEqual(big.too_similar("Dân số Hàn Quốc giảm năm thứ 5 liên tiếp"), "")
        from src.publish import metadata
        meta = metadata.finalize({"title": "GDP Việt Nam vượt Thái Lan năm 2025", "description": "d", "hashtags": [],
                                  "tags": []}, {"title": "GDP"}, [{"voice": "GDP Việt Nam vượt Thái Lan năm 2025."}],
                                 {"publish": {}})
        self.assertTrue(any("quá giống tiêu đề video của kênh khác" in w for w in meta["warnings"]))

    def test_metadata_hint_needs_enough_outliers(self):
        self.assertEqual(big.metadata_block({"playbook": {"outliers": 2, "titles": {"number": 50, "question": 0,
                                                                                    "compare": 50}}}), "")
        hint = big.metadata_block({"playbook": {"outliers": 8, "titles": {"number": 75, "question": 12, "compare": 50}}})
        self.assertIn("8 video đột biến", hint)
        self.assertIn("75% có con số", hint)

    def test_du_adds_a_channel_from_telegram(self):
        yt, sent = FakeYouTube(), []
        with mock.patch.object(big, "_get", yt), \
                mock.patch.object(tg, "send_message", side_effect=lambda t, **k: sent.append(t) or 1), \
                mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER}), \
                mock.patch("src.main.load_config", return_value=CFG):
            say = lambda text: review.handle_update(self.con, {"update_id": 1, "message": {
                "message_id": 9, "chat": {"id": int(OWNER)}, "from": {"id": int(OWNER)}, "text": text}}, {})
            say("/kenhlon")
            say("/kenhlon them https://www.youtube.com/@dataworld")
            say("/kenhlon")
        self.assertIn("Chưa có kênh lớn nào", sent[0])
        self.assertIn("Đã thêm kênh “Data World” (2.000.000 người đăng ký)", sent[1])
        self.assertIn("Đang học từ 1 kênh: Data World", sent[2])
        self.assertTrue(learned.load_learned()["big_channels"]["channels"][0]["manual"])


if __name__ == "__main__":
    unittest.main()
