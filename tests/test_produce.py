"""Test cửa kiểm spec của agent Sản xuất — không gọi LLM, không render.

    python -m unittest discover -s tests -v
"""
import logging
import unittest

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


class HighlightTest(unittest.TestCase):
    def test_numbers_and_acronyms_light_up(self):
        from src.render.templates import STATEMENT_STYLES, highlights
        self.assertEqual(STATEMENT_STYLES, produce.STATEMENT_STYLES)
        self.assertEqual(set(highlights("8.030 hệ thống AI ở Hàn Quốc, tăng 38,4% sau 5 năm")),
                         {"8.030", "AI", "38,4%", "5"})
        self.assertEqual(highlights("Không có lớp tường lửa nào"), [])


if __name__ == "__main__":
    unittest.main()
