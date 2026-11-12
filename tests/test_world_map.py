"""Test bản đồ thế giới: file ranh giới, phép chiếu, công cụ dựng, ý tưởng "Việt Nam đứng thứ
mấy thế giới" từ World Bank, và đường đi của số liệu từ tóm tắt tới cảnh bản đồ. Không gọi mạng.

    python -m unittest discover -s tests -v
"""
import importlib.util
import logging
import unittest
from unittest import mock

from src import crew, produce, qc
from src.render import geo
from src.sources import datatable
from src.sources import worldbank as wb

from tests.test_map import ROOT, CFG

LE = {"code": "SP.DYN.LE00.IN", "name": "Tuổi thọ trung bình", "unit": "tuổi"}


def load_world_tool():
    spec = importlib.util.spec_from_file_location("build_world_map", ROOT / "tools" / "build_world_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_world(n: int = 120) -> tuple:
    """Bảng giả n nước: Việt Nam giữa bảng, Hàn Quốc gần đầu, kèm tên tiếng Việt."""
    names = {f"C{i:03d}": f"Nước số {i}" for i in range(n - 2)}
    names.update({"VNM": "Việt Nam", "KOR": "Hàn Quốc", "SGP": "Singapore", "THA": "Thái Lan",
                  "LAO": "Lào", "KHM": "Campuchia", "PHL": "Philippines"})
    table = {c: 50.0 + (i % 30) for i, c in enumerate(sorted(names))}     # tối đa 79 < Hàn Quốc
    table.update({"VNM": 74.7, "KOR": 83.6, "SGP": 83.3, "THA": 76.4, "LAO": 69.0,
                  "KHM": 70.8, "PHL": 69.8})
    return table, names


class WorldFileTest(unittest.TestCase):
    def test_world_file_has_the_countries_with_vietnamese_names(self):
        w = geo.load_map("world")
        self.assertEqual(w["projection"], "equal_earth")
        self.assertIn("Natural Earth", w["source"])                          # ghi rõ nguồn/giấy phép
        c = w["countries"]
        self.assertGreater(len(c), 200)
        for code, name in (("VNM", "Việt Nam"), ("KOR", "Hàn Quốc"), ("USA", "Mỹ"), ("NOR", "Na Uy"),
                           ("SGP", "Singapore"), ("TWN", "Đài Loan (Trung Quốc)")):
            self.assertEqual(c[code]["name"], name)
        self.assertNotIn("ATA", c)                                           # bỏ châu Nam Cực

    def test_borders_follow_vietnams_point_of_view(self):
        # Việt Nam không công nhận Kosovo, Somaliland, Bắc Síp -> nằm trong nước chủ quyền
        c = geo.load_map("world")["countries"]
        for code in ("KOS", "SOL", "CYN", "KAS"):
            self.assertNotIn(code, c)
        self.assertTrue(any(18 < lon < 22 and 42 < lat < 43.5 for r in c["SRB"]["rings"] for lon, lat in r))

    def test_every_name_leads_back_to_its_own_code(self):
        # bảng số trong tóm tắt ghi TÊN; bản đồ tô theo MÃ -> tên nào cũng phải tra ngược đúng
        for code, country in geo.load_map("world")["countries"].items():
            self.assertEqual(geo.code_of(country["name"]), code, country["name"])

    def test_no_country_is_painted_over_the_two_vietnamese_archipelagos(self):
        for code, country in geo.load_map("world")["countries"].items():
            for ring in country["rings"]:
                self.assertFalse(any(111.1 <= lon <= 112.8 and 15.7 <= lat <= 17.1 for lon, lat in ring), code)
                self.assertFalse(any(111.4 <= lon <= 116.0 and 7.6 <= lat <= 11.5 for lon, lat in ring), code)

    def test_zoom_box_shows_both_archipelagos_and_their_names(self):
        # bản đồ thế giới quá nhỏ để đọc tên hai quần đảo -> ô phóng to phải chứa trọn chúng
        lon0, lat0, lon1, lat1 = geo.INSET_BBOX
        for name, spots, (lab_lon, lab_lat), _ in geo.VN_ISLANDS:
            self.assertTrue(all(lon0 < lon < lon1 and lat0 < lat < lat1 for lon, lat in spots), name)
            self.assertTrue(lon0 < lab_lon < lon1 and lat0 < lab_lat < lat1, name)
        box = geo.country_box("VNM")
        self.assertTrue(lon0 < box[0] and box[2] < lon1 and lat0 < box[1] and box[3] < lat1)

    def test_region_is_asia_only_when_every_country_is_in_asia(self):
        self.assertEqual(geo.region_for(["VNM", "KOR", "JPN"]), "asia")
        self.assertEqual(geo.region_for(["VNM", "KOR", "DEU"]), "world")


class ProjectionTest(unittest.TestCase):
    def test_equal_earth_keeps_the_centre_and_is_symmetric(self):
        self.assertEqual(geo.equal_earth(0, 0), (0.0, 0.0))
        x, y = geo.equal_earth(100, 30)
        self.assertEqual(geo.equal_earth(-100, -30), (-x, -y))
        self.assertAlmostEqual(geo.equal_earth(180, 0)[0], 2.7064, places=3)  # giá trị chuẩn

    def test_world_projection_fits_the_box_north_up_east_right(self):
        w, h = geo.projected_size(8.6, 4.6, "world")
        self.assertAlmostEqual(w, 8.6, places=6)
        self.assertLessEqual(h, 4.6)
        to_xy = geo.projector(8.6, 4.6, (0.0, 1.85), "world")
        hanoi, seoul, paris = to_xy(105.8, 21.0), to_xy(127.0, 37.6), to_xy(2.35, 48.9)
        self.assertGreater(seoul[0], hanoi[0]); self.assertGreater(seoul[1], hanoi[1])
        self.assertLess(paris[0], hanoi[0])
        self.assertAlmostEqual(to_xy(0, 13)[0], 0.0, places=9)


class WorldToolTest(unittest.TestCase):
    def feature(self, adm, vn=None, iso=None, eh=None, ring=None, name_vi=None):
        ring = ring or [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        return {"properties": {"ADM0_A3": adm, "ADM0_A3_VN": vn or adm, "ISO_A3": iso or adm,
                               "ISO_A3_EH": eh or iso or adm, "NAME_VI": name_vi or adm, "NAME": adm},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    def test_merges_by_vietnam_view_uses_iso_codes_and_keeps_tiny_countries(self):
        tool = load_world_tool()
        tiny = [[103.8, 1.25], [104.0, 1.25], [104.0, 1.45], [103.8, 1.45], [103.8, 1.25]]
        out = tool.build({"features": [
            self.feature("SRB", ring=[[19, 42], [23, 42], [23, 46], [19, 46], [19, 42]], name_vi="Serbia"),
            self.feature("KOS", vn="SRB", iso="-99", eh="-99",
                         ring=[[20, 42], [21, 42], [21, 43], [20, 43], [20, 42]], name_vi="Kosovo"),
            self.feature("NOR", iso="-99", eh="NOR", name_vi="Na Uy"),
            self.feature("SDS", iso="SSD", name_vi="Nam Sudan"),
            self.feature("ATA", ring=[[0, -89], [10, -89], [10, -70], [0, -70], [0, -89]]),
            self.feature("SGP", ring=tiny, name_vi="Singapore"),
            self.feature("USA", name_vi="Hoa Kỳ")]})
        c = out["countries"]
        self.assertEqual(sorted(c), ["NOR", "SGP", "SRB", "SSD", "USA"])
        self.assertEqual(len(c["SRB"]["rings"]), 2)                          # Kosovo nằm trong Serbia
        self.assertEqual(c["USA"]["name"], "Mỹ")                             # tên quen thuộc thay "Hoa Kỳ"
        self.assertIn("Hoa Kỳ", c["USA"]["aliases"])
        self.assertTrue(c["SGP"]["rings"])                                   # nước nhỏ không biến mất


class WorldTableFormatTest(unittest.TestCase):
    def test_ranks_go_from_high_to_low_and_ties_share_a_place(self):
        self.assertEqual(datatable.ranks_desc({"a": 5, "b": 9, "c": 5, "d": 1}),
                         {"b": 1, "a": 2, "c": 2, "d": 4})

    def test_world_table_line_reads_back(self):
        named = {"Hồng Kông (Trung Quốc)": 85.44, "Việt Nam": 74.7, "Nam Sudan": -1.234, "Mỹ": 85321.4}
        line = datatable.world_table_line(2024, named)
        got = datatable.parse_world_table("Chỉ số: X.\n" + line)
        self.assertEqual(got["year"], 2024)
        self.assertEqual({i["label"]: i["value"] for i in got["items"]},
                         {"Hồng Kông (Trung Quốc)": 85.4, "Việt Nam": 74.7, "Nam Sudan": -1.23, "Mỹ": 85321})
        self.assertIsNone(datatable.parse_world_table("không có bảng"))


class BuildWorldItemTest(unittest.TestCase):
    def test_idea_tells_where_vietnam_stands_and_carries_the_full_table(self):
        table, names = fake_world()
        history = {"VNM": [(1990, 70.0), (1995, 71.0), (2024, 74.7)], "KOR": [(1990, 72.0), (2024, 83.6)]}
        item = wb.build_world_item(LE, 2024, table, names, ["VNM", "KOR"], history)
        rank = datatable.ranks_desc(table)
        s = item["summary"]
        self.assertIn(f"Việt Nam thứ {rank['VNM']}/{len(table)}", item["title"])
        self.assertIn(f"Việt Nam: 74,7 tuổi — cao thứ {rank['VNM']} trên {len(table)} nước", s)
        self.assertIn("1. Hàn Quốc — 83,6 tuổi", s)
        self.assertIn("Trong 6 nước Đông Nam Á có số liệu, Việt Nam đứng thứ 3; cao nhất là Singapore", s)
        self.assertIn("Hàn Quốc hơn Việt Nam 8,9 tuổi", s)                  # chênh ít: "hơn", không "gấp 1,12 lần"
        self.assertEqual([x["label"] for x in datatable.parse_series(s)], ["Việt Nam", "Hàn Quốc"])
        world = datatable.parse_world_table(s)
        self.assertEqual(len(world["items"]), len(table))
        self.assertTrue(item["url"].endswith("year=2024"))

    def test_gaps_between_two_percentages_are_percentage_points(self):
        table, names = fake_world()
        table.update({"VNM": 20.0, "KOR": 25.5})
        item = wb.build_world_item({"code": "X", "name": "Tỷ lệ", "unit": "%"}, 2024, table, names,
                                   ["VNM", "KOR"], {})
        self.assertIn("Hàn Quốc hơn Việt Nam 5,5 điểm phần trăm", item["summary"])

    def test_too_few_countries_or_no_vietnam_gives_no_idea(self):
        table, names = fake_world(50)
        self.assertIsNone(wb.build_world_item(LE, 2024, table, names, ["VNM", "KOR"], {}))
        table, names = fake_world()
        del table["VNM"]
        self.assertIsNone(wb.build_world_item(LE, 2024, table, names, ["VNM", "KOR"], {}))

    def test_year_is_the_latest_with_enough_countries_and_vietnam(self):
        by_year = {2022: {f"C{i}": 1 for i in range(200)} | {"VNM": 1},
                   2023: {f"C{i}": 1 for i in range(190)},                    # thiếu Việt Nam
                   2024: {f"C{i}": 1 for i in range(40)} | {"VNM": 1}}         # mới có 41 nước
        self.assertEqual(wb.pick_world_year(by_year), 2022)
        self.assertIsNone(wb.pick_world_year({}))

    def test_fetch_keeps_only_countries_on_the_map(self):
        rows = [{"countryiso3code": "VNM", "date": "2024", "value": 74.7},
                {"countryiso3code": "WLD", "date": "2024", "value": 73.3},     # "Thế giới": không phải nước
                {"countryiso3code": "KOR", "date": "2024", "value": None}]
        r = mock.Mock(); r.json.return_value = [{"page": 1}, rows]
        with mock.patch.object(wb.requests, "get", return_value=r):
            self.assertEqual(wb.fetch_world_table("SP.DYN.LE00.IN", {"VNM", "KOR"}), {2024: {"VNM": 74.7}})


class WorldSceneTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_territories_keep_their_official_vietnamese_names_on_charts(self):
        # ca thật kịch bản #7: model rút "Hồng Kông (Trung Quốc)" thành "Hồng Kông"
        spec = produce.validate_spec([
            {"template": "bar_chart", "params": {"title": "Top", "items": [
                {"label": "Monaco", "value": 86.5}, {"label": "Hồng Kông", "value": 85.4},
                {"label": "Đài Loan", "value": 81.0}]}},
            {"template": "versus", "params": {"title": "So", "left": {"label": "Ma Cao", "value": 1},
                                              "right": {"label": "Việt Nam", "value": 2}}}], CFG)
        self.assertEqual([i["label"] for i in spec[1]["params"]["items"]],
                         ["Monaco", "Hồng Kông (Trung Quốc)", "Đài Loan (Trung Quốc)"])
        self.assertEqual(spec[2]["params"]["left"]["label"], "Ma Cao (Trung Quốc)")
        self.assertEqual(spec[2]["params"]["right"]["label"], "Việt Nam")

    def test_map_scene_is_filled_from_the_world_table_with_ranks(self):
        named = {"Việt Nam": 74.7, "Hàn Quốc": 83.6, "Nhật Bản": 84.7, "Đức": 81.0, "Chad": 55.2,
                 "Na Uy": 83.6}
        world = datatable.parse_world_table(datatable.world_table_line(2024, named))
        spec = [{"template": "map", "params": {"title": "Tuổi thọ", "items": [{"label": "Việt Nam", "value": 1}]}}]
        self.assertEqual(crew.fill_series_from_data(spec, [], world), 1)
        spec = produce.validate_spec(spec, CFG)
        p = spec[1]["params"]
        self.assertEqual((p["region"], p["year"], p["total"]), ("world", 2024, 6))
        ranks = {i["code"]: i["rank"] for i in p["items"]}
        self.assertEqual((ranks["JPN"], ranks["KOR"], ranks["NOR"], ranks["VNM"]), (1, 2, 2, 5))
        allowed = qc.param_digits(p)                                         # "cao thứ 5/6" không bị coi là sai số
        self.assertTrue({"5", "6", "2024", "747"} <= allowed)


if __name__ == "__main__":
    unittest.main()
