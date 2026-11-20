"""Test nền móng nhiều kênh / nhiều ngôn ngữ (src/lang.py) — kênh Việt phải giữ y nguyên.

    python -m unittest tests.test_lang -v
"""
import os
import unittest
from pathlib import Path
from unittest import mock

import yaml

from src import lang
from src.sources import datatable as dt
from src.utils import digit_set, digits_of, number_values

ROOT = Path(__file__).resolve().parent.parent


class ChannelTest(unittest.TestCase):
    def test_default_is_the_vietnamese_channel(self):
        with mock.patch.dict(os.environ, {"CHANNEL_CONFIG": ""}), \
                mock.patch("dotenv.dotenv_values", return_value={}):
            self.assertEqual(lang.config_path(), ROOT / "config" / "channel.yaml")
            self.assertEqual(lang.code(), "vi")

    def test_korean_channel_is_chosen_by_environment(self):
        with mock.patch.dict(os.environ, {"CHANNEL_CONFIG": "config/channel_ko.yaml"}):
            self.assertEqual(lang.config_path(), ROOT / "config" / "channel_ko.yaml")
            self.assertEqual(lang.code(), "ko")

    def test_korean_config_is_complete(self):
        ko = yaml.safe_load((ROOT / "config" / "channel_ko.yaml").read_text(encoding="utf-8"))
        vi = yaml.safe_load((ROOT / "config" / "channel.yaml").read_text(encoding="utf-8"))
        self.assertEqual(ko["channel"]["language"], "ko")
        # mọi mục cấp cao của kênh Việt đều có ở kênh Hàn (code đọc thẳng, thiếu là lỗi lúc chạy)
        self.assertEqual(set(vi) - set(ko), set())
        self.assertEqual(ko["sources"]["worldbank"]["countries"][0]["iso3"], "KOR")
        self.assertEqual(ko["publish"]["youtube"]["utc_offset_hours"], 9)
        self.assertFalse(ko["publish"]["facebook"]["enabled"])

    def test_unknown_language_is_refused(self):
        with self.assertRaises(ValueError):
            with lang.using("fr"):
                pass


class NumberTest(unittest.TestCase):
    def test_vietnamese_numbers_unchanged(self):
        with lang.using("vi"):
            self.assertEqual([dt.vn_number(x) for x in (36226.97, 83.74, 0.721, 8.9, 5.0)],
                             ["36.227", "83,7", "0,72", "8,9", "5"])
            self.assertEqual(dt.spoken_scale(100987686), " (khoảng 101 triệu)")
            self.assertEqual(dt.parse_vn_number("36.227"), 36227)
            self.assertEqual(lang.fixed(1234567.8, 1), "1.234.567,8")

    def test_korean_numbers(self):
        with lang.using("ko"):
            self.assertEqual([dt.vn_number(x) for x in (36226.97, 83.74, 0.721)], ["36,227", "83.7", "0.72"])
            self.assertEqual(lang.fixed(1234567.8, 1), "1,234,567.8")
            self.assertEqual(dt.spoken_scale(51700000), " (약 5,170만)")
            self.assertEqual(dt.spoken_scale(100987686), " (약 1.01억)")
            self.assertEqual(dt.spoken_scale(2.5e12), " (약 2.5조)")
            self.assertEqual(dt.parse_vn_number("36,227"), 36227)
            self.assertEqual(dt.parse_vn_number("83.7"), 83.7)

    def test_number_gates_work_in_both_styles(self):
        # chuỗi chữ số không phụ thuộc kiểu viết: '1.234,5' (Việt) và '1,234.5' (Hàn) là cùng một số
        self.assertEqual(digit_set("1.234,5"), digit_set("1,234.5"))
        self.assertIn(1234.5, number_values("1,234.5"))
        # kênh Hàn nói số theo 만/억: "5,170만 명" phải khớp 51.700.000 trong bảng
        with lang.using("ko"):
            self.assertIn("5170", digits_of(51700000))
            self.assertIn("1", digits_of(100000000))                      # 1억
        with lang.using("vi"):
            self.assertNotIn("5170", digits_of(51700000))                 # kênh Việt không nói 만


