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
        for target, attr, val in [(db, "DB_PATH", root / "t.db"), (daily, "OUTPUT", root / "output"),
                                  (daily, "SPEC_DIR", root / "specs"), (daily, "LOG_DIR", root / "logs"),
                                  (daily, "load_config", lambda: CFG)]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.msgs = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.msgs.append(t) or 1)
        p.start(); self.addCleanup(p.stop)
        self.root, self.con = root, db.connect()
        self.addCleanup(self.con.close)
        self.ran = []

    def script(self, sid, total, status="verified", days_ago=0.0):
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,scores) VALUES (?,?,?,?,?)",
                         (sid, f"t{sid}", f"t{sid}", f"https://s/{sid}", json.dumps({"total": total})))
        self.con.execute("INSERT INTO scripts (id,idea_id,status,created_at) VALUES (?,?,?,?)",
                         (sid, sid, status, iso(days_ago)))
        self.con.commit()

    def runner(self, fail=()):
        """Hàm giả thay run_step: ghi lại bước đã chạy; 'gửi duyệt' thì tạo bản ghi video."""
        def run(name, key, args, log_file):
            self.ran.append((key, args[-1] if key != "ideas" else "-"))
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

    def test_plan_skips_done_work(self):
        names = lambda sid: [s[1] for s in daily.plan_steps(sid)]
        self.assertEqual(names(1), ["produce", "assemble", "review"])
        (self.root / "specs" / "script_1.yaml").write_text("[]")
        self.assertEqual(names(1), ["assemble", "review"])          # không sinh lại spec
        (self.root / "output" / "final_1.mp4").write_bytes(b"x")
        self.assertEqual(names(1), ["review"])


class RunTest(DailyCase):
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
