"""Test các nâng cấp chất lượng kịch bản 19/11/2026 (từ số liệu giữ chân người xem của video #6, #7):
điểm nhấn + cách nói dễ hình dung tính sẵn từ bảng số, luật 15 giây đầu, câu kết quay lại hook,
cổng câu nêu nguyên nhân. Không gọi mạng, không gọi LLM.

    python -m unittest tests.test_story_quality -v
"""
import json
import unittest

from src import claims, crew, story
from src.sources import datatable as dt
from src.sources import worldbank as wb
from tests.test_daily import DailyCase


class FractionTest(unittest.TestCase):
    def test_percent_becomes_a_simple_fraction(self):
        self.assertEqual(dt.fraction_phrase(68.6, "phụ nữ"), "cứ 3 phụ nữ thì 2")
        self.assertEqual(dt.fraction_phrase(38.8, "người"), "cứ 5 người thì 2")
        self.assertEqual(dt.fraction_phrase(74.7, "người"), "cứ 4 người thì 3")
        self.assertEqual(dt.fraction_phrase(40.0, "xe mới bán"), "cứ 5 xe mới bán thì 2")

    def test_when_no_small_fraction_fits_use_ten_or_hundred(self):
        self.assertEqual(dt.fraction_phrase(56.8, "người"), "cứ 10 người thì gần 6")
        self.assertEqual(dt.fraction_phrase(2.1, "người lao động"), "cứ 100 người lao động thì 2")
        self.assertEqual(dt.fraction_phrase(96.3, "người"), "cứ 100 người thì hơn 96")
        self.assertEqual(dt.fraction_phrase(0.3, "người"), "chưa tới 1 trong 100 người")
        self.assertEqual(dt.fraction_phrase(100, "người"), "")
        self.assertEqual(dt.fraction_phrase(0, "người"), "")

    def test_relatable_line_follows_the_indicator_config(self):
        line = dt.relatable_line([("Việt Nam", 68.57), ("Hàn Quốc", 56.8)], "%", {"per": "phụ nữ"})
        self.assertEqual(line, f"{dt.RELATE_HEADER} Việt Nam 68,6% ≈ cứ 3 phụ nữ thì 2;"
                               " Hàn Quốc 56,8% ≈ cứ 10 phụ nữ thì gần 6.")
        money = dt.relatable_line([("Việt Nam", 5066.0)], "USD", {"period": "tháng"})
        self.assertIn("khoảng 422 USD mỗi tháng", money)
        self.assertEqual(dt.relatable_line([("Việt Nam", 5.0)], "% GDP", {}), "")      # không cấu hình
        self.assertEqual(dt.relatable_line([("Việt Nam", None)], "%", {"per": "người"}), "")


