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


if __name__ == "__main__":
    unittest.main()
