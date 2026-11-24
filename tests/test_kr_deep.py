"""Phát triển sâu ngách kênh Hàn (24/11/2026): bản đồ ~229 시군구, số mới công bố theo tháng, series cố định."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src import claims, daily, db, lang
from src.render import geo
from src.render.base import brand
from src.sources import datatable, kosis


class SggGeometryTest(unittest.TestCase):
    def test_units_and_lookups(self):
        units = geo.load_map("kr_sgg")["countries"]
        self.assertEqual(len(units), 228)                     # geoBoundaries 2020 thiếu 영광군
        self.assertTrue(all(c.startswith("SGG:") and u["rings"] for c, u in units.items()))
        # "중구" có ở 6 thành phố: mỗi nơi một mã riêng
        self.assertEqual(len([c for c in units if c.endswith(" 중구")]), 6)
        self.assertEqual(geo.sgg_code("세종시"), "SGG:세종시")
        self.assertEqual(geo.code_of("세종"), "KR-50")       # tên tỉnh vẫn là tỉnh
        self.assertEqual(geo.region_for(["SGG:서울 중구", "SGG:부산 중구", "SGG:세종시"]), "kr_sgg")

    def test_kosis_codes_to_map_labels(self):
        self.assertEqual(geo.kosis_sgg_label("11020", "중구"), "서울 중구")
        self.assertEqual(geo.kosis_sgg_label("21010", "중구"), "부산 중구")
        self.assertEqual(geo.kosis_sgg_label("1224050", "광산구"), "광주 광산구")     # mã mới sau sáp nhập
        self.assertEqual(geo.kosis_sgg_label("22520", "군위군"), "대구 군위군")       # 경북 -> 대구 (2023)
        self.assertEqual(geo.kosis_sgg_label("29", "세종특별자치시"), "세종시")
        self.assertIsNone(geo.kosis_sgg_label("23155", "영종구"))                    # Incheon 2026: chưa có hình
        self.assertIsNone(geo.kosis_sgg_label("11", "서울특별시"))
        self.assertIsNone(geo.kosis_sgg_label("31011", "장안구"))                    # 구 không tự trị của 수원시


def sgg_rows(values: dict, national: float, year=2025):
    """Dòng KOSIS giả cấp 시군구: values {(mã, tên): giá trị}."""
    rows = [{"C1": "00", "C1_NM": "전국", "PRD_DE": str(year), "DT": str(national)}]
    rows += [{"C1": c, "C1_NM": n, "PRD_DE": str(year), "DT": str(v)} for (c, n), v in values.items()]
    return rows


class SggSourceTest(unittest.TestCase):
    def test_series_read_by_code_not_name(self):
        dims = {"ITEM": [("T", "x")], "SGG": [("00", "전국")]}
        rows = sgg_rows({("11020", "중구"): 20.0, ("21010", "중구"): 30.0, ("37010", "포항시"): 25.0,
                         ("23155", "영종구"): 9.0}, 21.2)
        named, national = kosis._sgg_series(rows, dims, "SGG")
        self.assertEqual(named["SGG:서울 중구"], [(2025, 20.0)])
        self.assertEqual(named["SGG:부산 중구"], [(2025, 30.0)])
        self.assertNotIn("SGG:인천 영종구", named)
        self.assertEqual(national, [(2025, 21.2)])

    def test_build_sgg_map_idea(self):
        units = geo.load_map("kr_sgg")["countries"]
        codes = {u["name"]: c for c, u in units.items()}
        # dòng KOSIS giả cho mọi vùng: mã giả nhưng tên thật -> dùng kosis_sgg_label giả theo tên
        values = {name: 10 + k * 0.2 for k, name in enumerate(sorted(codes))}
        dims = {"ITEM": [("T1", "고령인구비율")], "SGG": [("00", "전국"), ("11", "서울특별시")]}

        def fake_series(rows, d, dim):
            return {codes[n]: [(2015, v - 3), (2025, v)] for n, v in values.items()}, [(2015, 13.1), (2025, 21.2)]
        t = {"kind": "province_map", "level": "sgg", "org": "101", "tbl": "X", "item": "고령인구비율",
             "name": "고령인구 비율", "unit": "%"}
        with lang.using("ko"), mock.patch.object(kosis, "table_meta", return_value=dims), \
                mock.patch.object(kosis, "fetch_table", return_value=[]), \
                mock.patch.object(kosis, "_sgg_series", fake_series):
            item = kosis.build_province_map(t, date(2026, 11, 24))
            world = datatable.parse_world_table(item["summary"])
        self.assertIn("한국 지도: 2025년 시군구별 고령인구 비율", item["title"])
        self.assertIn("228개 시군구", item["summary"])
        self.assertIn("시군구 상위 10곳", item["summary"])
        self.assertEqual(len(world["items"]), 229)              # 228 vùng + 전국
        from src.crew import fill_world_map
        p = {"title": "t"}
        with lang.using("ko"):
            fill_world_map(p, world)
        self.assertEqual((p["region"], p["total"], p["national"]), ("kr_sgg", 228, 21.2))
        self.assertIn("SGG:세종시", {it["code"] for it in p["items"]})

    def test_scene_has_seoul_inset_and_dokdo_owner(self):
        from src.render.web_map import KR_INSET, map_props
        units = geo.load_map("kr_sgg")["countries"]
        items = [{"label": u["name"], "value": float(k), "code": c} for k, (c, u) in enumerate(units.items())]
        # nơi CAO nhất là một 구 của Seoul -> tên ghi trong ô phóng to
        seoul = next(c for c, u in units.items() if u["province"] == "KR-11")
        next(it for it in items if it["code"] == seoul)["value"] = 999.0
        with lang.using("ko"):
            out = map_props({"title": "t", "region": "kr_sgg", "items": items, "national": 5.0, "unit": "%"},
                            brand()["colors"])
        self.assertEqual(out["region"], "kr_sgg")
        self.assertEqual(len(out["fills"]), 228)
        self.assertTrue(out["base"] and out["borders"] and out["inset"]["shapes"])
        self.assertFalse(out["inset"]["lines"])
        name = out["names"][0]
        self.assertTrue(KR_INSET["x0"] <= name["x"] <= KR_INSET["x1"] and KR_INSET["y0"] <= name["y"] <= KR_INSET["y1"])
        ulleung = next(f["color"] for f in out["fills"] if f["code"] == "SGG:경북 울릉군")
        self.assertEqual(out["islandColor"], ulleung)          # Dokdo thuộc 울릉군
        self.assertIn("독도", [l["text"] for l in out["islandLabels"]])


def monthly_rows(months: dict, region_values):
    """Dòng KOSIS giả theo tháng: months {yyyymm: hệ số}; region_values {tên: giá trị gốc}."""
    rows = []
    for m, k in months.items():
        for name, v in region_values.items():
            rows.append({"C1": name, "C1_NM": name, "PRD_DE": str(m), "DT": str(round(v * k, 3))})
    return rows


PROVINCES = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
             "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
             "경상북도", "경상남도", "제주특별자치도"]


class MonthlyTest(unittest.TestCase):
    T = {"org": "101", "tbl": "DT_1B8000G", "name": "출생아 수", "unit": "명", "pick": {"A": "출생아수(명)"},
         "map_value": "yoy"}

    def setUp(self):
        self.state = {}
        p = mock.patch.object(kosis, "_seen", lambda key, value=None: self.state.get(key) if value is None
                              else self.state.__setitem__(key, value))
        p.start(); self.addCleanup(p.stop)
        dims = {"ITEM": [("T1", "출생사망혼인이혼")], "B": [("00", "전국")] + [(n, n) for n in PROVINCES],
                "A": [("10", "출생아수(명)")]}
        p = mock.patch.object(kosis, "table_meta", return_value=dims)
        p.start(); self.addCleanup(p.stop)
        self.values = {"전국": 20000.0, **{n: 1000.0 + 100 * k for k, n in enumerate(PROVINCES)}}

    def run_with(self, months):
        with lang.using("ko"), mock.patch.object(kosis, "_monthly_rows",
                                                 return_value=monthly_rows(months, self.values)):
            return kosis.build_monthly_map(dict(self.T), date(2026, 11, 26))

    def test_first_sight_is_baseline_then_new_month_is_fresh(self):
        months = {202507: 1.0, 202607: 1.1}
        self.assertIsNone(self.run_with(months))               # lần đầu: chỉ ghi mốc
        self.assertIsNone(self.run_with(months))               # cùng tháng: không ra lại
        item = self.run_with({**months, 202508: 1.0, 202608: 1.13})
        self.assertIn("이번 달 통계: 2026년 8월 출생아 수", item["title"])
        self.assertTrue(datatable.is_fresh(item))
        self.assertIn("1년 전(2025년 8월 20,000명)보다 +13%", item["summary"])
        self.assertNotIn("배.", item["summary"].split("핵심 포인트")[1].split("\n")[1])   # không so số đếm thô giữa tỉnh
        with lang.using("ko"):
            w = datatable.parse_world_table(item["summary"])
        self.assertEqual((w["unit"], w["period"]), ("전년 동월 대비 %", "2026년 8월"))
        self.assertAlmostEqual(w["items"][0]["value"], 13.0)
        self.assertIsNone(self.run_with({**months, 202508: 1.0, 202608: 1.13}))

    def test_yoy_table_not_used_as_raw_values_by_claims(self):
        self.run_with({202507: 1.0, 202607: 1.1})
        item = self.run_with({202508: 1.0, 202608: 1.13})
        with lang.using("ko"):
            table = claims.data_table(item["summary"])
        self.assertNotIn("서울", table)                       # bảng tô màu là % thay đổi, không phải số sinh

    def test_fill_map_uses_table_unit_and_period(self):
        from src.crew import fill_world_map
        self.run_with({202507: 1.0, 202607: 1.1})
        item = self.run_with({202508: 1.0, 202608: 1.13})
        p = {"title": "t", "unit": "명"}
        with lang.using("ko"):
            fill_world_map(p, datatable.parse_world_table(item["summary"]))
        self.assertEqual((p["unit"], p["year"], p["region"]), ("전년 동월 대비 %", "2026년 8월", "kr"))


class FreshPickTest(unittest.TestCase):
    def test_fresh_script_built_first(self):
        from tests.test_daily import DailyCase

        class Case(DailyCase):
            def runTest(self):
                pass
        c = Case()
        c.setUp()
        try:
            c.script(1, 30); c.script(2, 10)
            c.con.execute("UPDATE ideas SET summary = ? WHERE id = 2", (f"{datatable.FRESH_MARK}: 2026년 8월 …",))
            c.con.commit()
            order = [x["id"] for x in daily.pick_candidates(c.con, {"daily": {"max_script_age_days": 3}})]
            self.assertEqual(order[0], 2)
        finally:
            c.doCleanups()


class SeriesTest(unittest.TestCase):
    CFG = {"publish": {"youtube": {"playlists": {"han-quoc": {"title": "지도로 보는 한국"},
                                                 "thang-nay": {"title": "이번 달 통계"},
                                                 "ban-do": {"title": "세계 지도로 보는 숫자"}}}}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "t.db")
        p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)

    def test_series_line_and_playlist(self):
        from src.publish import playlists
        self.assertEqual(playlists.series_of("한국 지도: 2025년 시군구별 …", self.CFG), "han-quoc")
        self.assertEqual(playlists.series_of("이번 달 통계: 2026년 8월 …", self.CFG), "thang-nay")
        self.assertIsNone(playlists.series_of("세계 지도: …", self.CFG))
        self.assertIsNone(playlists.series_of("한국 지도: …", {}))               # kênh không cấu hình series
        meta = playlists.with_series(self.con, {"description": "본문"}, "한국 지도: …", self.CFG)
        self.assertEqual(meta["description"], "▶ 시리즈 「지도로 보는 한국」 #지도로보는한국\n\n본문")
        db.set_state(self.con, "playlist_han-quoc", "PL123")
        meta = playlists.with_series(self.con, {"description": "본문"}, "한국 지도: …", self.CFG)
        self.assertIn("전체 보기: https://www.youtube.com/playlist?list=PL123", meta["description"])
        from src.publish import facebook
        cap = facebook.caption({"title": "T", "description": meta["description"]})
        self.assertNotIn("youtube.com/playlist", cap)                            # Reels không mang link YouTube
        self.assertIn("▶ 시리즈", cap)

    def test_subscribe_link_cached_and_kept_off_reels(self):
        from src.publish import facebook, playlists
        calls = []
        get = lambda: calls.append(1) or "UCxyz"
        with lang.using("ko"):
            meta = playlists.with_subscribe(self.con, {"description": "본문"}, get)
            playlists.with_subscribe(self.con, {"description": "본문"}, get)
        self.assertEqual(len(calls), 1)                                          # ID kênh lấy một lần, nhớ ở state
        self.assertTrue(meta["description"].startswith("🔔 매일 숫자 이야기 — 구독하기: "
                                                       "https://www.youtube.com/channel/UCxyz?sub_confirmation=1"))
        self.assertNotIn("sub_confirmation", facebook.caption({"title": "T", "description": meta["description"]}))
        db.set_state(self.con, "channel_id", "")
        self.assertEqual(playlists.with_subscribe(self.con, {"description": "x"}, lambda: 1 / 0)["description"], "x")


class TrialFixesTest(unittest.TestCase):
    """Hai lỗi lộ ra khi chạy thử video bản đồ 시군구 trên VM (24/11/2026)."""

    def test_whisper_number_pieces_merged_before_alignment(self):
        from src.audio.subtitles import merge_number_pieces, script_words_timed
        heard = [("반면", 11.7, 12.0), ("화성시는", 12.0, 12.54), ("11", 12.54, 13.1), (".6", 13.1, 13.5),
                 ("%로", 13.5, 14.08), ("최저입니다.", 14.08, 14.7)]
        self.assertEqual(merge_number_pieces(heard)[2], ("11.6%로", 12.54, 14.08))
        script = ["반면", "화성시는", "11.6%로", "최저입니다."]
        timed = script_words_timed(script, heard)
        self.assertEqual([w for w, _, _ in timed], script)            # chữ kịch bản, không phải mảnh Whisper
        self.assertEqual(merge_number_pieces([("2020,", 0, 1), ("Việt", 1, 2)])[1][0], "Việt")

    def test_finding_card_skips_fraction_numbers(self):
        from src.render.web import finding_of
        spec = lambda hook: [{"voice": hook}, {"voice": "x"}]
        with lang.using("ko"):
            f = finding_of(spec("2025년 경북 의성군은 2명 중 1명이 고령인구입니다."), 30)
            self.assertEqual(f["value"], "")                           # chỉ còn câu, không hiện to "2명"
            self.assertEqual(finding_of(spec("의성군은 2명 중 1명, 49.2%가 고령인구입니다."), 30)["value"], "49.2%")
        self.assertEqual(finding_of(spec("Cứ 3 người thì 2 người dùng internet, tức 68,6%."), 30)["value"], "68,6%")


if __name__ == "__main__":
    unittest.main()
