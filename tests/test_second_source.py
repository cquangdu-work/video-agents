"""Test kiểm chứng nguồn thứ hai (Our World in Data) cho ý tưởng số liệu World Bank. Không gọi mạng.

    python -m unittest discover -s tests -v
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src import review, second_source as ss
from src.sources import datatable

WB = datatable.WB_SOURCE
PAIR = ("Chỉ số: Tuổi thọ trung bình (tuổi). Nguồn: World Bank Open Data, mã SP.DYN.LE00.IN.\n"
        "Việt Nam theo năm: 2018: 74,1; 2024: 74,7.\nHàn Quốc theo năm: 2018: 82,6; 2024: 83,6.")
OWID_TABLE = {("VNM", 2018): 74.1, ("VNM", 2023): 74.59, ("KOR", 2018): 83.34, ("KOR", 2023): 84.33,
              ("NGA", 2023): 54.46, ("MCO", 2023): 86.37}


class FetchTest(unittest.TestCase):
    def test_csv_is_parsed_and_cached(self):
        csv_text = ("entity,code,year,life_expectancy_0\nAfrica,,2023,64.2\nVietnam,VNM,2023,74.588\n"
                    "Vietnam,VNM,-10000,1\nSouth Korea,KOR,2023,84.329\n")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ss, "CACHE", Path(d)):
            get = mock.Mock(return_value=mock.Mock(text=csv_text, raise_for_status=lambda: None))
            with mock.patch.object(ss.requests, "get", get):
                t = ss.fetch_table("life-expectancy")
                ss.fetch_table("life-expectancy")                  # lần 2: lấy từ bộ đệm
            self.assertEqual(get.call_count, 1)
            self.assertEqual(t[("VNM", 2023)], 74.588)
            self.assertNotIn(("", 2023), t)                        # châu lục (không mã) bị bỏ
            with mock.patch.object(ss.requests, "get", get):
                ss.fetch_table("life-expectancy", now=time.time() + 8 * 86400)   # cũ hơn 7 ngày
            self.assertEqual(get.call_count, 2)


class CheckTest(unittest.TestCase):
    def check(self, summary, table=OWID_TABLE, source=WB, scale=1.0):
        return ss.check({"summary": summary, "source_name": source}, scale, fetch=lambda slug: table)

    def test_pair_idea_matches_including_the_year_owid_has_not_published_yet(self):
        r = self.check(PAIR)
        self.assertEqual(r["status"], "ok")
        self.assertIn("4/4 điểm khớp", r["summary"])
        latest_vn = [c for c in r["checks"] if c["label"] == "Việt Nam" and c["year"] == 2024][0]
        self.assertEqual(latest_vn["their_year"], 2023)             # Liên Hợp Quốc chậm một năm
        self.assertIn("life-expectancy", r["url"])

    def test_world_idea_also_checks_the_top_and_bottom_country(self):
        world = datatable.world_table_line(2024, {"Monaco": 86.5, "Nigeria": 54.6, "Việt Nam": 74.7})
        r = self.check(PAIR + "\n" + world)
        self.assertEqual({c["label"] for c in r["checks"]}, {"Việt Nam", "Hàn Quốc", "Monaco", "Nigeria"})

    def test_big_gaps_are_named(self):
        r = self.check(PAIR, table={**OWID_TABLE, ("KOR", 2023): 95.0})
        self.assertEqual(r["status"], "warn")
        self.assertIn("LỆCH LỚN: Hàn Quốc 2024", r["summary"])

    def test_what_cannot_be_checked_is_said_plainly(self):
        self.assertIn("bài báo", self.check(PAIR, source="Hankyoreh")["summary"])
        gdp = PAIR.replace("SP.DYN.LE00.IN", "NY.GDP.PCAP.CD")     # OWID không có USD hiện hành
        self.assertEqual(self.check(gdp)["status"], "none")
        self.assertEqual(self.check(PAIR, table={})["status"], "none")

        def down(slug):
            raise ConnectionError("mạng")
        r = ss.check({"summary": PAIR, "source_name": WB}, fetch=down)
        self.assertEqual(r["status"], "none")                       # mạng lỗi không chặn kịch bản

    def test_units_follow_the_indicator(self):
        # dân số: tóm tắt ghi "triệu người" (scale 1.000.000); tử vong trẻ: OWID trên 100, WB trên 1.000
        pop = PAIR.replace("SP.DYN.LE00.IN", "SP.POP.TOTL").replace("74,1", "95,5").replace("74,7", "100,9")
        pop = pop.replace("82,6", "51,6").replace("83,6", "51,7")
        table = {("VNM", 2018): 95.5e6, ("VNM", 2023): 100.4e6, ("KOR", 2018): 51.6e6, ("KOR", 2023): 51.7e6}
        cfg = {"sources": {"worldbank": {"indicators": [{"code": "SP.POP.TOTL", "scale": 1000000}]}}}
        self.assertEqual(ss.scale_for(pop, cfg), 1e6)
        self.assertEqual(self.check(pop, table=table, scale=1e6)["status"], "ok")
        imr = PAIR.replace("SP.DYN.LE00.IN", "SP.DYN.IMRT.IN").replace("74,1", "16,5").replace("74,7", "15,6")
        imr = imr.replace("82,6", "2,7").replace("83,6", "2,4")
        table = {("VNM", 2018): 1.65, ("VNM", 2023): 1.57, ("KOR", 2018): 0.27, ("KOR", 2023): 0.24}
        self.assertEqual(self.check(imr, table=table)["status"], "ok")


class ReviewLineTest(unittest.TestCase):
    def test_stored_result_is_shown_and_old_scripts_are_checked_on_the_fly(self):
        stored = {"factcheck": json.dumps({"second_source": {"status": "ok", "summary": "4/4 điểm khớp"}})}
        self.assertEqual(review.second_source_line(stored, {}), "✅ Nguồn 2: 4/4 điểm khớp")
        old = {"factcheck": None, "summary": PAIR, "source_name": WB}
        with mock.patch.object(ss, "fetch_table", lambda slug: OWID_TABLE):
            self.assertIn("4/4 điểm khớp", review.second_source_line(old, {}))
        caption = review.format_review_caption(3, 18, {"title": "T"}, [], "⚠️ Nguồn 2: lệch")
        self.assertIn("⚠️ Nguồn 2: lệch", caption)


if __name__ == "__main__":
    unittest.main()
