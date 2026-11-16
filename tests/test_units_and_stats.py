"""Tiêu đề giữ đơn vị tỷ lệ/bình quân + báo cáo tuần lấy số công khai khi Analytics còn trễ.

    python -m unittest tests.test_units_and_stats -v
"""
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.analysis import weekly
from src.publish import metadata, youtube


class TitleUnitTest(unittest.TestCase):
    FDI = {"title": "Vốn FDI vào so với GDP: Việt Nam và Hàn Quốc từ 1970 đến 2025"}

    def test_real_case_video_6_is_caught(self):
        # Đã đăng 15/11: số là FDI tính theo % GDP, tiêu đề đọc như lượng vốn
        self.assertEqual(metadata.title_drops_unit("Vốn FDI của Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc", self.FDI),
                         "so với GDP")
        self.assertIsNone(metadata.title_drops_unit("FDI so với GDP của Việt Nam gấp 5 lần Hàn Quốc", self.FDI))
        self.assertIsNone(metadata.title_drops_unit("FDI của Việt Nam bằng 4,27% GDP, gấp 5 lần Hàn Quốc", self.FDI))

    def test_per_capita_and_per_100(self):
        gdp = {"title": "Cuộc đua GDP bình quân đầu người: 10 nền kinh tế châu Á"}
        self.assertEqual(metadata.title_drops_unit("Việt Nam chạm mốc 5.066 đô la ra sao?", gdp), "bình quân đầu người")
        self.assertIsNone(metadata.title_drops_unit("GDP đầu người Việt Nam chạm 5.066 đô la", gdp))
        mobile = {"title": "Thuê bao di động trên 100 dân: Việt Nam và Hàn Quốc từ 1960"}
        self.assertEqual(metadata.title_drops_unit("Việt Nam 2024 mới bằng Hàn Quốc 2018 về thuê bao?", mobile),
                         "trên 100 dân")

    def test_totals_are_left_alone(self):
        self.assertIsNone(metadata.ratio_unit({"title": "Dân số Việt Nam vượt 100 triệu"}))
        self.assertIsNone(metadata.title_drops_unit("Việt Nam vượt 100 triệu dân", {"title": "Dân số Việt Nam"}))

    def test_finalize_sends_it_back(self):
        meta = metadata.finalize({"title": "Vốn FDI của Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc"}, self.FDI,
                                 [{"voice": "Năm 2025 Việt Nam gấp 5,06 lần Hàn Quốc."}], {"publish": {}})
        self.assertTrue(any("bỏ mất đơn vị" in w for w in meta["warnings"]))


class WeeklyLateAnalyticsTest(unittest.TestCase):
    def test_videos_analytics_has_not_counted_yet_get_public_numbers(self):
        videos = [{"id": 1, "youtube_id": "old", "published_at": "2026-11-01T00:00:00+00:00"},
                  {"id": 2, "youtube_id": "zero", "published_at": "2026-11-14T00:00:00+00:00"},
                  {"id": 3, "youtube_id": "empty", "published_at": "2026-11-15T00:00:00+00:00"}]
        analytics = {"old": {"views": 120, "averageViewPercentage": 61.0}, "zero": {"views": 0}, "empty": {}}
        saved = []
        with mock.patch.dict(os.environ, {"YT_CLIENT_ID": "x", "YOUTUBE_API_KEY": "k"}), \
                mock.patch.object(youtube, "TOKEN_PATH", Path(__file__)), \
                mock.patch.object(youtube, "access_token", return_value="t"), \
                mock.patch.object(youtube, "analytics_video", side_effect=lambda vid, *a: analytics[vid]), \
                mock.patch.object(youtube, "analytics_retention", return_value=[]), \
                mock.patch.object(youtube, "public_stats", return_value={
                    "zero": {"views": 717, "likes": 3, "comments": 0}, "empty": {"views": 18, "likes": 0, "comments": 0}}), \
                mock.patch.object(weekly.db, "save_video_stats", side_effect=lambda con, vid, src, st, *r: saved.append((vid, src, st["views"]))):
            src = weekly.fetch_and_store(None, videos, datetime(2026, 11, 16, tzinfo=timezone.utc))
        self.assertEqual(src, "analytics")
        self.assertEqual(sorted(saved), [(1, "analytics", 120), (2, "public", 717), (3, "public", 18)])


if __name__ == "__main__":
    unittest.main()
