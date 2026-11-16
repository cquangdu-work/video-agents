"""Video dài hằng tuần (src/longform.py). Chạy: python -m unittest tests.test_longform -v"""
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import longform, review

NOW = datetime(2026, 11, 21, 0, 30, tzinfo=timezone.utc)
CFG = {"publish": {"disclosure": "Giọng đọc được tạo bằng AI.", "hashtags_fixed": ["#thegioiquaconso", "#Shorts"]}}


def _video(i, title, day, status="published", script=True, src="World Bank — https://x"):
    return {"id": i, "script_id": 100 + i if script else None, "title": title, "status": status,
            "youtube_id": f"yt{i}", "published_at": f"2026-11-{day:02d}T12:00:00+00:00",
            "description": f"Tóm tắt {i}\n\nNguồn: {src}\n\nNhạc nền: Bài {i % 2} (YouTube Audio Library)",
            "tags": json.dumps([f"thẻ {i}", "dữ liệu"], ensure_ascii=False)}


class WeekSelectionTest(unittest.TestCase):
    def test_only_published_shorts_of_the_last_7_days(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, script_id INTEGER, title TEXT, status TEXT,"
                    " youtube_id TEXT, published_at TEXT, description TEXT, tags TEXT)")
        con.execute("CREATE TABLE scripts (id INTEGER PRIMARY KEY, idea_id INTEGER)")
        con.execute("CREATE TABLE ideas (id INTEGER PRIMARY KEY, title TEXT)")
        con.execute("INSERT INTO scripts VALUES (103, 1)")
        con.execute("INSERT INTO ideas VALUES (1, 'Vốn FDI vào so với GDP: Việt Nam và Hàn Quốc')")
        rows = [_video(1, "cũ quá", 10), _video(2, "b", 16), _video(3, "FDI Việt Nam gấp 5,06 lần Hàn Quốc", 15),
                _video(4, "loại", 17, status="rejected"),
                _video(5, "video dài tuần trước", 18, script=False)]
        for r in rows:
            con.execute("INSERT INTO videos VALUES (:id,:script_id,:title,:status,:youtube_id,:published_at,"
                        ":description,:tags)", r)
        got = longform.week_videos(con, NOW)
        self.assertEqual([v["id"] for v in got], [3, 2])         # cũ trước mới sau
        # tiêu đề Shorts cũ bỏ mất đơn vị -> tiêu đề chương tự thêm (ca thật video #6)
        self.assertEqual(got[0]["title"], "FDI Việt Nam gấp 5,06 lần Hàn Quốc (so với GDP)")
        self.assertEqual(got[1]["title"], "b")


class TextTest(unittest.TestCase):
    def test_chapters_sources_and_hashtags(self):
        vids = [_video(1, "Thuê bao di động trên 100 dân", 14), _video(2, "FDI so với GDP gấp 5 lần", 15),
                _video(3, "GDP đầu người", 16, src="KOSIS — https://k")]
        title, desc, tags = longform.build_text(vids, [0.0, 72.4, 3700.0], "14/11–16/11", CFG)
        self.assertTrue(title.startswith("3 câu chuyện qua con số tuần 14/11–16/11"))
        self.assertLessEqual(len(title), 100)
        # mốc chương: chương đầu 0:00 (YouTube cần), định dạng phút:giây / giờ:phút:giây
        self.assertIn("0:00 Thuê bao di động trên 100 dân", desc)
        self.assertIn("1:12 FDI so với GDP gấp 5 lần", desc)
        self.assertIn("1:01:40 GDP đầu người", desc)
        self.assertEqual(desc.count("Nguồn: World Bank"), 1)    # nguồn trùng chỉ ghi một lần
        self.assertIn("Nguồn: KOSIS", desc)
        self.assertEqual(desc.count("Nhạc nền:"), 2)             # 2 bài khác nhau
        self.assertIn("Giọng đọc được tạo bằng AI.", desc)
        self.assertNotIn("#Shorts", desc)                         # video dài không gắn #Shorts
        self.assertEqual(tags.count("dữ liệu"), 1)


class PublishTest(unittest.TestCase):
    def test_long_video_is_not_pushed_to_tiktok(self):
        cfg = {"publish": {"youtube": {"mode": "api"}}}
        with mock.patch.object(review, "_publish_api") as api, mock.patch.object(review, "push_tiktok") as tt:
            review.publish(None, {"id": 9, "status": "approved", "script_id": None}, cfg)
            review.publish(None, {"id": 8, "status": "approved", "script_id": 35}, cfg)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(tt.call_count, 1)                        # chỉ Shorts


if __name__ == "__main__":
    unittest.main()
