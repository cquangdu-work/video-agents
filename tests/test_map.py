"""Test mẫu bản đồ châu Á — không render, không gọi mạng.

    python -m unittest discover -s tests -v
"""
import importlib.util
import logging
import unittest
from pathlib import Path

from src import crew, produce, qc
from src.render import geo

ROOT = Path(__file__).resolve().parent.parent
CFG = {"pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4}}


def load_tool():
    spec = importlib.util.spec_from_file_location("build_asia_map", ROOT / "tools" / "build_asia_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GeoTest(unittest.TestCase):
    def test_map_file_has_the_race_countries(self):
        countries = geo.load_map()["countries"]
        for code in ("VNM", "KOR", "JPN", "CHN", "THA", "MYS", "IDN", "PHL", "IND", "SGP"):
            self.assertIn(code, countries)
        self.assertIn("Natural Earth", geo.load_map()["source"])          # ghi rõ nguồn/giấy phép

    def test_vietnamese_names_map_to_codes(self):
        self.assertEqual(geo.code_of("Việt Nam"), "VNM")
        self.assertEqual(geo.code_of(" hàn quốc "), "KOR")
        self.assertIsNone(geo.code_of("Đức"))

    def test_projection_fits_the_box_and_keeps_north_up(self):
        to_xy = geo.projector(8.4, 6.6, (0.0, 0.3))
        lon0, lat0, lon1, lat1 = geo.load_map()["bbox"]
        x0, y0, _ = to_xy(lon0, lat0)
        x1, y1, _ = to_xy(lon1, lat1)
        self.assertLessEqual(x1 - x0, 8.4 + 1e-9)
        self.assertLessEqual(y1 - y0, 6.6 + 1e-9)
        self.assertGreater(y1, y0)                                         # bắc ở trên
        hanoi, hcm = to_xy(105.8, 21.0), to_xy(106.7, 10.8)
        self.assertGreater(hanoi[1], hcm[1])
        box = geo.country_box("VNM")
        self.assertTrue(102 < box[0] < 104 and 109 < box[2] < 110 and 8 < box[1] < 9)

    def test_vietnam_islands_are_always_drawn_in_the_right_place(self):
        # Bản đồ có Việt Nam mà thiếu Hoàng Sa, Trường Sa là sai luật Việt Nam — đừng xoá
        names = {name for name, *_ in geo.VN_ISLANDS}
        self.assertEqual(names, {"Hoàng Sa", "Trường Sa"})
        where = {"Hoàng Sa": (110.5, 15.5, 113.0, 17.2), "Trường Sa": (111.5, 6.5, 117.0, 11.6)}
        for name, spots, *_ in geo.VN_ISLANDS:
            a, b, c, d = where[name]
            self.assertTrue(all(a <= lon <= c and b <= lat <= d for lon, lat in spots), name)
        # Natural Earth 1:50m không có đa giác nào ở đó -> không nước nào bị tô màu lên hai quần đảo
        for code, country in geo.load_map()["countries"].items():
            for ring in country["rings"]:
                self.assertFalse(any(111.1 <= lon <= 112.8 and 15.7 <= lat <= 17.1 for lon, lat in ring), code)
                self.assertFalse(any(111.4 <= lon <= 116.0 and 7.6 <= lat <= 11.5 for lon, lat in ring), code)

    def test_label_spots_are_inside_the_map(self):
        lon0, lat0, lon1, lat1 = geo.load_map()["bbox"]
        for lon, lat in geo.LABEL_AT.values():
            self.assertTrue(lon0 < lon < lon1 and lat0 < lat < lat1)


class MapToolTest(unittest.TestCase):
    def test_rectangle_clipping(self):
        tool = load_tool()
        square = [[0, 0], [10, 0], [10, 10], [0, 10]]
        got = tool.clip_ring(square, (5, -1, 20, 20))
        self.assertEqual(sorted(map(tuple, got)), [(5, 0), (5, 10), (10, 0), (10, 10)])
        self.assertEqual(tool.clip_ring(square, (50, 50, 60, 60)), [])

    def test_simplify_keeps_closed_rings(self):
        # Lỗi thật khi viết công cụ: vòng khép kín (đầu = cuối) bị giảm còn 2 điểm, cả bản đồ rỗng
        tool = load_tool()
        ring = [[0, 0], [5, 0.01], [10, 0], [10, 10], [0, 10], [0, 0]]
        got = tool.simplify(ring, 0.05)
        self.assertGreaterEqual(len(got), 5)
        self.assertNotIn([5, 0.01], got)                                    # điểm gần thẳng hàng bị bỏ


class MapSpecTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_map_keeps_known_asian_countries_and_needs_three(self):
        spec = produce.validate_spec([
            {"template": "map", "params": {"title": "GDP", "items": [
                {"label": "Việt Nam", "value": 5066}, {"label": "Hàn Quốc", "value": "36227"},
                {"label": "Đức", "value": 54000}, {"label": "Ấn Độ", "value": 2702.5}]}},
            {"template": "map", "params": {"title": "Ít", "items": [
                {"label": "Việt Nam", "value": 1}, {"label": "Lào", "value": 2}]}}], CFG)
        self.assertEqual([s["template"] for s in spec], ["intro", "map"])
        p = spec[1]["params"]
        self.assertEqual([i["label"] for i in p["items"]], ["Việt Nam", "Hàn Quốc", "Ấn Độ"])
        self.assertEqual(p["decimals"], 1)                                   # 2.702,5 không bị làm tròn

    def test_map_is_filled_with_the_latest_common_year(self):
        data = [{"label": "Việt Nam", "xs": [1990, 2024], "ys": [98.9, 2756]},
                {"label": "Hàn Quốc", "xs": [1990, 2024, 2025], "ys": [2462, 12235, 12071]},
                {"label": "Ấn Độ", "xs": [1990, 2024], "ys": [271, 1223]}]
        spec = [{"template": "map", "params": {"title": "Điện", "items": [{"label": "Việt Nam", "value": 1}]}}]
        self.assertEqual(crew.fill_series_from_data(spec, data), 1)
        p = spec[0]["params"]
        self.assertEqual(p["year"], 2024)
        self.assertEqual(p["items"], [{"label": "Việt Nam", "value": 2756}, {"label": "Hàn Quốc", "value": 12235},
                                      {"label": "Ấn Độ", "value": 1223}])

    def test_map_year_on_screen_is_not_a_number_error(self):
        allowed = qc.param_digits({"year": 2024, "items": [{"label": "Việt Nam", "value": 2756}]})
        self.assertTrue({"2024", "2756"} <= allowed)


if __name__ == "__main__":
    unittest.main()
