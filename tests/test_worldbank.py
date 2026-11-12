"""Test nguồn dữ liệu World Bank — không gọi mạng.

    python -m unittest discover -s tests -v
"""
import logging
import unittest
from datetime import date
from unittest import mock

from src import crew, main
from src.sources import worldbank as wb

COUNTRIES = [{"iso3": "VNM", "iso2": "VN", "name": "Việt Nam"},
             {"iso3": "KOR", "iso2": "KR", "name": "Hàn Quốc"}]
GDP = {"code": "NY.GDP.PCAP.CD", "name": "GDP bình quân đầu người", "unit": "USD"}
SERIES = {
    "VNM": [(1985, 239.0), (1990, 98.8), (2000, 404.03), (2010, 1683.0), (2020, 3534.0), (2025, 5065.99)],
    "KOR": [(1960, 159.0), (1980, 1746.0), (1988, 4889.0), (1990, 6813.0), (2000, 12710.3),
            (2020, 33646.0), (2025, 36226.97)],
}


def api_payload(series: dict) -> list:
    rows = [{"countryiso3code": c, "date": str(y), "value": v} for c, pts in series.items() for y, v in pts]
    rows.append({"countryiso3code": "VNM", "date": "1970", "value": None})    # năm thiếu số liệu
    return [{"page": 1}, rows]


class FormatTest(unittest.TestCase):
    def test_numbers_are_written_the_vietnamese_way_and_rounded_to_be_readable(self):
        self.assertEqual([wb.vn_number(x) for x in (36226.97, 404.03, 83.74, 0.721, 101598527)],
                         ["36.227", "404", "83,7", "0,72", "101.598.527"])
        self.assertEqual(wb.spoken_scale(101598527), " (khoảng 102 triệu)")
        self.assertEqual(wb.spoken_scale(1.872e12), " (khoảng 1,87 nghìn tỷ)")
        self.assertEqual(wb.spoken_scale(5066), "")

    def test_change_is_described_in_words(self):
        self.assertEqual(wb.change_phrase(239, 5066), "tăng gấp 21,2 lần")
        self.assertEqual(wb.change_phrase(58.0, 74.7), "tăng 28,8%")
        self.assertEqual(wb.change_phrase(6.27, 1.90), "giảm 69,7%")
        self.assertEqual(wb.change_phrase(0, 5), "")

    def test_catch_up_year_only_when_values_really_match(self):
        self.assertEqual(wb.catch_up_year(5065.99, SERIES["KOR"]), (1988, 4889.0))
        self.assertIsNone(wb.catch_up_year(98.2, [(2000, 30.0), (2025, 45.8)]))   # chưa bao giờ ngang nhau


class BuildItemTest(unittest.TestCase):
    def test_idea_carries_the_real_numbers_and_the_time_lag_angle(self):
        item = wb.build_item(GDP, COUNTRIES, SERIES)
        self.assertEqual(item["title"], "GDP bình quân đầu người: Việt Nam và Hàn Quốc từ 1960 đến 2025")
        self.assertEqual(item["url"],
                         "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD?locations=VN-KR&end=2025")
        self.assertEqual((item["source"], item["lang"]), (wb.SOURCE_NAME, "vi"))
        s = item["summary"]
        self.assertIn("Việt Nam: năm 1985 là 239 USD; năm 2025 là 5.066 USD.", s)
        self.assertIn("Số mới nhất: Hàn Quốc gấp 7,15 lần Việt Nam.", s)
        self.assertIn("Việt Nam năm 2025 (5.066 USD) tương đương Hàn Quốc năm 1988 (4.889 USD)"
                      " — cách nhau 37 năm.", s)
        self.assertIn("Hàn Quốc theo năm: 1960: 159; 1980: 1.746; 1990: 6.813; 2000: 12.710;"
                      " 2020: 33.646; 2025: 36.227.", s)

    def test_series_can_be_read_back_from_the_summary(self):
        item = wb.build_item(GDP, COUNTRIES, SERIES)
        got = wb.parse_series(item["summary"])
        self.assertEqual([s["label"] for s in got], ["Việt Nam", "Hàn Quốc"])
        self.assertEqual(got[0]["xs"], [1985, 1990, 2000, 2010, 2020, 2025])
        self.assertEqual(got[0]["ys"], [239.0, 98.8, 404.0, 1683.0, 3534.0, 5066.0])
        self.assertEqual(got[1]["ys"][-1], 36227.0)
        self.assertEqual(wb.parse_series("Bài báo bình thường, năm 2020 có 5 người."), [])
        self.assertEqual(wb.parse_vn_number("0,75"), 0.75)

    def test_thin_data_gives_no_idea(self):
        self.assertIsNone(wb.build_item(GDP, COUNTRIES, {"VNM": SERIES["VNM"][:3], "KOR": SERIES["KOR"]}))

    def test_script_numbers_copied_from_the_record_pass_the_fabrication_gate(self):
        item = wb.build_item(GDP, COUNTRIES, SERIES)
        idea = {"title": item["title"], "summary": item["summary"]}
        script = {"scenes": [
            {"voice": "Năm 2025, GDP đầu người Việt Nam đạt 5.066 USD, Hàn Quốc 36.227 USD."},
            {"voice": "Tức là gấp 7,15 lần, và Việt Nam hôm nay bằng Hàn Quốc năm 1988."},
            {"voice": "Khoảng cách là 37 năm; sau 40 năm Việt Nam tăng gấp 21,2 lần."}]}
        self.assertEqual(crew.unsourced_numbers(script, idea, item["summary"]), ["40"])   # 40 là tự suy


class FetchTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.cfg = {"per_day": 2, "start_year": 1960, "countries": COUNTRIES, "indicators": [
            GDP, {"code": "X.DEAD", "name": "Chỉ số chết", "unit": ""},
            {"code": "SP.DYN.LE00.IN", "name": "Tuổi thọ trung bình", "unit": "tuổi"}]}

    def test_rotation_walks_through_the_whole_list(self):
        inds = list("ABCDE")
        d = date(2026, 11, 12)
        days = [wb.todays_indicators(inds, 2, date.fromordinal(d.toordinal() + k)) for k in range(5)]
        self.assertEqual({x for day in days for x in day}, set(inds))        # 5 ngày phủ hết 5 chỉ số
        self.assertTrue(all(len(day) == 2 for day in days))
        self.assertEqual(wb.todays_indicators([], 2), [])
        self.assertEqual(sorted(wb.todays_indicators(inds, 9, d)), inds)     # xin dư cũng không lặp

    def test_one_dead_indicator_does_not_stop_the_others(self):
        def get(url, **kw):
            r = mock.Mock()
            if "X.DEAD" in url:
                r.raise_for_status.side_effect = wb.requests.HTTPError("502")
            r.json.return_value = api_payload(SERIES)
            return r
        today = next(date.fromordinal(n) for n in range(date(2026, 1, 1).toordinal(), 800000)
                     if [i["code"] for i in wb.todays_indicators(self.cfg["indicators"], 2,
                                                                 date.fromordinal(n))][:2]
                     == ["NY.GDP.PCAP.CD", "X.DEAD"])
        with mock.patch.object(wb.requests, "get", get):
            items = wb.fetch_worldbank(self.cfg, today)
        self.assertEqual([i["title"].split(":")[0] for i in items], ["GDP bình quân đầu người"])
        self.assertEqual(wb.fetch_worldbank({"countries": COUNTRIES[:1], "indicators": [GDP]}), [])

    def test_null_years_are_dropped_and_series_sorted(self):
        r = mock.Mock(); r.json.return_value = api_payload(SERIES)
        with mock.patch.object(wb.requests, "get", return_value=r):
            got = wb.fetch_series("NY.GDP.PCAP.CD", ["VNM", "KOR"], 1960)
        self.assertEqual(got, SERIES)

    def test_the_record_itself_is_the_source_text(self):
        fetch = mock.Mock(return_value="toàn văn bài báo")
        data_idea = {"source_name": wb.SOURCE_NAME, "source_url": "https://data...", "summary": "bảng số"}
        self.assertEqual(main.source_text_for(data_idea, fetch), "bảng số")
        fetch.assert_not_called()                     # trang World Bank là app JS, không có số trong HTML
        news = {"source_name": "Hankyoreh", "source_url": "https://hani/1", "summary": "tóm tắt"}
        self.assertEqual(main.source_text_for(news, fetch), "toàn văn bài báo")


ASIA = [{"iso3": "VNM", "iso2": "VN", "name": "Việt Nam"}, {"iso3": "KOR", "iso2": "KR", "name": "Hàn Quốc"},
        {"iso3": "JPN", "iso2": "JP", "name": "Nhật Bản"}, {"iso3": "IND", "iso2": "IN", "name": "Ấn Độ"}]
RACE = {
    "VNM": [(1990, 98.8), (1995, 288.0), (2000, 404.0), (2025, 5066.0)],
    "KOR": [(1990, 6813.0), (1995, 13002.0), (2000, 12710.0), (2025, 36227.0)],
    "JPN": [(1990, 26345.0), (1993, 35000.0), (1995, 44000.0), (2000, 39000.0), (2025, 35951.0)],
    "IND": [(1990, 371.0), (1995, 380.0), (2000, 443.0), (2025, 2702.0)],
}