class KoreanSummaryTest(unittest.TestCase):
    """Bảng số cho kênh Hàn: câu tiếng Hàn, số kiểu Hàn, code vẫn đọc ngược lại được."""
    KOR = [(1960, 5.99), (1970, 4.53), (1980, 2.82), (1990, 1.57), (2000, 1.48), (2010, 1.23), (2024, 0.75)]
    JPN = [(1960, 2.0), (1970, 2.13), (1980, 1.75), (1990, 1.54), (2000, 1.36), (2010, 1.39), (2024, 1.15)]

    def test_josa(self):
        self.assertEqual([lang.josa(w, "이/가") for w in ("한국", "일본", "베트남", "미국", "중국", "프랑스")],
                         ["한국이", "일본이", "베트남이", "미국이", "중국이", "프랑스가"])
        self.assertEqual(lang.josa("한국", "과/와"), "한국과")
        self.assertEqual(lang.josa("인도", "과/와"), "인도와")
        self.assertEqual(lang.josa("서울", "으로/로"), "서울로")
        self.assertEqual(lang.josa("한국", "으로/로"), "한국으로")

    def test_two_country_item_in_korean(self):
        from src.sources import worldbank
        ind = {"code": "SP.DYN.TFRT.IN", "name": "합계출산율", "unit": "명"}
        countries = [{"iso3": "KOR", "iso2": "KR", "name": "한국"}, {"iso3": "JPN", "iso2": "JP", "name": "일본"}]
        with lang.using("ko"):
            item = worldbank.build_item(ind, countries, {"KOR": self.KOR, "JPN": self.JPN})
            s = item["summary"]
            self.assertEqual(item["lang"], "ko")
            self.assertEqual(item["title"], "합계출산율: 한국과 일본, 1960–2024년")
            self.assertIn("한국: 1960년 5.99명; 2024년 0.75명.", s)
            self.assertIn("최신 수치: 일본은 한국의 1.53배.", s)
            self.assertIn("핵심 포인트", s)
            self.assertIn("일본이 한국을 앞지름", s)
            self.assertNotRegex(s, r"\d,\d{1,2}\b")                    # không còn số kiểu Việt (0,75)
            got = dt.parse_series(s)                                    # máy đọc lại để vẽ biểu đồ
            self.assertEqual([g["label"] for g in got], ["한국", "일본"])
            self.assertEqual(got[0]["ys"][-1], 0.75)
        with lang.using("vi"):                                         # kênh Việt vẫn đọc dòng "theo năm"
            self.assertEqual(dt.parse_series("Việt Nam theo năm: 2020: 1,5; 2024: 2.462.")[0]["ys"], [1.5, 2462])

    def test_fraction_and_period_lines(self):
        with lang.using("ko"):
            self.assertEqual(dt.fraction_phrase(68.6, "phụ nữ"), "여성 3명 중 2명")
            self.assertEqual(dt.fraction_phrase(56.8, "người"), "10명 중 거의 6명")
            self.assertEqual(dt.fraction_phrase(62.0, "xe mới bán"), "신차 5대 중 3대")
            line = dt.relatable_line([("한국", 1910.0)], "시간", {"period": "tuần"})
            self.assertEqual(line, "쉽게 와닿는 표현(기계가 미리 계산): 한국 연간 1,910시간 ≈ 일주일에 약 36.7시간.")
        with lang.using("vi"):
            self.assertEqual(dt.fraction_phrase(68.6, "phụ nữ"), "cứ 3 phụ nữ thì 2")

    def test_korean_country_names(self):
        from src.render import geo
        with lang.using("ko"):
            names = geo.country_names()
            self.assertEqual((names["KOR"], names["CHN"], names["PRK"], names["VNM"]), ("한국", "중국", "북한", "베트남"))
            self.assertEqual(geo.display_name("JPN"), "일본")
        self.assertEqual(geo.code_of("한국"), "KOR")
        with lang.using("vi"):
            self.assertEqual(geo.display_name("KOR"), "Hàn Quốc")


class KoreanMapTest(unittest.TestCase):
    """Bản đồ kênh Hàn theo GÓC NHÌN HÀN QUỐC (Du chốt 20/11/2026): Dokdo + 동해, không Hoàng Sa/Trường Sa;
    kênh Việt giữ nguyên Hoàng Sa/Trường Sa (luật bản đồ Việt Nam)."""
    COLORS = {"surface": "#1D2D44", "accent": "#FFB703", "muted": "#748CAB", "background": "#0D1321",
              "text": "#F0EBD8", "vietnam": "#E63946", "korea": "#457B9D", "japan": "#E63946"}

    def props(self, region):
        from src.render.web_map import map_props
        items = [{"label": "x", "code": c, "value": v} for c, v in
                 (("KOR", 83.6), ("JPN", 84.0), ("VNM", 74.7), ("CHN", 78.0), ("USA", 79.0), ("XKX", 76.0))]
        return map_props({"title": "t", "items": items, "region": region, "unit": "세"}, self.COLORS)

    def texts(self, mp):
        return [l["text"] for l in mp.get("islandLabels", []) + (mp.get("inset") or {}).get("labels", [])]

    def test_korean_view(self):
        from src.render import geo
        with lang.using("ko"):
            self.assertEqual(geo._map_path("world").name, "world_ko.json")
            self.assertIn("XKX", geo.load_map("world")["countries"])            # Hàn Quốc công nhận Kosovo
            for region in ("world", "asia"):
                t = self.texts(self.props(region))
                self.assertIn("독도", t, region)
                self.assertIn("동해", t, region)
                self.assertNotIn("Hoàng Sa", t, region)
            panel = [r["label"] for r in self.props("world")["panel"]]
            self.assertEqual(panel[:2], ["x", "x"])                             # Hàn, Nhật đứng đầu khung số
            self.assertEqual(self.props("world")["panel"][0]["color"], self.COLORS["korea"])

    def test_vietnamese_view_unchanged(self):
        from src.render import geo
        with lang.using("vi"):
            self.assertEqual(geo._map_path("world").name, "world.json")
            self.assertNotIn("XKX", geo.load_map("world")["countries"])
            for region in ("world", "asia"):
                t = self.texts(self.props(region))
                self.assertIn("Hoàng Sa", t)
                self.assertIn("Trường Sa", t)
                self.assertNotIn("독도", t)


if __name__ == "__main__":
    unittest.main()
