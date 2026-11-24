"""Chủ đề tuần cho video dài (src/themes.py, 24/11/2026)."""
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from src import daily, db, longform, themes
from src.sources import kosis
from tests.test_daily import DailyCase

THEMES = [
    {"key": "a", "title": "출산율 반등, 진짜일까?", "words": ["출산", "출생", "혼인"], "wb": ["SP.DYN.TFRT.IN"],
     "kosis": ["DT_1B81A21"]},
    {"key": "b", "title": "지방소멸", "words": ["고령"], "kosis": ["DT_1YL20631:sgg"], "owid": ["median-age"]},
]
CFG = {"daily": {"utc_offset_hours": 9, "videos_per_day": 2, "max_script_age_days": 3},
       "longform": {"themes_start": "2026-11-22", "theme_shorts": 2, "themes": THEMES},
       "publish": {"youtube": {"utc_offset_hours": 9}},
       "sources": {"worldbank": {"indicators": [], "races": {"x": 1}, "world": {"per_day": 1}},
                   "owid": {"charts": []}, "kosis": {"tables": []}}}


class RotationTest(unittest.TestCase):
    def test_week_rotation(self):
        self.assertEqual(themes.current(CFG, date(2026, 11, 22))["key"], "a")       # Chủ nhật đầu tiên
        self.assertEqual(themes.current(CFG, date(2026, 11, 28))["key"], "a")       # thứ Bảy cùng tuần (video dài)
        self.assertEqual(themes.current(CFG, date(2026, 11, 29))["key"], "b")
        self.assertEqual(themes.current(CFG, date(2026, 12, 6))["key"], "a")        # vòng lại
        self.assertIsNone(themes.current(CFG, date(2026, 11, 21)))
        self.assertIsNone(themes.current({"daily": {}}, date(2026, 11, 25)))
        self.assertEqual(themes.week_start(CFG, date(2026, 11, 26)), date(2026, 11, 22))

    def test_matches_and_priority_injection(self):
        t = THEMES[0]
        self.assertTrue(themes.matches(t, "이번 달 통계: 2026년 9월 출생아 수", ""))
        self.assertTrue(themes.matches(t, "x", "지표: 혼인 건수(건). 출처…"))
        self.assertFalse(themes.matches(t, "세계 지도: 산림", "지표: 산림 면적 비율"))
        out = themes.with_theme(CFG, date(2026, 11, 25))
        src = out["sources"]
        self.assertEqual(src["worldbank"]["priority"], ["SP.DYN.TFRT.IN"])
        self.assertEqual(src["worldbank"]["world"]["priority"], ["SP.DYN.TFRT.IN"])
        self.assertEqual(src["kosis"]["priority"], ["DT_1B81A21"])
        self.assertNotIn("priority", src["owid"])
        self.assertNotIn("priority", CFG["sources"]["kosis"])                       # cấu hình gốc không bị sửa

    def test_kosis_priority_picks_theme_table_first(self):
        tables = [{"kind": "x", "tbl": "A"}, {"kind": "x", "tbl": "DT_1YL20631"},
                  {"kind": "x", "tbl": "DT_1YL20631", "level": "sgg"}]
        seen = []
        with mock.patch.dict(kosis.BUILDERS, {"x": lambda t, today: seen.append(t) or None}), \
                mock.patch.object(kosis, "api_key", return_value="k"):
            kosis.fetch_kosis({"tables": tables, "per_day": 1, "priority": ["DT_1YL20631:sgg"]}, date(2026, 11, 25))
        self.assertEqual(seen, [tables[2]])


class WeekCountTest(DailyCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(daily, "load_config", lambda: CFG)
        p.start(); self.addCleanup(p.stop)

    def idea(self, sid, title):
        self.con.execute("UPDATE ideas SET title = ?, summary = '' WHERE id = ?", (title, sid))
        self.con.commit()

    def test_theme_scripts_first_until_enough(self):
        now = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)           # thứ Tư 10:00 giờ Hàn
        self.script(1, 30); self.idea(1, "세계 지도: 산림")
        self.script(2, 10); self.idea(2, "합계출산율: 한국과 일본")
        order = [c["id"] for c in daily.pick_candidates(self.con, CFG, now)]
        self.assertEqual(order[0], 2)                                     # khớp chủ đề -> dựng trước
        # đủ 2 Short của chủ đề trong tuần -> hết ưu tiên
        for sid, title in ((3, "출생아 수"), (4, "혼인 건수")):
            self.script(sid, 5); self.idea(sid, title)
            vid = db.upsert_video(self.con, sid, "f.mp4", "T", "D", [], [])
            db.update_video(self.con, vid, tg_message_id=10)
            self.con.execute("UPDATE videos SET created_at = ? WHERE id = ?", ("2026-11-24T00:00:00+00:00", vid))
        self.con.commit()
        self.assertEqual(themes.shorts_this_week(self.con, CFG, THEMES[0], date(2026, 11, 25)), 2)
        self.assertIsNone(themes.wanted(self.con, CFG, date(2026, 11, 25)))
        order = [c["id"] for c in daily.pick_candidates(self.con, CFG, now)]
        self.assertEqual(order[0], 1)


class LongformThemeTest(unittest.TestCase):
    NOW = datetime(2026, 11, 28, 2, 30, tzinfo=timezone.utc)              # thứ Bảy 11:30 giờ Hàn

    def vids(self, titles):
        return [{"id": k, "idea_title": t, "idea_summary": "", "title": t} for k, t in enumerate(titles)]

    def test_enough_theme_shorts_make_the_long_video(self):
        v = self.vids(["합계출산율", "산림", "출생아 수", "혼인 건수", "GDP"])
        got, title = longform.theme_chapters(v, CFG, self.NOW)
        self.assertEqual([x["id"] for x in got], [0, 2, 3])
        self.assertEqual(title, "출산율 반등, 진짜일까?")

    def test_too_few_keeps_old_behaviour(self):
        v = self.vids(["합계출산율", "산림", "GDP"])
        got, title = longform.theme_chapters(v, CFG, self.NOW)
        self.assertEqual((len(got), title), (3, None))
        self.assertEqual(longform.theme_chapters(v, {"publish": {}}, self.NOW), (v, None))

    def test_title_and_intro_use_theme(self):
        from src import lang
        videos = [{"title": f"t{k}", "description": "", "tags": "[]"} for k in range(3)]
        with lang.using("ko"):
            title, desc, _ = longform.build_text(videos, [0, 30, 60], "11.22–11.28", {"publish": {}},
                                                 lead=1, theme="출산율 반등, 진짜일까?")
            intro = longform.intro_text(videos, "11.22–11.28", 1, "출산율 반등, 진짜일까?")
        self.assertTrue(title.startswith("출산율 반등, 진짜일까? | "))
        self.assertTrue(desc.startswith("출산율 반등, 진짜일까?"))
        self.assertIn("한 가지 주제로 숫자 이야기 3편", intro)


if __name__ == "__main__":
    unittest.main()
