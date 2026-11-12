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

    def test_chart_may_use_source_data_the_narration_does_not_read_out(self):
        spec = [self.scene("line_chart", (0,), title="Việt Nam", xs=[2000, 2010, 2025],
                           ys=[404, 1683, 5066]),
                self.scene("big_number", (1,), title="Hàn Quốc", value=36227),
                self.scene("statement", (2,), text="Con đường còn dài")]
        self.assertEqual(self.design(spec), spec)           # 404 và 1.683 chỉ có trong dữ liệu nguồn

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
