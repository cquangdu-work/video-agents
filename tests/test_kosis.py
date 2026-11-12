"""Test nguồn KOSIS — không gọi mạng (KOSIS được giả lập), không cần key thật.

    python -m unittest discover -s tests -v
"""
import json
import logging
import unittest
from unittest import mock

from src import crew, produce
from src.sources import kosis
from src.sources.datatable import is_data_source, parse_series

ITEM = [{"OBJ_ID": "ITEM", "ITM_ID": "T1", "ITM_NM": "현황"}]
NAT = [("AAC000", "총계"), ("AAC001", "아시아주계"), ("AAC004", "베트남"), ("AAC002", "중국"),
       ("AAC003", "한국계중국인"), ("AAC009", "우즈베키스탄"), ("AAC777", "어딘가")]
SEX = [("S0", "계"), ("SM", "남성")]
VISA = [("V0", "합계"), ("V9", "비전문취업(E-9)"), ("V6", "결혼이민(F-6)"), ("V2", "유학(D-2)"),
        ("V99", "기타(X-99)")]
META = ITEM + [{"OBJ_ID": d, "ITM_ID": i, "ITM_NM": n}
               for d, rows in (("NAT", NAT), ("SEX", SEX), ("VISA", VISA)) for i, n in rows]
VALUES = {  # (quốc tịch, visa) -> {năm: giá trị}
    ("AAC000", "V0"): {2022: 1000, 2025: 1600}, ("AAC001", "V0"): {2022: 900, 2025: 1400},
    ("AAC004", "V0"): {2022: 196883, 2023: 227930, 2024: 261581, 2025: 293907},
    ("AAC002", "V0"): {2022: 181571, 2023: 205502, 2024: 218893, 2025: 226628},
    ("AAC003", "V0"): {2022: 237869, 2023: 242032, 2024: 246988, 2025: 251037},
    ("AAC009", "V0"): {2022: 49149, 2023: 55239, 2024: 61733, 2025: 69317},
    ("AAC777", "V0"): {2022: 99999, 2025: 99999},
    ("AAC004", "V9"): {2022: 31607, 2025: 43561}, ("AAC004", "V6"): {2022: 37277, 2025: 42245},
    ("AAC004", "V2"): {2022: 32111, 2025: 56468}, ("AAC004", "V99"): {2022: 5, 2025: 7},
}
NAMES = dict(NAT + VISA)


def fake_get(url, params=None, timeout=None):
    r = mock.Mock(status_code=200)
    r.raise_for_status.return_value = None
    if url == kosis.META_URL:
        r.json.return_value = META
        return r
    nat, visa = params["objL1"], params["objL3"]
    rows = []
    for (n, v), years in VALUES.items():
        if nat not in ("ALL", n) or visa not in ("ALL", v):
            continue
        for y, val in years.items():
            rows.append({"C1": n, "C1_NM": NAMES[n], "C2": "S0", "C2_NM": "계", "C3": v,
                         "C3_NM": NAMES[v], "PRD_DE": str(y), "DT": str(val)})
    r.json.return_value = rows
    return r


TABLE = {"org": "111", "tbl": "DT_X", "name": "Người nước ngoài ở Hàn Quốc", "unit": "người",
         "org_name": "Bộ Tư pháp Hàn Quốc", "focus": ["Việt Nam"], "start": 2010}


class KosisTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        for target, attr, val in [(kosis.requests, "get", fake_get), (kosis.time, "sleep", lambda s: None)]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict("os.environ", {"KOSIS_API_KEY": "khoa-gia"}); p.start(); self.addCleanup(p.stop)

    def test_nationality_race_tells_the_story_and_warns_about_the_china_split(self):
        item = kosis.build_nationality_race(dict(TABLE, kind="nationality_race"))
        s = item["summary"]
        self.assertTrue(is_data_source(item["source"]))
        self.assertIn("Xếp hạng năm 2025: 1. Việt Nam 293.907; 2. Trung Quốc gốc Hàn 251.037;", s)
        self.assertIn("Việt Nam: hạng 2 năm 2022, hạng 1 năm 2025 — vượt Trung Quốc gốc Hàn.", s)
        self.assertIn("gộp lại năm 2025 là 477.665 người", s)               # chống kể sai "đông nhất"
        self.assertNotIn("총계", s); self.assertNotIn("주계", s)              # dòng gộp bị bỏ
        self.assertNotIn("99.999", s)                                          # quốc tịch chưa dịch: bỏ
        labels = [r["label"] for r in parse_series(s)]
        self.assertEqual(labels, ["Việt Nam", "Trung Quốc gốc Hàn", "Trung Quốc", "Uzbekistan"])
        self.assertTrue(item["url"].endswith("tblId=DT_X#nam-2025"))

    def test_vietnamese_by_visa_type(self):
        item = kosis.build_vietnam_by_category(dict(TABLE, name="Người Việt theo visa"))
        s = item["summary"]
        self.assertIn("Tổng số người Việt: năm 2022 là 196.883; năm 2025 là 293.907.", s)
        self.assertIn("Tỷ trọng năm 2025: Du học (D-2) 19,2%", s)
        self.assertEqual({r["label"] for r in parse_series(s)},
                         {"Du học (D-2)", "Lao động phổ thông (E-9)", "Kết hôn (F-6)"})   # (X-99) không dịch: bỏ

    def test_no_key_or_broken_table_never_breaks_the_pipeline(self):
        with mock.patch.dict("os.environ", {"KOSIS_API_KEY": ""}):
            self.assertEqual(kosis.fetch_kosis({"tables": [TABLE]}), [])
        err = mock.Mock(status_code=200)
        err.raise_for_status.return_value = None
        err.json.return_value = {"err": "20", "errMsg": "필수요청변수값이 누락되었습니다."}
        with mock.patch.object(kosis.requests, "get", return_value=err):
            self.assertEqual(kosis.fetch_kosis({"tables": [dict(TABLE, kind="nationality_race")]}), [])
        self.assertEqual(kosis.fetch_kosis({"tables": [dict(TABLE, kind="la")]}), [])

    def test_daily_rotation_through_tables(self):
        tables = [dict(TABLE, kind="nationality_race"), dict(TABLE, kind="vietnam_by_category")]
        from datetime import date
        titles = {kosis.fetch_kosis({"tables": tables, "per_day": 1}, date(2026, 11, d))[0]["title"]
                  for d in (12, 13)}
        self.assertEqual(len(titles), 2)                                       # hai ngày, hai bảng khác nhau


class BrokenSceneTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_broken_scene_keeps_its_narration_as_a_text_scene(self):
        cfg = {"pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4}}
        spec = produce.validate_spec([
            {"template": "map", "voice": "Các loại visa của người Việt.", "params": {
                "title": "Visa người Việt", "items": [{"label": "Du học (D-2)", "value": 1}]}},
            {"template": "pie_3d", "voice": "Câu lời của một mẫu lạ."},
            {"template": "pie_3d"}], cfg)                                     # không có lời: bỏ được
        self.assertEqual([s["template"] for s in spec], ["intro", "statement", "statement"])
        self.assertEqual(spec[1]["voice"], "Các loại visa của người Việt.")
        self.assertEqual(spec[1]["params"]["text"], "Visa người Việt")
        self.assertEqual(spec[2]["params"]["text"], "Câu lời của một mẫu lạ.")


class DesignerHintTest(unittest.TestCase):
    def hint(self, labels):
        summary = "\n".join(f"{l} theo năm: 2022: {k + 1}; 2025: {k + 2}." for k, l in enumerate(labels))
        seen = []
        with mock.patch.object(crew, "_run_single_task",
                               lambda **kw: seen.append(kw["description"]) or "[]"):
            crew.design_scenes({"title": "t", "angle": "g", "summary": summary},
                               [{"voice": "một hai ba"}],
                               {"channel": {"name": "k"}, "pacing": {"scene_seconds_min": 2,
                                                                     "scene_seconds_max": 4}})
        return seen[0]

    def test_map_is_suggested_only_for_countries(self):
        countries = self.hint(["Việt Nam", "Nepal", "Campuchia", "Trung Quốc gốc Hàn"])
        visas = self.hint(["Du học (D-2)", "Kết hôn (F-6)", "Lao động phổ thông (E-9)"])
        self.assertIn('"map"', countries)
        self.assertNotIn('cảnh "map"', visas)
        self.assertIn('"bar_race"', visas)
        self.assertIn('[{"label": "Việt Nam"}]', countries)                   # gợi ý đúng nhãn có trong bảng
        self.assertIn('{"label": "Du học (D-2)"}', visas)


if __name__ == "__main__":
    unittest.main()
