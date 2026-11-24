"""Bản đồ Hàn Quốc theo 17 시도 (kênh Hàn, 24/11/2026): hình học, nguồn KOSIS theo tỉnh, cảnh bản đồ."""
import unittest
from unittest import mock

from src import lang
from src.render import geo
from src.render.base import brand
from src.sources import datatable, kosis

CODES = ["KR-11", "KR-26", "KR-27", "KR-28", "KR-29", "KR-30", "KR-31", "KR-50", "KR-41", "KR-42", "KR-43",
         "KR-44", "KR-45", "KR-46", "KR-47", "KR-48", "KR-49"]
# tên KOSIS (cả tên cũ lẫn tên mới sau 2023) -> số giả lập
KOSIS_NAMES = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
               "세종특별자치시", "경기도", "강원도", "충청북도", "충청남도", "전라북도", "전라남도", "경상북도",
               "경상남도", "제주특별자치도"]


class GeometryTest(unittest.TestCase):
    def test_all_17_provinces_with_shapes(self):
        m = geo.load_map("kr")
        self.assertEqual(sorted(m["countries"]), sorted(CODES))
        for code, c in m["countries"].items():
            self.assertTrue(c["rings"], code)
        self.assertTrue(m["context"])                        # nền Triều Tiên

    def test_kosis_names_old_and_new_map_to_codes(self):
        for name, code in zip(KOSIS_NAMES, CODES):
            self.assertEqual(geo.code_of(name), code, name)
        self.assertEqual(geo.code_of("강원특별자치도"), "KR-42")
        self.assertEqual(geo.code_of("전북특별자치도"), "KR-45")
        self.assertEqual(geo.code_of("서울"), "KR-11")
        self.assertIsNone(geo.code_of("전국"))

    def test_region_for(self):
        self.assertEqual(geo.region_for(CODES), "kr")
        self.assertEqual(geo.region_for(["KOR", "JPN", "CHN"]), "asia")
        self.assertNotEqual(geo.region_for(CODES + ["JPN"]), "kr")

    def test_dokdo_belongs_to_gyeongbuk_and_inside_map(self):
        owner, spots, label, _ = geo.KR_DOKDO
        self.assertEqual(owner, "KR-47")
        lon0, lat0, lon1, lat1 = geo.load_map("kr")["bbox"]
        for lon, lat in spots + [label]:
            self.assertTrue(lon0 <= lon <= lon1 and lat0 <= lat <= lat1)


def _fake_kosis(values: dict, national: dict, years=(2015, 2020, 2024)):
    """table_meta + fetch_table giả: chiều vùng A gồm 전국 + 17 시도."""
    dims = {"ITEM": [("T1", "합계출산율"), ("T2", "모의 연령별출산율:15-19세")],
            "A": [("00", "전국")] + [(f"{i:02d}", n) for i, n in enumerate(KOSIS_NAMES, 1)]}

    def fetch(org, tbl, d, pick, start, end, item=None):
        assert item == "T1" and pick == {"A": "ALL"}
        rows = []
        for y in years:
            for code, name in d["A"]:
                v = national[y] if name == "전국" else values[name] * (1 + (2024 - y) * 0.02)
                rows.append({"C1": code, "C1_NM": name, "PRD_DE": str(y), "DT": f"{v:.3f}"})
        return rows
    return mock.patch.object(kosis, "table_meta", return_value=dims), mock.patch.object(kosis, "fetch_table", fetch)


TABLE = {"kind": "province_map", "org": "101", "tbl": "DT_X", "item": "합계출산율", "name": "합계출산율", "unit": "명"}
VALUES = dict(zip(KOSIS_NAMES, [0.58, 0.68, 0.75, 0.76, 0.71, 0.79, 0.94, 1.03, 0.82, 0.92, 0.95, 0.96, 0.82, 1.0,
                                 0.93, 0.87, 0.89]))
NATIONAL = {2015: 1.24, 2020: 0.84, 2024: 0.75}