class BeatsTest(unittest.TestCase):
    VN = [(1990, 1.0), (1995, 2.0), (2000, 4.0), (2005, 9.0), (2010, 12.0), (2015, 14.0), (2020, 13.0), (2025, 15.0)]
    KR = [(1990, 5.0), (1995, 6.0), (2000, 7.0), (2005, 8.0), (2010, 9.0), (2015, 10.0), (2020, 11.0), (2025, 11.5)]

    def beats(self, unit="kWh"):
        return dt.story_beats({"Việt Nam": self.VN, "Hàn Quốc": self.KR}, ["Việt Nam", "Hàn Quốc"], unit)

    def test_crossover_gap_peak_fastest_and_milestone(self):
        b = self.beats()
        self.assertIn("Năm 2005: Việt Nam vượt Hàn Quốc (Việt Nam 9 kWh, Hàn Quốc 8 kWh)", b)
        self.assertIn("Khoảng cách: năm 1990 Hàn Quốc gấp 5 lần Việt Nam; năm 2025 Việt Nam gấp 1,3 lần Hàn Quốc", b)
        self.assertIn("Giai đoạn Việt Nam thay đổi nhanh nhất: 2000–2005, từ 4 kWh lên 9 kWh", b)
        self.assertIn("Việt Nam vượt mốc 10 kWh vào năm 2010", b)
        self.assertFalse(any(x.startswith("Đỉnh của Việt Nam") for x in b))      # 2015 -> 2025 vẫn cao hơn

    def test_peak_inside_the_series_is_reported(self):
        vn = self.VN[:-1] + [(2025, 12.5)]                                         # đỉnh 2015 (14) rồi giảm
        b = dt.story_beats({"Việt Nam": vn}, ["Việt Nam"], "kWh")
        self.assertIn("Đỉnh của Việt Nam: năm 2015 (14 kWh); năm 2025 còn 12,5 kWh", b)

    def test_percentages_use_points_for_the_gap(self):
        vn = [(1990, 74.7), (2000, 70.0), (2010, 71.7), (2025, 68.6)]
        kr = [(1990, 47.2), (2000, 49.4), (2010, 49.8), (2025, 56.8)]
        b = dt.story_beats({"Việt Nam": vn, "Hàn Quốc": kr}, ["Việt Nam", "Hàn Quốc"], "%")
        self.assertIn("Khoảng cách: năm 1990 Việt Nam hơn Hàn Quốc 27,5 điểm phần trăm;"
                      " năm 2025 Việt Nam hơn Hàn Quốc 11,8 điểm phần trăm", b)

    def test_beats_are_in_the_summary_and_numbers_pass_the_gate(self):
        ind = {"code": "X", "name": "Điện tiêu thụ bình quân đầu người", "unit": "kWh", "period": "ngày"}
        countries = [{"iso3": "VNM", "iso2": "VN", "name": "Việt Nam"}, {"iso3": "KOR", "iso2": "KR", "name": "Hàn Quốc"}]
        s = wb.build_item(ind, countries, {"VNM": self.VN, "KOR": self.KR})["summary"]
        self.assertIn(dt.BEATS_HEADER, s)
        self.assertIn("• Năm 2005: Việt Nam vượt Hàn Quốc", s)
        self.assertIn(dt.RELATE_HEADER, s)
        self.assertEqual(len(wb.parse_series(s)), 2)                    # dòng "theo năm" vẫn đọc ngược được
        say = {"scenes": [{"voice": "Năm 2005 Việt Nam vượt Hàn Quốc với 9 kWh mỗi người."},
                          {"voice": "Giai đoạn 2000–2005 tăng từ 4 lên 9 kWh."}]}
        self.assertEqual(crew.unsourced_numbers(say, {"summary": s}, s), [])

    def test_leading_zero_years_are_trimmed_but_small_real_values_kept(self):
        vn = [(1960, 0.0), (1980, 0.0), (1990, 0.0), (2000, 1.0), (2024, 128.0)]
        kr = [(1960, 0.0), (1980, 0.0), (1990, 1.6), (2000, 57.0), (2024, 173.0)]
        a, b = dt.trim_leading(vn, kr)
        self.assertEqual(a[0][0], 1990)                                 # 1960-1980 toàn số 0: bỏ
        self.assertEqual(b[0], (1990, 1.6))
        gdp_kr = [(1960, 159.0), (2025, 36227.0)]
        self.assertEqual(dt.trim_leading(gdp_kr)[0], gdp_kr)            # 159 USD là chuyện đáng kể: giữ

    def test_race_reports_the_biggest_climb(self):
        series = {"Việt Nam": [(2015, 0.1), (2020, 1.0), (2025, 40.0)],
                  "Mỹ": [(2015, 0.7), (2020, 2.3), (2025, 10.0)],
                  "Anh": [(2015, 1.0), (2020, 11.0), (2025, 30.0)],
                  "Nhật Bản": [(2015, 0.5), (2020, 0.8), (2025, 3.0)]}
        lines = dt.race_lines(series, [2015, 2020, 2025], ["Việt Nam"], "%")
        self.assertIn("• Giai đoạn Việt Nam leo hạng mạnh nhất: 2020–2025, từ hạng 3 lên hạng 1.", lines)
        self.assertNotIn(dt.BEATS_HEADER, dt.race_lines(series, [2015, 2025], [], None))


