"""Test lớp chống trùng YouTube — không gọi mạng.

    python -m unittest discover -s tests -v
"""
import logging
import unittest
from unittest import mock

from src.sources import youtube_check as yt

CFG = {"max_results": 10, "high_view_threshold": 100_000}


def api(videos):
    """videos = [(tiêu đề, lượt xem)] -> hàm giả thay requests.get."""
    def get(url, params=None, **kw):
        r = mock.Mock()
        if url == yt.SEARCH_URL:
            r.json.return_value = {"items": [{"id": {"videoId": f"v{i}"}} for i in range(len(videos))]}
        else:
            r.json.return_value = {"items": [
                {"snippet": {"title": t}, "statistics": {"viewCount": str(n)}} for t, n in videos]}
        return r
    return get


class SameTopicTest(unittest.TestCase):
    def test_country_names_alone_do_not_make_a_duplicate(self):
        kw = "điện tiêu thụ bình quân Việt Nam Hàn Quốc"
        self.assertFalse(yt.same_topic(kw, "Việt Nam vs Hàn Quốc | Highlights AFF Cup 2024"))
        self.assertTrue(yt.same_topic(kw, "So sánh điện tiêu thụ bình quân: Việt Nam thua xa Hàn Quốc?"))

    def test_generic_or_empty_keyword_never_claims_a_duplicate(self):
        self.assertFalse(yt.same_topic("Việt Nam và Hàn Quốc 2025", "Việt Nam và Hàn Quốc 2025"))
        self.assertEqual(yt.topic_tokens("Tỷ suất sinh Hàn Quốc năm 2024 là 0,75!"), {"tỷ", "suất", "sinh"})


class CountTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        p = mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": "k"}); p.start(); self.addCleanup(p.stop)

    def count(self, query, videos):
        with mock.patch.object(yt.requests, "get", api(videos)):
            return yt.count_popular_vietnamese_videos(query, CFG)

    def test_popular_but_unrelated_videos_are_not_counted(self):
        # Ca thật trên VM 12/11: hai ý tưởng World Bank bị loại vì "đã có 8-9 video view cao"
        football = [(f"Việt Nam vs Hàn Quốc trận {i} | Highlights", 3_000_000) for i in range(8)]
        self.assertEqual(self.count("điện tiêu thụ bình quân Việt Nam Hàn Quốc", football), 0)

    def test_popular_same_topic_videos_are_counted_and_unpopular_ones_are_not(self):
        videos = [("Tỷ suất sinh Hàn Quốc thấp nhất thế giới", 2_500_000),
                  ("Vì sao tỷ suất sinh của Hàn Quốc chỉ còn 0,72?", 400_000),
                  ("Tỷ suất sinh Hàn Quốc giải thích", 9_000),          # ít view: không tính
                  ("Du lịch Hàn Quốc 2025", 5_000_000)]                  # khác đề tài: không tính
        self.assertEqual(self.count("tỷ suất sinh Hàn Quốc", videos), 2)

    def test_no_key_or_api_failure_means_skip_the_check(self):
        with mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}):
            self.assertIsNone(yt.count_popular_vietnamese_videos("x", CFG))
        boom = mock.Mock(side_effect=yt.requests.ConnectionError("https://...&key=SECRET"))
        with mock.patch.object(yt.requests, "get", boom), self.assertLogs(yt.log, "WARNING") as logs:
            logging.disable(logging.NOTSET)
            self.assertIsNone(yt.count_popular_vietnamese_videos("x", CFG))
        self.assertNotIn("SECRET", " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