class ProvinceSourceTest(unittest.TestCase):
    def build(self, t=TABLE):
        a, b = _fake_kosis(VALUES, NATIONAL)
        with lang.using("ko"), a, b:
            return kosis.build_province_map(dict(t))

    def test_summary_and_region_table(self):
        item = self.build()
        self.assertIn("한국 지도: 2024년 시도별 합계출산율 — 1위 세종, 최하위 서울", item["title"])
        s = item["summary"]
        self.assertIn("2024년 전국: 0.75명.", s)
        self.assertIn("1. 세종 — 1.03명", s)
        self.assertIn("17. 서울 — 0.58명", s)
        self.assertIn("세종은 서울의 1.78배", s)
        with lang.using("ko"):
            world = datatable.parse_world_table(s)
            self.assertEqual(world["year"], 2024)
            self.assertEqual(len(world["items"]), 18)          # 17 시도 + 전국
            self.assertNotIn("시도별 수치", datatable.before_world_table(s))

    def test_renamed_province_merged(self):
        with lang.using("ko"):
            named, nat = kosis._province_series({"강원도": [(2015, 1.0), (2020, 0.9)], "강원특별자치도": [(2024, 0.92)],
                                                 "전국": [(2024, 0.75)]})
        self.assertEqual(named["KR-42"], [(2015, 1.0), (2020, 0.9), (2024, 0.92)])
        self.assertEqual(nat, [(2024, 0.75)])

    def test_national_false_drops_country_line(self):
        item = self.build(dict(TABLE, national=False))
        self.assertNotIn("전국", item["summary"])

    def test_vietnamese_channel_skips(self):
        a, b = _fake_kosis(VALUES, NATIONAL)
        with a, b:
            self.assertIsNone(kosis.build_province_map(dict(TABLE)))

    def test_fill_map_scene_from_table(self):
        from src.crew import fill_series_from_data
        item = self.build()
        with lang.using("ko"):
            world = datatable.parse_world_table(item["summary"])
            spec = [{"template": "map", "params": {"title": "시도별 합계출산율", "unit": "명"}}]
            fill_series_from_data(spec, [], world)
        p = spec[0]["params"]
        self.assertEqual(p["region"], "kr")
        self.assertEqual(p["total"], 17)
        self.assertEqual(p["national"], 0.75)
        self.assertEqual({it["code"] for it in p["items"]}, set(CODES))
        self.assertEqual(next(it["rank"] for it in p["items"] if it["code"] == "KR-50"), 1)

    def test_produce_keeps_province_map(self):
        from src.produce import _check_scene
        items = [{"label": n.split("특별")[0], "value": v, "code": c} for n, v, c in zip(KOSIS_NAMES, VALUES.values(), CODES)]
        sc = _check_scene(0, {"template": "map", "params": {"title": "x", "items": items, "national": 0.75}})
        self.assertEqual(sc["params"]["region"], "kr")
        self.assertEqual(len(sc["params"]["items"]), 17)


class AbsorbStatementTest(unittest.TestCase):
    """Ca thật 24/11: bản đồ gánh một câu 5 cụm (3,2 giây), câu sau là cảnh chữ -> bản đồ nhận luôn câu đó."""

    def test_short_map_takes_next_statement(self):
        from src.crew import absorb_statements
        spec = [{"template": "big_number", "voice": "가 나 다", "seconds": 3},
                {"template": "map", "voice": "1명을 넘긴 지역은 전남과 세종뿐입니다.", "seconds": 3},
                {"template": "statement", "voice": "서울은 0.63명으로 최하위입니다.", "seconds": 3}]
        out = absorb_statements(spec, 1.1)
        self.assertEqual([s["template"] for s in out], ["big_number", "map"])
        self.assertEqual(out[1]["voice"], "1명을 넘긴 지역은 전남과 세종뿐입니다. 서울은 0.63명으로 최하위입니다.")

    def test_long_enough_or_shared_statement_untouched(self):
        from src.crew import absorb_statements
        long_map = [{"template": "map", "voice": " ".join(["말"] * 10), "seconds": 6},
                    {"template": "statement", "voice": "다른 문장", "seconds": 3}]
        self.assertEqual(len(absorb_statements(long_map, 1.1)), 2)
        shared = [{"template": "map", "voice": "짧은 문장", "seconds": 3},
                  {"template": "statement", "voice": "같은 문장 둘", "seconds": 2},
                  {"template": "versus", "voice": "같은 문장 둘", "seconds": 2}]
        self.assertEqual(len(absorb_statements(shared, 1.1)), 3)


