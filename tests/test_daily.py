"""Test chuỗi chạy hằng ngày — các bước con được thay bằng hàm giả, không dựng video thật.

    python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import daily, db
from src import telegram_bot as tg

CFG = {"daily": {"videos_per_day": 1, "max_attempts": 2, "max_script_age_days": 3}}


def iso(days_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


class DailyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "output").mkdir(); (root / "specs").mkdir()
        from src.analysis import learned
        # learned.yaml giả: sở thích người xem đã học trên VM không được làm đổi thứ tự trong test
        for target, attr, val in [(db, "DB_PATH", root / "t.db"), (daily, "OUTPUT", root / "output"),
                                  (daily, "LOCK", root / "daily.lock"),
                                  (daily, "SPEC_DIR", root / "specs"), (daily, "LOG_DIR", root / "logs"),
                                  (learned, "LEARNED_PATH", root / "learned.yaml"),
                                  (daily, "load_config", lambda: CFG)]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.msgs = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.msgs.append(t) or 1)
        p.start(); self.addCleanup(p.stop)
        self.root, self.con = root, db.connect()
        self.addCleanup(self.con.close)
        self.ran = []

    def script(self, sid, total, status="verified", days_ago=0.0, words=200, numbers=6):
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,scores) VALUES (?,?,?,?,?)",
                         (sid, f"t{sid}", f"t{sid}", f"https://s/{sid}", json.dumps({"total": total})))
        # JSON cũng là YAML; mỗi cảnh mở đầu bằng một con số khác nhau cho đủ "giàu số liệu"
        body = json.dumps([{"voice": (f"{100 + k} " if k < numbers else "") + "từ " * 10}
                           for k in range(words // 10)])
        self.con.execute("INSERT INTO scripts (id,idea_id,status,created_at,body) VALUES (?,?,?,?,?)",
                         (sid, sid, status, iso(days_ago), body))
        self.con.commit()

    def longform_video(self):
        """Bản ghi video dài hằng tuần như src/longform.py ghi: script_id rỗng, đã tới Telegram."""
        self.con.execute("INSERT INTO videos (script_id, file, title, created_at, tg_message_id)"
                         " VALUES (NULL, 'w.mp4', 'Tuần qua', ?, 70)", (iso(),))
        self.con.commit()

    def runner(self, fail=(), out_of_quota=()):
        """Hàm giả thay run_step: ghi lại bước đã chạy; 'gửi duyệt' thì tạo bản ghi video."""
        def run(name, key, args, log_file):
            self.ran.append((key, args[-1] if key != "ideas" else "-"))
            if (key, args[-1]) in out_of_quota:
                return False, f"mã thoát {daily.EXIT_RETRY_LATER}\nERROR assemble: TẠM DỪNG"
            if (key, args[-1]) in fail or (key == "ideas" and "ideas" in fail):
                return False, "mã thoát 1\nTraceback: lỗi giả lập"
            if key == "review":
                vid = db.upsert_video(self.con, int(args[-1]), "f.mp4", "T", "D", [], [])
                db.update_video(self.con, vid, tg_message_id=10)
            return True, ""
        return run


class PickTest(DailyCase):
    def test_order_and_filters(self):
        self.script(1, 26.5)
        self.script(2, 25.5)
        self.script(3, 30.0, status="draft")            # chưa qua kiểm chứng -> loại
        self.script(4, 29.0, days_ago=10)               # quá cũ -> loại
        self.script(5, 20.0)
        (self.root / "output" / "final_5.mp4").write_bytes(b"x")   # đã dựng sẵn -> ưu tiên số 1
        self.script(6, 28.0)
        db.set_state(self.con, "prod_fail_6", 2)        # hỏng 2 lần -> loại
        self.script(7, 27.0)
        vid = db.upsert_video(self.con, 7, "f", "T", "D", [], [])
        db.update_video(self.con, vid, tg_message_id=3)  # đã gửi duyệt -> loại
        self.script(8, 10.0)
        db.upsert_video(self.con, 8, "f", "T", "D", [], [])   # gửi Telegram hụt -> vẫn được thử lại
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [5, 1, 2, 8])

    def test_weekly_long_video_does_not_hide_every_script(self):
        # Ca thật 18/11: `s.id NOT IN (… NULL …)` không bao giờ đúng -> 0 ứng viên, 0 video
        self.script(1, 26.5)
        self.longform_video()
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [1])

    def test_does_not_make_the_same_topic_family_two_days_in_a_row(self):
        # Ca thật 13-18/11: 6/6 video là Việt–Hàn vì ý tưởng World Bank luôn được chấm điểm cao nhất
        from src.sources import datatable as dt
        self.script(1, 26.5); self.script(2, 22.0); self.script(3, 20.0)
        for sid, src in ((1, dt.WB_SOURCE), (2, dt.OWID_SOURCE), (3, dt.WB_SOURCE)):
            self.con.execute("UPDATE ideas SET source_name=? WHERE id=?", (src, sid))
        self.script(9, 30.0)
        self.con.execute("UPDATE ideas SET source_name=? WHERE id=9", (dt.KOSIS_SOURCE,))
        vid = db.upsert_video(self.con, 9, "f", "T", "D", [], [])
        db.update_video(self.con, vid, tg_message_id=5)            # hôm qua: video Việt–Hàn
        self.con.commit()
        picked = daily.pick_candidates(self.con, CFG)
        self.assertEqual([(c["id"], c["family"]) for c in picked],
                         [(2, "the-gioi"), (1, "viet-han"), (3, "viet-han")])
        self.assertEqual(daily.recent_families(self.con), ["viet-han"])
        self.assertEqual(daily.streak("viet-han", ["viet-han", "viet-han", "the-gioi"]), 2)
        self.assertEqual(daily.streak("the-gioi", ["viet-han", "the-gioi"]), 0)

    def test_too_short_legacy_script_is_skipped_before_spending_tts(self):
        # Ca thật trên VM: kịch bản đời cũ 3 cảnh ~115 từ có điểm CAO NHẤT nên bị chọn trước
        self.script(1, 26.5, words=110)
        self.script(6, 24.0, words=200)
        self.assertEqual(daily.script_words(None), 0)
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [6])
        loose = {"daily": {**CFG["daily"], "min_script_words": 100}}
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, loose)], [1, 6])

    def test_script_with_too_few_numbers_is_skipped(self):
        # Ca thật trên VM: kịch bản "verified" đời cũ chỉ có 2 con số, điểm cao nhất
        self.script(7, 24.0, numbers=2)
        self.script(8, 23.0, numbers=5)
        self.assertEqual(daily.script_numbers(None), 0)
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [8])

    def test_script_opening_with_a_banned_template_is_not_produced(self):
        # Kịch bản viết trước luật kể chuyện 12/11 (ca thật #13 "Đừng bỏ qua…", #12 "Sai lầm…")
        self.script(12, 26.0)
        self.script(13, 25.0)
        body = json.loads(self.con.execute("SELECT body FROM scripts WHERE id=12").fetchone()["body"])
        body[0]["voice"] = "Sai lầm 40 điểm khi chọn nguồn đạm cho cơ thể?"
        self.con.execute("UPDATE scripts SET body=? WHERE id=12", (json.dumps(body, ensure_ascii=False),))
        self.con.commit()
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [13])
        self.assertEqual(daily.opening_problems(None), [])

    def test_verified_script_with_a_false_comparison_is_not_produced(self):
        # Ca thật #46 (19/11): "đạt" Kiểm chứng trước khi có cổng so sánh, hook sai sự thật
        from tests.test_claims import WOMEN
        self.script(46, 25.5)
        self.script(47, 20.0)
        body = json.loads(self.con.execute("SELECT body FROM scripts WHERE id=46").fetchone()["body"])
        body[0]["voice"] = "Hàn Quốc năm 2025 mới đạt tỷ lệ phụ nữ đi làm mà Việt Nam đã có từ năm 1990."
        self.con.execute("UPDATE scripts SET body=? WHERE id=46", (json.dumps(body, ensure_ascii=False),))
        self.con.execute("UPDATE ideas SET summary=? WHERE id=46", (WOMEN,))
        self.con.commit()
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, CFG)], [47])
        self.assertEqual(daily.comparison_problems(None, WOMEN), [])

    def test_plan_skips_done_work(self):
        names = lambda sid: [s[1] for s in daily.plan_steps(sid)]
        self.assertEqual(names(1), ["produce", "assemble", "review"])
        # Spec đời cũ KHÔNG có 'voice' -> video sẽ câm -> phải sinh lại
        (self.root / "specs" / "script_1.yaml").write_text(
            "- template: statement\n  params: {text: x}\n", encoding="utf-8")
        self.assertEqual(names(1), ["produce", "assemble", "review"])
        # Spec có lời đọc -> dùng lại, không sinh lại (giữ cache giọng)
        (self.root / "specs" / "script_1.yaml").write_text(
            "- template: statement\n  voice: xin chào\n  params: {text: x}\n", encoding="utf-8")
        self.assertEqual(names(1), ["assemble", "review"])
        (self.root / "output" / "final_1.mp4").write_bytes(b"x")
        self.assertEqual(names(1), ["review"])


class RunTest(DailyCase):
    def test_a_day_is_a_calendar_day_in_korea_not_a_rolling_window(self):
        vid = db.upsert_video(self.con, 1, "f.mp4", "T", "D", [], [])
        db.update_video(self.con, vid, tg_message_id=10)
        at = lambda iso_utc: datetime.fromisoformat(iso_utc)
        # video ra lúc 18:10 giờ Hàn ngày 11 (lượt chạy bù buổi chiều)
        self.con.execute("UPDATE videos SET created_at='2026-11-11T09:10:00+00:00'")
        self.con.commit()
        self.assertEqual(daily.videos_made_today(self.con, CFG, at("2026-11-11T14:00:00+00:00")), 1)  # 23:00 cùng ngày
        self.assertEqual(daily.videos_made_today(self.con, CFG, at("2026-11-11T21:00:00+00:00")), 0)  # 06:00 hôm sau
        # video ra lúc 06:30 giờ Hàn -> lượt chạy bù 17:40 cùng ngày không làm thêm
        self.con.execute("UPDATE videos SET created_at='2026-11-10T21:30:00+00:00'")
        self.con.commit()
        self.assertEqual(daily.videos_made_today(self.con, CFG, at("2026-11-11T08:40:00+00:00")), 1)

    def test_weekly_long_video_does_not_count_as_todays_short(self):
        # Thứ Bảy: sáng hết quota TTS, video dài gửi 09:30 -> lượt bù 17:40 vẫn phải làm Shorts
        self.script(1, 26.5)
        self.longform_video()
        self.assertEqual(daily.videos_made_today(self.con, CFG), 0)
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 1)
        self.assertEqual(daily.videos_made_today(self.con, CFG), 1)

    def test_second_run_at_the_same_time_backs_off(self):
        self.script(1, 26.5)
        self.assertTrue(daily.acquire_lock())            # một lượt khác đang chạy
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 0)
        self.assertEqual(self.ran, [])
        self.assertTrue(daily.LOCK.exists())             # không được xoá khoá của lượt kia
        os.utime(daily.LOCK, (0, 0))                     # khoá từ năm 1970 = lượt trước chết giữa chừng
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 1)
        self.assertFalse(daily.LOCK.exists())            # chạy xong thì nhả khoá

    def test_happy_path_makes_one_video_then_stops_for_the_day(self):
        self.script(1, 26.5); self.script(2, 25.5)
        self.assertEqual(daily.run_daily(runner=self.runner()), 1)
        self.assertEqual(self.ran, [("ideas", "-"), ("produce", "--spec-only"),
                                    ("assemble", "1"), ("review", "1")])
        self.assertEqual(self.msgs, [])                 # êm thì không nhắn gì thêm
        self.ran.clear()
        self.assertEqual(daily.run_daily(runner=self.runner()), 0)   # chạy lại trong ngày
        self.assertEqual(self.ran, [])

    def test_falls_back_to_next_script_and_reports(self):
        self.script(1, 26.5); self.script(2, 25.5); self.script(3, 20.0)
        made = daily.run_daily(skip_ideas=True, runner=self.runner(fail={("assemble", "1")}))
        self.assertEqual(made, 1)
        self.assertIn(("review", "2"), self.ran)
        self.assertNotIn(("review", "1"), self.ran)     # hỏng lắp ráp thì KHÔNG gửi duyệt
        self.assertNotIn(("assemble", "3"), self.ran)
        self.assertEqual(db.get_state(self.con, "prod_fail_1"), "1")
        self.assertEqual(len(self.msgs), 1)
        self.assertIn("Kịch bản #1 hỏng ở bước “Lắp ráp video”", self.msgs[0])

    def test_all_fail_notifies_and_respects_max_attempts(self):
        for sid in (1, 2, 3):
            self.script(sid, 20 + sid)
        fail = {("assemble", "1"), ("assemble", "2"), ("assemble", "3"), "ideas"}
        self.assertEqual(daily.run_daily(runner=self.runner(fail=fail)), 0)
        self.assertEqual(sum(1 for k, _ in self.ran if k == "assemble"), 2)   # max_attempts = 2
        self.assertIn("chưa có video", self.msgs[0])
        self.assertIn("Bước ý tưởng/kịch bản lỗi", self.msgs[0])

    def test_tts_quota_pauses_without_blaming_the_script(self):
        self.script(1, 26.5); self.script(2, 25.5)
        made = daily.run_daily(skip_ideas=True, runner=self.runner(out_of_quota={("assemble", "1")}))
        self.assertEqual(made, 0)
        self.assertEqual(db.get_state(self.con, "prod_fail_1", "0"), "0")   # không tính lần hỏng
        self.assertNotIn(("assemble", "2"), self.ran)   # kịch bản kế cũng cần TTS -> không đốt thêm
        self.assertEqual(len(self.msgs), 1)
        self.assertIn("hết quota giọng đọc", self.msgs[0])
        self.assertNotIn("hỏng ở bước", self.msgs[0])

    def test_exit_codes_agree_between_assemble_and_daily(self):
        from src import assemble
        self.assertEqual(assemble.EXIT_RETRY_LATER, daily.EXIT_RETRY_LATER)

    def test_nothing_verified(self):
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 0)
        self.assertIn("Không có kịch bản nào qua được Kiểm chứng", self.msgs[0])

    def test_dry_run_runs_nothing(self):
        self.script(1, 26.5)
        with mock.patch("builtins.print") as pr:
            daily.run_daily(dry_run=True, runner=self.runner())
        self.assertEqual(self.ran, [])
        self.assertIn("kịch bản #1", " ".join(str(c.args[0]) for c in pr.call_args_list))

    def test_run_step_real_subprocess(self):
        logf = self.root / "x.log"
        with mock.patch.object(daily, "ROOT", self.root):
            self.assertEqual(daily.run_step("ok", "review", ["-c", "print('xin chào')"], logf), (True, ""))
            ok, tail = daily.run_step("hỏng", "review", ["-c", "raise SystemExit('bùm')"], logf)
            self.assertFalse(ok); self.assertIn("bùm", tail)
            with mock.patch.dict(daily.STEP_TIMEOUT, {"review": 1}):
                ok, tail = daily.run_step("treo", "review", ["-c", "import time; time.sleep(5)"], logf)
            self.assertFalse(ok); self.assertIn("quá", tail)
        self.assertIn("xin chào", logf.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