class OpeningTest(unittest.TestCase):
    def script(self, *voices):
        return {"scenes": [{"voice": v} for v in voices]}

    def test_the_real_drop_points_of_video_7_are_caught(self):
        s = self.script("Vì sao 100 người Việt Nam hiện sở hữu tới 128 thuê bao di động?",
                        "Chiếc điện thoại trong tay bạn là một phần của hạ tầng viễn thông khổng lồ.",
                        "Nó thay đổi hoàn toàn cách chúng ta làm việc và kết nối mỗi ngày.",
                        "Nhìn lại năm 1960, cả Việt Nam và Hàn Quốc đều ghi nhận 0 thuê bao.",
                        "Đến năm 2024, Việt Nam đạt 128 thuê bao trên mỗi 100 dân.")
        hard, soft = story.opening_problems(s)
        self.assertTrue(any("hai câu liền nhau không có con số" in p for p in hard))
        self.assertTrue(any("câu đệm chung chung" in p for p in soft))
        self.assertTrue(any("lùi về quá khứ" in p for p in soft))

    def test_definition_in_the_first_seconds_is_blocked(self):
        s = self.script("Vốn FDI so với GDP của Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc.",
                        "Chỉ số này đo lường tỷ lệ vốn đầu tư trực tiếp nước ngoài.",
                        "Năm 2025, con số của Việt Nam là 4,1% GDP.")
        hard, _ = story.opening_problems(s)
        self.assertTrue(any("định nghĩa" in p for p in hard))

    def test_going_back_to_a_year_the_hook_names_is_proof_not_filler(self):
        s = self.script("Năm 2018 Việt Nam xếp chót bảng nhưng năm 2025 đã vượt Mỹ và Anh.",
                        "Quay lại năm 2018, tỷ lệ xe điện của Việt Nam gần như bằng 0%.",
                        "Năm 2025, con số đó đã là 40%.")
        self.assertEqual(story.opening_problems(s), ([], []))

    def test_ending_must_come_back_to_the_hook(self):
        good = self.script("Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc.", "a 1", "b 2",
                           "Gấp 5,06 lần — và khoảng cách vẫn đang nới rộng.")
        self.assertEqual(story.ending_problem(good), "")
        bad = self.script("Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc.", "a 1", "b 2",
                          "Một sự đảo chiều lịch sử từ mức âm vươn lên top đầu.")
        self.assertIn("câu kết", story.ending_problem(bad))
        words = self.script("Hàn Quốc sinh ít con nhất thế giới.", "a", "b",
                            "Hàn Quốc sinh ít con nhất — câu chuyện chưa có hồi kết.")
        self.assertEqual(story.ending_problem(words), "")

    def test_soft_rules_do_not_block_the_final_gate(self):
        from tests.test_stage1 import CFG, script
        s = script()
        s["scenes"][-1]["voice"] = " ".join(["từ"] * 14)        # câu kết không nhắc lại hook
        self.assertTrue(any("câu kết" in p for p in crew.script_problems(s, CFG)))
        self.assertEqual(crew.script_problems(s, CFG, include_soft=False), [])


class CauseTest(unittest.TestCase):
    TABLE = "Việt Nam theo năm: 1990: 0,2; 2025: 4,1.\nHàn Quốc theo năm: 1990: 0,3; 2025: 0,8."

    def test_invented_cause_in_a_data_script_is_caught(self):
        got = claims.cause_claims(["Sự mở cửa đã thu hút mạnh mẽ các dự án quốc tế lớn.",
                                   "Vì sao Việt Nam hút vốn FDI mạnh đến vậy?",          # câu hỏi: được
                                   "Năm 2025 Việt Nam đạt 4,1% GDP."], self.TABLE)
        self.assertEqual(len(got), 1)
        self.assertIn("mở cửa", got[0])

    def test_article_ideas_are_left_to_the_fact_checker(self):
        self.assertEqual(claims.cause_claims(["Nhờ chính sách mới, số ca giảm."], "Bài báo ScienceDaily."), [])


class DailyLongScriptTest(DailyCase):
    def test_scripts_written_for_the_old_length_go_last(self):
        from src import daily
        cfg = {"daily": {"videos_per_day": 1, "max_attempts": 2, "max_script_age_days": 3},
               "channel": {"video_seconds_max": 60}, "pacing": {"words_per_second": 3.4}}
        self.script(1, 30.0, words=300)            # khổ cũ 60-90 giây, điểm cao hơn
        self.script(2, 20.0, words=180)            # đúng khổ 45-60 giây
        got = daily.pick_candidates(self.con, cfg)
        self.assertEqual([x["id"] for x in got], [2, 1])
        self.assertEqual([x["long"] for x in got], [False, True])


class QcBoundsTest(unittest.TestCase):
    def test_duration_bounds_come_from_config(self):
        from src import qc
        lo, hi = qc.duration_bounds()
        self.assertLess(lo, 45)                       # Shorts 45-60 giây phải lọt sàn
        self.assertGreaterEqual(hi, 90)


if __name__ == "__main__":
    unittest.main()