class RaceTest(unittest.TestCase):
    def test_race_years_are_common_years_every_5_plus_first_and_last(self):
        self.assertEqual(wb.race_years(RACE), [1990, 1995, 2000, 2025])
        self.assertEqual(wb.race_years({"A": [(1991, 1), (2024, 2)], "B": [(1991, 3), (2024, 4)]}), [1991, 2024])
        self.assertEqual(wb.race_years({}), [])

    def test_race_idea_tells_who_passed_whom(self):
        item = wb.build_race_item({"code": "NY.GDP.PCAP.CD", "name": "GDP bình quân đầu người", "unit": "USD"},
                                  ASIA, RACE, ["VNM", "KOR"])
        self.assertEqual(item["title"], "Cuộc đua GDP bình quân đầu người: 4 nền kinh tế châu Á từ 1990 đến 2025")
        other = wb.build_race_item({"code": "X", "name": "Tỷ lệ người dùng Internet", "unit": "%"}, ASIA, RACE, [])
        self.assertTrue(other["title"].startswith("Cuộc đua tỷ lệ người dùng Internet:"))
        s = item["summary"]
        self.assertIn("Xếp hạng năm 1990: 1. Nhật Bản 26.345; 2. Hàn Quốc 6.813; 3. Ấn Độ 371; 4. Việt Nam 98,8.", s)
        self.assertIn("Việt Nam: hạng 4 năm 1990, hạng 3 năm 2025 — vượt Ấn Độ.", s)
        self.assertIn("Hàn Quốc: hạng 2 năm 1990, hạng 1 năm 2025 — vượt Nhật Bản.", s)
        self.assertIn("locations=VN-KR-JP-IN", item["url"])
        rows = wb.parse_series(s)                                # bảng đọc ngược lại được cho cuộc đua
        self.assertEqual([r["label"] for r in rows], ["Hàn Quốc", "Nhật Bản", "Việt Nam", "Ấn Độ"])
        self.assertEqual(rows[0]["xs"], [1990, 1995, 2000, 2025])

    def test_lost_places_are_reported_too(self):
        flipped = {c: [(y, -v) for y, v in s] for c, s in RACE.items()}
        flipped = {c: [(y, v + 50000) for y, v in s] for c, s in flipped.items()}
        s = wb.build_race_item({"code": "X", "name": "Chỉ số", "unit": ""}, ASIA, flipped, ["VNM"])["summary"]
        self.assertIn("Việt Nam: hạng 1 năm 1990, hạng 2 năm 2025 — bị vượt bởi Ấn Độ.", s)

    def test_too_few_countries_or_years_gives_no_race(self):
        ind = {"code": "X", "name": "Chỉ số", "unit": ""}
        self.assertIsNone(wb.build_race_item(ind, ASIA, {k: RACE[k] for k in ("VNM", "KOR")}, []))
        short = {c: s[:2] for c, s in RACE.items()}
        self.assertIsNone(wb.build_race_item(ind, ASIA, short, []))

    def test_scale_and_start_year_per_indicator(self):
        r = mock.Mock(); r.json.return_value = api_payload({"VNM": [(2000, 2.0e9)], "KOR": [(2000, 5.0e9)]})
        with mock.patch.object(wb.requests, "get", return_value=r) as get:
            got = wb.fetch_indicator({"code": "NY.GDP.MKTP.CD", "scale": 1e9, "start_year": 2000},
                                     ["VNM", "KOR"], 1960)
        self.assertEqual(got, {"VNM": [(2000, 2.0)], "KOR": [(2000, 5.0)]})
        self.assertTrue(get.call_args.kwargs["params"]["date"].startswith("2000:"))

    def test_slow_first_answer_is_retried_after_a_pause(self):
        # Đo thật 12/11: URL mới treo > 60 giây, gọi lại sau ~20 giây thì trả ngay
        r = mock.Mock(); r.json.return_value = api_payload(SERIES)
        answers = [wb.requests.Timeout("treo"), r]

        def get(*a, **kw):
            x = answers.pop(0)
            if isinstance(x, Exception):
                raise x
            return x
        with mock.patch.object(wb.requests, "get", get), mock.patch.object(wb.time, "sleep") as nap:
            self.assertEqual(wb.fetch_series("X", ["VNM", "KOR"], 1960), SERIES)
        nap.assert_called_once_with(wb.RETRY_PAUSE)
        with mock.patch.object(wb.requests, "get", side_effect=wb.requests.Timeout("treo mãi")),                 mock.patch.object(wb.time, "sleep"), self.assertRaises(wb.requests.Timeout):
            wb.fetch_series("X", ["VNM"], 1960)


if __name__ == "__main__":
    unittest.main()
