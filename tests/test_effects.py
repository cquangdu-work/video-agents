"""Nâng cấp hiệu ứng 24/11/2026 (Du: "hình ảnh phải đẹp ngay cả khi tắt âm thanh; chuyển động phải giúp hiểu số liệu;
mỗi video phải có một phát hiện đáng nhớ"): thẻ phát hiện, ngoặc đo khoảng cách, nhãn vượt trong cuộc đua. Mọi số
trên hình đều tính từ số liệu đã có — không số mới."""
import unittest

from src import lang
from src.render import web, web_map


class FindingTest(unittest.TestCase):
    def test_value_prefers_number_with_unit_and_skips_years(self):
        with lang.using("vi"):
            f = web.finding_of([{"voice": "Năm 2025, vốn FDI của Việt Nam gấp 5,06 lần Hàn Quốc."}, {"voice": "x"}], 50)
        self.assertEqual(f["value"], "5,06 lần")
        self.assertEqual(f["text"], "Năm 2025, vốn FDI của Việt Nam gấp 5,06 lần Hàn Quốc.")
        self.assertAlmostEqual(f["end"], 50)
        self.assertTrue(46 <= f["start"] < 48)

    def test_years_only_still_gets_a_card_without_big_number(self):
        with lang.using("vi"):
            f = web.finding_of([{"voice": "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991."}], 45)
        self.assertEqual(f["value"], "")

    def test_korean(self):
        with lang.using("ko"):
            f = web.finding_of([{"voice": "한국 중위연령 44.5세, 228개국 중 19위입니다."}], 40)
        self.assertEqual((f["value"], f["label"]), ("44.5세", "핵심 한 줄"))


class GapTest(unittest.TestCase):
    S = [{"label": "Việt Nam", "xs": [2000, 2024], "ys": [10.0, 40.0], "emphasis": True},
         {"label": "Hàn Quốc", "xs": [2000, 2024], "ys": [20.0, 8.0], "emphasis": False}]

    def test_ratio_and_percentage_points(self):
        with lang.using("vi"):
            g = web.gap_of(self.S, "kWh")
            self.assertEqual((g["value"], g["label"]), ("×5", "Việt Nam gấp 5 lần Hàn Quốc"))
            g = web.gap_of(self.S, "% dân số")
            self.assertEqual(g["label"], "Việt Nam hơn Hàn Quốc 32 điểm %")

    def test_no_gap_when_tiny_absurd_or_years_differ(self):
        with lang.using("vi"):
            near = [dict(self.S[0], ys=[1, 10]), dict(self.S[1], ys=[1, 9.5])]
            self.assertIsNone(web.gap_of(near, "kWh"))                       # gấp 1,05 lần: không đáng kể
            huge = [dict(self.S[0], ys=[1, 5000]), dict(self.S[1], ys=[1, 2])]
            self.assertIsNone(web.gap_of(huge, "USD"))                      # > 1.000 lần: tỷ số vô nghĩa
            other = [self.S[0], dict(self.S[1], xs=[2000, 2020])]
            self.assertIsNone(web.gap_of(other, "kWh"))


class OvertakeTest(unittest.TestCase):
    def test_anchor_passing_others_is_reported_per_leg(self):
        items = [{"label": "Nhật Bản", "values": [50, 50, 30], "strong": True},
                 {"label": "Việt Nam", "values": [10, 40, 60], "strong": True},
                 {"label": "Thái Lan", "values": [30, 20, 10], "strong": False}]
        with lang.using("vi"):
            ev = web_map.overtakes(items)
        self.assertEqual(ev, [{"leg": 0, "item": 1, "passed": ["Thái Lan"]},
                              {"leg": 1, "item": 1, "passed": ["Nhật Bản"]}])

    def test_no_anchor_no_events(self):
        self.assertEqual(web_map.overtakes([{"label": "A", "values": [1, 2], "strong": False}]), [])


class OpeningCardTest(unittest.TestCase):
    """Thẻ mở đầu (núm "opening" của src/style.py, 24/11/2026): chỉ có khi video có phát hiện; không dài quá 60% cảnh đầu;
    thẻ cuối có dòng mời theo dõi."""

    def spec(self):
        return [{"template": "statement", "seconds": 3.0, "voice": "Việt Nam gấp 5,06 lần Hàn Quốc.",
                 "params": {"text": "Việt Nam gấp 5,06 lần Hàn Quốc."}},
                {"template": "statement", "seconds": 7.0, "voice": "Câu kết.", "params": {"text": "Câu kết."}}]

    def build(self, opening):
        with lang.using("vi"):
            return web.build_story(self.spec(), [], "t", opening=opening)

    def test_opening_capped_by_first_scene_and_cta_present(self):
        p = self.build(2.4)
        self.assertEqual(p["opening"], 1.8)                                  # 60% của cảnh đầu 3 giây
        self.assertIn("Theo dõi", p["finding"]["cta"])
        self.assertNotIn("opening", self.build(0))
        self.assertNotIn("opening", self.build(None))

    def test_style_knob_window(self):
        from src import style
        self.assertEqual(style.arms("opening", {}), [0.0, 1.2, 2.4])
        self.assertEqual(style.fmt("opening", 1.2), "1,2 giây")