class ShortRaceTest(unittest.TestCase):
    """Ca thật 24/11: cuộc đua 3 thanh chỉ 4 giây lời, không có cảnh chữ cạnh -> biểu đồ đường cùng số liệu."""
    RACE = {"template": "bar_race", "voice": "2018년 전국 수치는 처음 1명 아래로 하락했습니다.", "seconds": 4,
            "params": {"title": "추이", "unit": "명", "source": "KOSIS", "years": [2011, 2015, 2020, 2025],
                       "items": [{"label": "전남", "values": [1.57, 1.55, 1.15, 1.09]},
                                 {"label": "전국", "values": [1.24, 1.24, 0.84, 0.8]}]}}

    def test_short_race_becomes_line_chart(self):
        import copy
        from src.crew import short_race_to_line
        from src.produce import _check_scene
        spec = short_race_to_line([copy.deepcopy(self.RACE)], 1.1)
        sc = spec[0]
        self.assertEqual(sc["template"], "line_chart")
        self.assertEqual(sc["params"]["xs"], [2011, 2015, 2020, 2025])
        self.assertEqual([s["label"] for s in sc["params"]["series"]], ["전남", "전국"])
        self.assertEqual(sc["params"]["series"][1]["ys"], [1.24, 1.24, 0.84, 0.8])
        self.assertIsNotNone(_check_scene(0, sc))

    def test_long_race_kept(self):
        import copy
        from src.crew import short_race_to_line
        race = copy.deepcopy(self.RACE)
        race["voice"] = " ".join(["말"] * 10)
        self.assertEqual(short_race_to_line([race], 1.1)[0]["template"], "bar_race")


class ProvinceSceneTest(unittest.TestCase):
    def props(self, national=0.75):
        from src.render.web_map import map_props
        p = {"title": "t", "unit": "명", "year": 2024, "decimals": 2, "region": "kr",
             "items": [{"label": geo.display_name(c), "value": v} for c, v in zip(CODES, VALUES.values())]}
        if national is not None:
            p["national"] = national
        with lang.using("ko"):
            return map_props(p, brand()["colors"])

    def test_scene_props(self):
        out = self.props()
        self.assertEqual(out["region"], "kr")
        self.assertEqual(len(out["fills"]), 17)
        self.assertTrue(out["context"])
        texts = [l["text"] for l in out["islandLabels"]]
        self.assertIn("독도", texts)
        self.assertIn("동해", texts)
        gb = next(f["color"] for f in out["fills"] if f["code"] == "KR-47")
        self.assertEqual(out["islandColor"], gb)                # Dokdo cùng màu 경북
        self.assertEqual([r["label"] for r in out["panel"]], ["세종", "서울", "전국"])
        self.assertEqual([n["text"] for n in out["names"]], ["세종", "서울"])
        self.assertEqual(len(out["marks"]), 2)
        self.assertEqual(out["ranksShown"], [1, 17, 17, 17])
        for f in out["fills"]:                                  # mọi điểm nằm trong khung dọc
            nums = [float(x) for x in f["d"].replace("M", " ").replace("L", " ").replace("Z", " ").replace(",", " ").split()]
            self.assertTrue(all(0 <= x <= 1080 for x in nums[0::2]) and all(300 <= y <= 1030 for y in nums[1::2]))

    def test_no_national_row_without_value(self):
        self.assertEqual(len(self.props(None)["panel"]), 2)


if __name__ == "__main__":
    unittest.main()
