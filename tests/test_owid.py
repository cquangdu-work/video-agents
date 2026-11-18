"""Test nguồn ý tưởng Our World in Data (src/sources/owid.py) và việc giữ cân bằng mảng chủ đề.
Không gọi mạng: bảng OWID là bảng giả {(mã, năm): giá trị}.

    python -m unittest discover -s tests -v
"""
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import yaml

from src import db, main, second_source
from src.sources import datatable, owid

ROOT = Path(__file__).resolve().parent.parent
YEAR = 2026
CHART = {"slug": "meat-supply-per-person", "kind": "map", "name": "Lượng thịt bình quân mỗi người",
         "unit": "kg", "origin": "FAO"}


def fake_names(n: int = 120) -> dict:
    names = {f"C{i:03d}": f"Nước số {i}" for i in range(n)}
    names.update({"VNM": "Việt Nam", "THA": "Thái Lan", "LAO": "Lào",
                  "KHM": "Campuchia", "PHL": "Philippines", "SGP": "Singapore"})
    return names


def fake_table(names: dict, years=range(1990, 2024), world: float = None) -> dict:
    """Mỗi nước một mức riêng, tăng đều theo năm; Việt Nam ở giữa bảng."""
    table = {}
    for k, code in enumerate(sorted(names)):
        for y in years:
            table[(code, y)] = 10.0 + k + (y - 1990) * 0.5
    for y in years:
        table[("VNM", y)] = 40.0 + (y - 1990)
        if world is not None:
            table[(owid.WORLD, y)] = world + (y - 1990) * 0.1
    return table


class MapIdeaTest(unittest.TestCase):
    def test_world_map_idea_in_the_shared_data_format(self):
        names = fake_names()
        table = fake_table(names, world=30.0)
        table[("VNM", 2031)] = 999.0              # số DỰ BÁO của năm tương lai: không được dùng
        item = owid.build_map(CHART, table, names, ["VNM"], YEAR)
        s = item["summary"]
        self.assertEqual(item["source"], datatable.OWID_SOURCE)
        self.assertTrue(datatable.is_data_source(item["source"]))
        self.assertTrue(item["title"].startswith("Bản đồ thế giới: lượng thịt bình quân mỗi người năm 2023"))
        self.assertIn("— Việt Nam thứ", item["title"])
        self.assertIn("Nguồn: Our World in Data, biểu đồ “meat-supply-per-person” (số liệu gốc: FAO).",
                      s.splitlines()[0])
        self.assertEqual(item["url"], "https://ourworldindata.org/grapher/meat-supply-per-person?tab=map&time=2023")
        self.assertNotIn("999", s)
        # bảng mọi nước để tô bản đồ + chuỗi theo năm để vẽ biểu đồ đường, đúng khuôn World Bank
        self.assertEqual(datatable.parse_world_table(s)["year"], 2023)
        self.assertEqual([x["label"] for x in datatable.parse_series(s)], ["Việt Nam", "Thế giới"])
        # chủ đề thế giới: chỉ neo Việt Nam, không có dòng so găng hai nước ("gấp", "tương đương")
        self.assertNotIn("tương đương", s)
        self.assertNotIn(" lần ", s.split(datatable.WORLD_TABLE)[0])

    def test_world_total_is_not_drawn_next_to_countries(self):
        # CO2 cả năm của "Thế giới" là TỔNG, lớn hơn mọi nước: vẽ chung trục thì các nước dẹp lép
        names = fake_names()
        s = owid.build_map(CHART, fake_table(names, world=100000.0), names, ["VNM"], YEAR)["summary"]
        self.assertEqual([x["label"] for x in datatable.parse_series(s)], ["Việt Nam"])

    def test_too_few_countries_gives_no_map(self):
        names = fake_names(40)
        self.assertIsNone(owid.build_map(CHART, fake_table(names), names, ["VNM"], YEAR))


