"""Test cửa kiểm spec của agent Sản xuất — không gọi LLM, không render.

    python -m unittest discover -s tests -v
"""
import logging
import unittest
from unittest import mock

from src import produce

CFG = {"pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4}}


def st(text):
    return {"template": "statement", "seconds": 3, "voice": text, "params": {"text": text}}


class ValidateSpecTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_intro_is_added_and_broken_scenes_are_dropped(self):
        spec = produce.validate_spec([
            st("a"), {"template": "pie_3d", "params": {}},
            {"template": "big_number", "params": {"title": "thiếu value"}},
            {"template": "line_chart", "params": {"title": "t", "xs": [1, 2], "ys": [1]}},
            {"template": "statement", "seconds": 99, "params": {"text": "b"}}], CFG)
        self.assertEqual([s["template"] for s in spec], ["intro", "statement", "statement"])
        self.assertEqual(spec[2]["seconds"], 4)                  # kẹp về nhịp 2-4 giây

    def test_statement_layouts_rotate_so_neighbours_differ(self):
        spec = produce.validate_spec([st("a"), st("b"), {
            "template": "big_number", "params": {"title": "t", "value": 5}}, st("c"), st("d")], CFG)
        styles = [(s["params"]["style"], s["params"]["n"]) for s in spec if s["template"] == "statement"]
        self.assertEqual(styles, [(0, 1), (1, 2), (2, 3), (0, 4)])

    def test_fractional_numbers_are_never_rounded_away(self):
        # LLM quên 'decimals' -> 38.4 hiện thành "38": hình sai số so với lời đọc
        spec = produce.validate_spec([
            {"template": "big_number", "params": {"title": "t", "value": 38.4}},
            {"template": "percent", "params": {"title": "t", "value": 60}},
            {"template": "versus", "params": {"title": "t", "decimals": 0,
                                              "left": {"label": "VN", "value": 29.3},
                                              "right": {"label": "KR", "value": 33.95}}},
            {"template": "big_number", "params": {"title": "t", "value": 1479, "decimals": 0}}], CFG)
        self.assertEqual([s["params"].get("decimals", 0) for s in spec[1:]], [1, 0, 2, 0])

    def test_two_country_line_chart_is_kept_and_bad_series_dropped(self):
        xs = [1960, 1990, 2024]
        spec = produce.validate_spec([
            {"template": "line_chart", "params": {"title": "Tỷ suất sinh", "xs": xs, "series": [
                {"label": "Việt Nam", "ys": [6.27, 3.6, 1.9]},
                {"label": "Hàn Quốc", "ys": [5.99, 1.57, 0.75]},
                {"label": "Thiếu điểm", "ys": [1, 2]}]}},
            {"template": "line_chart", "params": {"title": "Hỏng", "xs": xs,
                                                  "series": [{"label": "x", "ys": [1]}]}},
            {"template": "line_chart", "params": {"title": "Một mốc", "xs": [2024], "ys": [1]}}], CFG)
        self.assertEqual([s["params"]["title"] for s in spec[1:]], ["Tỷ suất sinh"])
        p = spec[1]["params"]
        self.assertEqual([s["label"] for s in p["series"]], ["Việt Nam", "Hàn Quốc"])
        self.assertEqual(p["decimals"], 2)                       # 0,75 không bị làm tròn thành "1"

    def test_chart_numbers_include_every_series(self):
        from src.utils import spec_values
        p = {"xs": [2000, 2024], "series": [{"label": "VN", "ys": [404, 5066]},
                                            {"label": "KR", "ys": [12710, 36227]}]}
        self.assertEqual(spec_values(p), [404, 5066, 12710, 36227])   # năm trên trục không tính
        self.assertEqual(sorted(spec_values({"left": {"value": 1}, "right": {"value": 2},
                                             "items": [{"value": 3}]})), [1, 2, 3])
        self.assertEqual(spec_values(None), [])

    def test_series_colours_follow_the_country_names(self):
        from src.render.templates import chart_series
        colors = {"accent": "#A", "vietnam": "#VN", "korea": "#KR", "good": "#G", "bad": "#B"}
        got = chart_series({"xs": [1, 2], "series": [
            {"label": "Việt Nam", "ys": [1, 1]}, {"label": "Hàn Quốc", "ys": [2, 2], "xs": [1, 3]},
            {"label": "Nhật Bản", "ys": [3, 3]}]}, colors)
        self.assertEqual([c for *_, c in got], ["#VN", "#KR", "#A"])
        self.assertEqual([xs for _, xs, _, _ in got], [[1, 2], [1, 3], [1, 2]])   # trục riêng nếu có
        two_unknown = chart_series({"xs": [1], "series": [{"label": "A", "ys": [1]},
                                                          {"label": "B", "ys": [2]}]}, colors)
        self.assertEqual([c for *_, c in two_unknown], ["#A", "#G"])     # hai đường không trùng màu
        self.assertEqual(chart_series({"xs": [5, 6], "ys": [1, 2]}, colors), [("", [5, 6], [1, 2], "#A")])

    def test_long_titles_wrap_into_two_balanced_lines(self):
        from src.render.base import wrap_title
        self.assertEqual(wrap_title("Mức rớt giá"), "Mức rớt giá")
        self.assertEqual(wrap_title("Điện tiêu thụ bình quân đầu người năm 1990"),
                         "Điện tiêu thụ bình quân\nđầu người năm 1990")
        self.assertEqual(wrap_title("Ca tử vong tập trung\nở vùng nhiệt đới"),
                         "Ca tử vong tập trung\nở vùng nhiệt đới")             # xuống dòng sẵn: giữ
        self.assertTrue(all(len(l) <= 24 for l in wrap_title("từ " * 30).split("\n")))

    def test_chart_end_labels_show_only_real_decimals(self):
        from src.render.templates import label_decimals
        self.assertEqual([label_decimals(v, d) for v, d in ((2756.0, 1), (98.9, 1), (0.75, 2),
                                                           (12071.0, 2), (4.9, 2), (5066, 0))],
                         [0, 1, 2, 0, 1, 0])

    def test_each_series_may_have_its_own_years(self):
        spec = produce.validate_spec([{"template": "line_chart", "params": {
            "title": "Điện", "xs": [1990, 2024, 2025], "series": [
                {"label": "Việt Nam", "xs": [1990, 2024], "ys": [98.9, 2756]},
                {"label": "Hàn Quốc", "xs": [1990, 2025], "ys": [2462, 12071]},
                {"label": "Sai", "xs": [1990, 2025], "ys": [1]}]}}], CFG)
        self.assertEqual([s["label"] for s in spec[1]["params"]["series"]], ["Việt Nam", "Hàn Quốc"])

    def test_percent_outside_0_100_becomes_a_big_number(self):
        spec = produce.validate_spec([
            {"template": "percent", "params": {"title": "Tăng", "value": 250}},
            {"template": "percent", "params": {"title": "Sai", "value": "nhiều"}}], CFG)
        self.assertEqual([s["template"] for s in spec[1:]], ["big_number", "big_number"])
        self.assertEqual(spec[1]["params"]["suffix"], "%")


class DesignScenesTest(unittest.TestCase):
    """crew.design_scenes: LLM được thay bằng danh sách câu trả lời soạn sẵn."""
    SCENES = [{"voice": "Năm 2025, GDP đầu người Việt Nam đạt 5.066 USD."},
              {"voice": "Hàn Quốc cùng năm là 36.227 USD."},
              {"voice": "Con đường phía trước vẫn còn rất dài và nhiều thử thách."}]
    IDEA = {"title": "GDP bình quân đầu người: Việt Nam và Hàn Quốc", "angle": "góc",
            "summary": "Việt Nam theo năm: 2000: 404; 2010: 1.683; 2025: 5.066.\n"
                       "Hàn Quốc theo năm: 2000: 12.710; 2025: 36.227."}
    CFG = {"channel": {"name": "Thế giới qua con số"},
           "pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4, "words_per_second": 3.4}}

    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def design(self, *answers):
        import json as _json
        from src import crew
        queue, self.prompts = [a if isinstance(a, str) else _json.dumps(a) for a in answers], []

        def fake(role, goal, description, expected_output):
            self.prompts.append(description)
            return queue.pop(0)
        with mock.patch.object(crew, "_run_single_task", fake):
            return crew.design_scenes(dict(self.IDEA), self.SCENES, self.CFG)

    def scene(self, template, voice_idx, **params):
        voice = " ".join(self.SCENES[i]["voice"] for i in voice_idx)
        return {"template": template, "seconds": 4, "voice": voice, "params": params}

    def test_two_sentences_merged_into_one_versus_scene_are_accepted(self):
        # Trước đây gộp làm tổng "seconds" tụt -> bị trả lại -> model toàn tách thành big_number
        spec = [self.scene("versus", (0, 1), title="GDP đầu người 2025",
                           left={"label": "Việt Nam", "value": 5066},
                           right={"label": "Hàn Quốc", "value": 36227}),
                self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design(spec), spec)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("DỮ LIỆU NGUỒN", self.prompts[0])

    def test_line_chart_numbers_come_from_the_table_not_from_the_model(self):
        # Ca thật (kịch bản #17): model tự chế 11.500 / 11.800 kWh cho Hàn Quốc ba lần liền
        made_up = [self.scene("line_chart", (0, 1), title="GDP đầu người", xs=[2000, 2025], series=[
                       {"label": "Việt Nam", "ys": [404, 5066]}, {"label": "Hàn Quốc", "ys": [9999, 36227]}]),
                   self.scene("statement", (2,), text="Con đường còn dài")]
        got = self.design(made_up)
        self.assertEqual(len(self.prompts), 1)                   # không còn gì để trả lại
        self.assertIn("máy tự điền đúng xs/ys từ bảng", self.prompts[0])
        p = got[0]["params"]
        self.assertEqual(p["series"], [{"label": "Việt Nam", "xs": [2000, 2010, 2025], "ys": [404, 1683, 5066]},
                                       {"label": "Hàn Quốc", "xs": [2000, 2025], "ys": [12710, 36227]}])
        self.assertEqual(p["xs"], [2000, 2010, 2025])
        only_vn = self.design([self.scene("line_chart", (0,), title="Việt Nam", series=[{"label": "việt nam"}]),
                               self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                               self.scene("statement", (2,), text="Con đường còn dài")])
        self.assertEqual([s["label"] for s in only_vn[0]["params"]["series"]], ["Việt Nam"])

    def test_chart_may_use_numbers_from_an_article_summary(self):
        # Ý tưởng từ bài báo (không có bảng theo năm): model được dùng số trong tóm tắt
        self.IDEA = dict(self.IDEA, summary="GDP đầu người năm 2000 là 404 USD, năm 2010 là 1.683 USD.")
        spec = [self.scene("line_chart", (0,), title="Việt Nam", xs=[2000, 2010, 2025],
                           ys=[404, 1683, 5066]),
                self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design(spec), spec)
        fake = [dict(spec[0], params=dict(spec[0]["params"], ys=[404, 9999, 5066])), spec[1], spec[2]]
        self.assertEqual(self.design(fake, fake, fake)[0]["template"], "statement")

    def test_same_value_written_differently_is_not_called_fabricated(self):
        # Ca thật: nguồn ghi "4,90 lần", spec ghi 4.9 -> từng bị coi là bịa số
        self.SCENES = [dict(s) for s in self.SCENES]
        self.SCENES[1] = {"voice": "Hàn Quốc tăng gấp 4,90 lần, lên 36.227 USD."}
        spec = [self.scene("big_number", (0,), title="Việt Nam", value=5066),
                self.scene("big_number", (1,), title="Hàn Quốc tăng", value=4.9),
                self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design(spec), spec)

    def test_race_scene_gets_every_country_from_the_table(self):
        self.IDEA = dict(self.IDEA, summary=(
            "Hàn Quốc theo năm: 1990: 6.813; 1995: 13.002; 2025: 36.227.\n"
            "Nhật Bản theo năm: 1990: 26.345; 1995: 44.000; 2025: 35.951.\n"
            "Việt Nam theo năm: 1990: 98,8; 1993: 150; 1995: 288; 2025: 5.066."))
        long = " ".join(s["voice"] for s in self.SCENES[:2])     # cuộc đua gánh 2 câu: được phép
        spec = [{"template": "bar_race", "seconds": 9, "voice": long,
                 "params": {"title": "Cuộc đua GDP", "unit": "USD", "source": "World Bank"}},
                self.scene("statement", (2,), text="Con đường còn dài")]
        got = self.design(spec)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn('ĐÚNG MỘT cảnh "bar_race"', self.prompts[0])
        p = got[0]["params"]
        self.assertEqual(p["years"], [1990, 1995, 2025])             # năm 1993 chỉ một nước có
        self.assertEqual(p["items"][2], {"label": "Việt Nam", "values": [98.8, 288.0, 5066.0]})
        spec2 = produce.validate_spec(got, {"pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4}})
        self.assertEqual(spec2[1]["template"], "bar_race")
        self.assertEqual(spec2[1]["params"]["decimals"], 1)          # 98,8 không bị làm tròn

    def test_race_needs_three_countries_with_full_data(self):
        bad = {"template": "bar_race", "params": {"title": "t", "years": [1990, 2000], "items": [
            {"label": "A", "values": [1, 2]}, {"label": "B", "values": [3, 4]}, {"label": "C", "values": [5]}]}}
        self.assertEqual(len(produce.validate_spec([bad], CFG)), 1)   # chỉ còn intro

    def test_one_picture_carrying_too_much_narration_is_sent_back(self):
        from src import crew
        long = "Vào năm 1990 điện tiêu thụ của Việt Nam chỉ là 98,9 kWh " * 3          # 39 từ
        spec = [{"template": "versus", "voice": long}, {"template": "statement", "voice": "ngắn"}]
        self.assertEqual(crew.static_scenes(spec, 27), ["cảnh 1 (versus) mang 39 từ cho 1 hình"])
        split = [{"template": "versus", "voice": long}, {"template": "big_number", "voice": long}]
        self.assertEqual(crew.static_scenes(split, 27), [])        # hai hình chia nhau một câu dài
        self.SCENES = [{"voice": long.strip()}] + self.SCENES[1:]
        one = [self.scene("statement", (0,), text="1990"), self.scene("big_number", (1,), title="KR",
                                                                       value=36227),
               self.scene("statement", (2,), text="Con đường còn dài")]
        two = [self.scene("statement", (0,), text="Năm 1990"), self.scene("statement", (0,), text="Việt Nam")] \
            + one[1:]
        self.assertEqual(self.design(one, two), two)
        self.assertIn("cảnh đứng yên quá lâu", self.prompts[1])

    def test_dropping_a_sentence_is_sent_back(self):
        short = [self.scene("big_number", (0,), title="Việt Nam", value=5066)]
        full = short + [self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                        self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design(short, full), full)
        self.assertIn("KHÔNG được bỏ câu nào", self.prompts[1])

    def test_invented_number_scene_becomes_text_and_keeps_its_narration(self):
        fake = [self.scene("big_number", (0,), title="Việt Nam tăng trưởng", value=777),
                self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                self.scene("statement", (2,), text="Con đường còn dài")]
        got = self.design(fake, fake, fake)                  # 3 lần vẫn bịa 777
        self.assertEqual([s["template"] for s in got], ["statement", "big_number", "statement"])
        self.assertEqual(got[0]["voice"], self.SCENES[0]["voice"])        # lời đọc KHÔNG bị cắt mất
        self.assertEqual(got[0]["params"]["text"], "Việt Nam tăng trưởng")

    def test_junk_answers_do_not_crash_and_best_attempt_is_kept(self):
        good = [self.scene("big_number", (0,), title="Việt Nam", value=5066),
                self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design("Xin lỗi, tôi không làm được.", {"scenes": good}), good)
        self.assertEqual(self.design("không", '"vẫn không"', "[1, 2]"), [])


class HighlightTest(unittest.TestCase):
    def test_numbers_and_acronyms_light_up(self):
        from src.render.templates import STATEMENT_STYLES, highlights
        self.assertEqual(STATEMENT_STYLES, produce.STATEMENT_STYLES)
        self.assertEqual(set(highlights("8.030 hệ thống AI ở Hàn Quốc, tăng 38,4% sau 5 năm")),
                         {"8.030", "AI", "38,4%", "5"})
        self.assertEqual(highlights("Không có lớp tường lửa nào"), [])


if __name__ == "__main__":
    unittest.main()
