"""Test cổng soát câu so sánh bằng code (src/claims.py) — không gọi mạng, không gọi LLM.

    python -m unittest tests.test_claims -v
"""
import unittest

from src import claims

# Tóm tắt THẬT của ý tưởng kịch bản #46 (World Bank, 19/11/2026) — bản có câu hook sai
WOMEN = """Chỉ số: Tỷ lệ phụ nữ tham gia lực lượng lao động (%). Nguồn: World Bank Open Data, mã SL.TLF.CACT.FE.ZS.
Việt Nam: năm 1990 là 74,7 %; năm 2025 là 68,6 %.
Hàn Quốc: năm 1990 là 47,2 %; năm 2025 là 56,8 %.
Từ 1990 đến 2025, Việt Nam giảm 6,1 điểm phần trăm.
Từ 1990 đến 2025, Hàn Quốc tăng 9,6 điểm phần trăm.
Số mới nhất: Việt Nam hơn Hàn Quốc 11,8 điểm phần trăm.
Việt Nam theo năm: 1990: 74,7; 1995: 73,8; 2000: 70; 2005: 70,4; 2010: 71,7; 2015: 72,9; 2020: 69,1; 2025: 68,6.
Hàn Quốc theo năm: 1990: 47,2; 1995: 48,4; 2000: 49,4; 2005: 50,7; 2010: 49,8; 2015: 52,4; 2020: 53,1; 2025: 56,8."""

GDP = """Chỉ số: GDP bình quân đầu người (USD). Nguồn: World Bank Open Data, mã NY.GDP.PCAP.CD.
Số mới nhất: Hàn Quốc gấp 7,15 lần Việt Nam.
Việt Nam năm 2025 (5.066 USD) tương đương Hàn Quốc năm 1988 (4.889 USD) — cách nhau 37 năm.
Việt Nam theo năm: 1985: 239; 1990: 98,8; 2000: 404; 2010: 1.683; 2020: 3.534; 2025: 5.066.
Hàn Quốc theo năm: 1960: 159; 1980: 1.746; 1990: 6.813; 2000: 12.710; 2020: 33.646; 2025: 36.227."""


class CatchUpTest(unittest.TestCase):
    def test_the_real_false_hook_of_script_46_is_caught(self):
        got = claims.comparison_problems(
            ["Hàn Quốc năm 2025 mới đạt tỷ lệ phụ nữ đi làm mà Việt Nam đã có từ năm 1990."], WOMEN)
        self.assertEqual(len(got), 1)
        self.assertIn("SAI", got[0])
        self.assertIn("Hàn Quốc năm 2025 là 56,8", got[0])
        self.assertIn("Việt Nam năm 1990 là 74,7", got[0])

    def test_a_precomputed_catch_up_is_accepted_in_every_word_order(self):
        ok = ["Việt Nam năm 2025 mới bằng Hàn Quốc năm 1988.",
              "Năm 2025, Việt Nam mới bằng Hàn Quốc năm 1988.",
              "Hàn Quốc đã đạt từ năm 1988 mức mà Việt Nam năm 2025 mới chạm tới."]
        self.assertEqual(claims.comparison_problems(ok, GDP), [])

    def test_catch_up_backed_by_the_table_itself_is_accepted(self):
        # Hàn Quốc 2005 (50,7) và Nhật Bản 1990 (50,1) lệch 1,2%: không cần dòng "tương đương"
        table = WOMEN + "\nNhật Bản theo năm: 1990: 50,1; 2025: 55."
        self.assertEqual(claims.comparison_problems(
            ["Hàn Quốc năm 2005 mới bằng Nhật Bản năm 1990."], table), [])
        self.assertEqual(claims.comparison_problems(                       # cùng năm: không phải mốc thời gian
            ["Nhật Bản năm 2025 mới bằng Hàn Quốc năm 2025."], table), [])

    def test_catch_up_that_the_table_cannot_back_is_rejected(self):
        got = claims.comparison_problems(["Việt Nam năm 2025 mới bằng Hàn Quốc năm 1987."], GDP)
        self.assertEqual(len(got), 1)
        self.assertIn("không có căn cứ", got[0])

    def test_today_means_the_latest_year_in_the_table(self):
        # Ca thật #37 (19/11): "hôm nay" thay cho năm — Việt Nam 2025: 38,8%, Hàn Quốc 1990: 74%
        urban = ("Việt Nam theo năm: 1990: 19,2; 2010: 30,3; 2025: 38,8.\n"
                 "Hàn Quốc theo năm: 1990: 74; 2010: 82; 2025: 81,2.")
        got = claims.comparison_problems(
            ["Việt Nam hôm nay mới bằng Hàn Quốc năm 1990 về đô thị hóa."], urban)
        self.assertEqual(len(got), 1)
        self.assertIn("Việt Nam năm 2025 là 38,8", got[0])
        self.assertEqual(claims.comparison_problems(                       # có dòng "tương đương": đúng
            ["Việt Nam hôm nay mới bằng Hàn Quốc năm 1988."], GDP), [])
        self.assertEqual(claims.comparison_problems(["Hiện nay, Việt Nam cao hơn Hàn Quốc."], WOMEN), [])
        self.assertEqual(len(claims.comparison_problems(["Hiện nay, Việt Nam thấp hơn Hàn Quốc."], WOMEN)), 1)

    def test_negated_and_compound_sentences_are_left_alone(self):
        texts = ["Hàn Quốc năm 2025 vẫn chưa bằng Việt Nam năm 1990.",
                 "Năm 1990, Việt Nam có tỷ lệ gần bằng 75%, còn Hàn Quốc năm 2025 là 56,8%."]
        self.assertEqual(claims.comparison_problems(texts, WOMEN), [])