class RaceIdeaTest(unittest.TestCase):
    RACE = {"slug": "coffee-bean-production", "kind": "race", "group": "top", "name": "Sản lượng cà phê",
            "unit": "nghìn tấn", "scale": 1000, "origin": "FAO"}

    def test_top_ten_keeps_a_seat_for_vietnam(self):
        names = fake_names(30)
        table = fake_table(names)
        for y in range(1990, 2024):
            table[("VNM", y)] = 1.0                       # Việt Nam bét bảng
        item = owid.build_race(self.RACE, table, names, {}, ["VNM"], YEAR)
        self.assertEqual(item["title"], "Cuộc đua sản lượng cà phê: 9 nước dẫn đầu thế giới và Việt Nam"
                                        " từ 1990 đến 2023")
        labels = [x["label"] for x in datatable.parse_series(item["summary"])]
        self.assertEqual(len(labels), 10)
        self.assertIn("Việt Nam", labels)
        self.assertIn("Việt Nam: hạng 10 năm 1990, hạng 10 năm 2023", item["summary"])
        # hạng trong cuộc đua KHÔNG phải hạng thế giới: tóm tắt nói rõ và đưa hạng thật (ca thật #44)
        self.assertIn("không phải hạng thế giới", item["summary"].splitlines()[0])
        self.assertIn("Hạng thế giới thật năm 2023: Việt Nam thứ 36 trong 36 nước", item["summary"])
        self.assertIn("KHÔNG được gọi là hạng thế giới", item["summary"])
        self.assertIn("&country=", item["url"])
        self.assertTrue(item["url"].endswith("~VNM"))

    def test_vietnam_already_in_the_top_is_not_called_an_extra(self):
        names = fake_names(30)
        table = fake_table(names)
        for y in range(1990, 2024):
            table[("VNM", y)] = 10000.0 * (y - 1985)      # Việt Nam dẫn đầu, tính theo nghìn tấn
        item = owid.build_race(self.RACE, table, names, {}, ["VNM"], YEAR)
        self.assertIn(": 10 nước dẫn đầu thế giới từ", item["title"])
        self.assertIn("1. Việt Nam", item["summary"])

    def test_named_group_of_big_economies(self):
        names = fake_names(30)
        chart = dict(self.RACE, group="major", scale=1, name="Số giờ làm việc mỗi năm", unit="giờ")
        groups = {"major": ["C001", "C002", "C003", "VNM", "XXX"]}      # XXX không có trên bản đồ
        item = owid.build_race(chart, fake_table(names), names, groups, ["VNM"], YEAR)
        self.assertTrue(item["title"].startswith("Cuộc đua số giờ làm việc mỗi năm: Việt Nam và 3 nền kinh tế lớn"))
        # Việt Nam dẫn cả thế giới thật -> hạng trong nhóm = hạng thế giới, không cần cảnh báo
        self.assertIn("Việt Nam thứ 1 trong 36 nước", item["summary"])
        self.assertNotIn("KHÔNG được gọi", item["summary"])

    def test_too_few_years_gives_no_race(self):
        names = fake_names(30)
        item = owid.build_race(self.RACE, fake_table(names, years=range(2021, 2024)), names, {}, ["VNM"], YEAR)
        self.assertIsNone(item)