class DirectionTest(unittest.TestCase):
    def test_true_comparison_in_one_year_passes(self):
        self.assertEqual(claims.comparison_problems(
            ["Vì sao tỷ lệ phụ nữ làm việc ở Việt Nam năm 1990 cao hơn Hàn Quốc nhiều đến vậy?"], WOMEN), [])

    def test_reversed_comparison_in_one_year_is_caught(self):
        got = claims.comparison_problems(["Năm 1990, tỷ lệ của Việt Nam thấp hơn Hàn Quốc."], WOMEN)
        self.assertEqual(len(got), 1)
        self.assertIn("ngược chiều", got[0])

    def test_talk_about_growth_is_not_a_level_comparison(self):
        self.assertEqual(claims.comparison_problems(
            ["Năm 2025, Hàn Quốc tăng nhanh hơn Việt Nam."], WOMEN), [])

    def test_year_missing_from_table_is_not_judged(self):
        self.assertEqual(claims.comparison_problems(["Năm 1993, Việt Nam thấp hơn Hàn Quốc."], WOMEN), [])


class TimesTest(unittest.TestCase):
    def test_inverted_ratio_is_caught(self):
        got = claims.comparison_problems(["GDP đầu người Việt Nam gấp 7,15 lần Hàn Quốc."], GDP)
        self.assertEqual(len(got), 1)
        self.assertIn("đảo chiều", got[0])
        self.assertEqual(claims.comparison_problems(["Hàn Quốc gấp 7,15 lần Việt Nam."], GDP), [])

    def test_ratio_checked_against_the_table_year(self):
        got = claims.comparison_problems(["Năm 2025, Việt Nam gấp 7,15 lần Hàn Quốc về GDP đầu người."],
                                         GDP.replace("Số mới nhất: Hàn Quốc gấp 7,15 lần Việt Nam.\n", ""))
        self.assertEqual(len(got), 1)


class ScopeTest(unittest.TestCase):
    def test_article_ideas_have_no_table_and_pass_through(self):
        self.assertEqual(claims.comparison_problems(
            ["Hàn Quốc năm 2025 mới bằng Việt Nam năm 1990."], "Bài báo ScienceDaily, không có bảng."), [])

    def test_world_table_counts_as_data(self):
        summary = ("Chỉ số: Lượng rượu bia (lít). Năm 2020: có số của 3 nước.\n"
                   "Số liệu từng nước năm 2020 (máy dùng để tô bản đồ): Lào 10,8; Thái Lan 8,3; Việt Nam 8,04.")
        self.assertEqual(claims.comparison_problems(["Năm 2020, Việt Nam thấp hơn Lào."], summary), [])
        self.assertEqual(len(claims.comparison_problems(["Năm 2020, Việt Nam cao hơn Lào."], summary)), 1)

    def test_lowercase_world_and_single_word_names(self):
        summary = WOMEN + "\nThế giới theo năm: 1990: 50,2; 2025: 48,7."
        got = claims.comparison_problems(["Năm 2025, Việt Nam thấp hơn mức của thế giới."], summary)
        self.assertEqual(len(got), 1)
        table = claims.data_table("Ý theo năm: 2000: 1; 2020: 2.\nViệt Nam theo năm: 2000: 3; 2020: 4.")
        self.assertEqual([m[2] for m in claims._mentions("Ý nghĩa là Việt Nam đứng đầu", table)],
                         ["Ý", "Việt Nam"])
        self.assertEqual([m[2] for m in claims._mentions("ý nghĩa là Việt Nam đứng đầu", table)],
                         ["Việt Nam"])

    def test_whole_script(self):
        script = {"scenes": [{"voice": "Hàn Quốc năm 2025 mới đạt tỷ lệ phụ nữ đi làm mà Việt Nam đã có từ năm 1990."},
                             {"voice": "Năm 1990, Việt Nam đứng ở mức 74,7%."}, "rác"]}
        self.assertEqual(len(claims.script_comparison_problems(script, WOMEN)), 1)


if __name__ == "__main__":
    unittest.main()