class FetchTest(unittest.TestCase):
    def test_rotates_charts_and_a_broken_chart_does_not_stop_the_rest(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        names = fake_names()
        tables = {"good": fake_table(names, world=30.0)}

        def fetch(slug):
            if slug not in tables:
                raise ConnectionError("mạng chập chờn")
            return tables[slug]
        world = {"countries": {c: {"name": n} for c, n in names.items()}}
        charts = [dict(CHART, slug="bad"), dict(CHART, slug="good")]
        with mock.patch("src.render.geo.has_map", return_value=True), \
                mock.patch("src.render.geo.load_map", return_value=world):
            items = owid.fetch_owid({"per_day": 2, "charts": charts}, date(2026, 11, 18), fetch)
        self.assertEqual([i["url"].split("/")[-1].split("?")[0] for i in items], ["good"])
        self.assertEqual(owid.fetch_owid({"charts": []}), [])

    def test_every_configured_chart_is_well_formed(self):
        cfg = yaml.safe_load((ROOT / "config" / "channel.yaml").read_text(encoding="utf-8"))["sources"]["owid"]
        self.assertGreaterEqual(len(cfg["charts"]), 10)
        slugs = [c["slug"] for c in cfg["charts"]]
        self.assertEqual(len(slugs), len(set(slugs)))
        for c in cfg["charts"]:
            self.assertIn(c["kind"], ("map", "race"), c["slug"])
            self.assertTrue(c["name"] and c["unit"] and c["origin"], c["slug"])
            if c["kind"] == "race":
                self.assertIn(c.get("group", "top"), ["top", *cfg["groups"]], c["slug"])
        # 2 bảng liền nhau (= 2 bảng của cùng một ngày) không cùng dạng hình
        kinds = [c["kind"] for c in cfg["charts"]]
        self.assertFalse(any(a == b == "race" for a, b in zip(kinds, kinds[1:])))


class FamilyTest(unittest.TestCase):
    def test_sources_map_to_topic_families(self):
        self.assertEqual(datatable.topic_family(datatable.WB_SOURCE), "viet-han")
        self.assertEqual(datatable.topic_family(datatable.KOSIS_SOURCE), "viet-han")
        self.assertEqual(datatable.topic_family(datatable.OWID_SOURCE), "the-gioi")
        self.assertEqual(datatable.topic_family("ScienceDaily Top"), "bai-bao")
        self.assertEqual(datatable.topic_family(None), "bai-bao")

    def test_editor_picks_are_interleaved_by_family(self):
        ideas = [{"id": 1, "source_name": datatable.WB_SOURCE}, {"id": 2, "source_name": datatable.WB_SOURCE},
                 {"id": 3, "source_name": datatable.OWID_SOURCE}, {"id": 4, "source_name": "ScienceDaily"},
                 {"id": 5, "source_name": datatable.WB_SOURCE}, {"id": 6, "source_name": datatable.OWID_SOURCE}]
        self.assertEqual([i["id"] for i in main.balance_families(ideas)], [1, 3, 4, 2, 6, 5])
        self.assertEqual(main.balance_families([]), [])

    def test_owid_ideas_say_where_the_numbers_come_from_instead_of_a_second_source(self):
        names = fake_names()
        item = owid.build_map(dict(CHART, origin="Tổ chức Y tế Thế giới (WHO)"), fake_table(names), names,
                              ["VNM"], YEAR)
        res = second_source.check({"source_name": item["source"], "summary": item["summary"]})
        self.assertEqual(res["status"], "none")
        self.assertIn("gốc: Tổ chức Y tế Thế giới (WHO))", res["summary"])


class DedupTest(unittest.TestCase):
    def test_data_ideas_are_deduplicated_by_url_not_by_similar_titles(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(db, "DB_PATH", Path(d) / "t.db"):
            con = db.connect()
            try:
                meat = "Bản đồ thế giới: lượng thịt bình quân mỗi người một năm năm 2023 — Việt Nam thứ 84/176"
                fish = ("Bản đồ thế giới: lượng cá và hải sản bình quân mỗi người một năm năm 2023"
                        " — Việt Nam thứ 21/176")
                src = datatable.OWID_SOURCE
                added = db.insert_raw_ideas(con, [
                    {"title": meat, "url": "https://o/meat", "source": src},
                    {"title": fish, "url": "https://o/fish", "source": src},     # tiêu đề giống 0,8
                    {"title": fish, "url": "https://o/fish", "source": src},     # trùng URL -> bỏ
                    {"title": "Bài báo về pin mặt trời mới", "url": "https://n/1", "source": "News"},
                    {"title": "Bài báo về pin mặt trời mới!", "url": "https://n/2", "source": "News"}])
                self.assertEqual(added, 3)
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
