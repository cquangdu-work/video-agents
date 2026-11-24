"""Kênh Hàn 2 video/ngày (Du chốt phương án A, 24/11/2026): nhiều khung giờ đăng, hai video cùng ngày khác mảng + dạng,
bài viết ảnh 1 bài/ngày, chốt hạn mức YouTube dùng chung hai kênh, video dài tối đa 8 chương, so trước/sau nhịp mới."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import daily, db, growth, longform, review
from src.publish import youtube, yt_quota
from src.sources.datatable import KOSIS_SOURCE, OWID_SOURCE, WB_SOURCE
from tests.test_daily import DailyCase
import tests.test_phase4 as p4              # import cả module: tên lớp test cũ không lọt vào đây (khỏi chạy lặp)
from tests.test_phase4 import CFG as REVIEW_CFG, cb

KST = timezone(timedelta(hours=9))
YT = {"publish_times_local": ["12:00", "19:00"], "publish_time_local": "19:00", "utc_offset_hours": 9}


def kst(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=KST)


def z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SlotTest(unittest.TestCase):
    def test_two_slots_fill_in_order_then_next_day(self):
        now = kst(25, 8)
        a = youtube.compute_publish_at(YT, now)
        self.assertEqual(a, z(kst(25, 12)))
        b = youtube.compute_publish_at(YT, now, taken={a})
        self.assertEqual(b, z(kst(25, 19)))
        self.assertEqual(youtube.compute_publish_at(YT, now, taken={a, b}), z(kst(26, 12)))

    def test_slot_within_15_minutes_is_skipped(self):
        self.assertEqual(youtube.compute_publish_at(YT, kst(25, 18, 50)), z(kst(26, 12)))

    def test_single_time_unchanged(self):
        one = {"publish_time_local": "19:00", "utc_offset_hours": 9}
        t = youtube.compute_publish_at(one, kst(25, 8))
        self.assertEqual(t, z(kst(25, 19)))
        self.assertEqual(youtube.compute_publish_at(one, kst(25, 8), taken={t}), z(kst(26, 19)))
        self.assertIsNone(youtube.compute_publish_at({}, kst(25, 8)))

    def test_preferred_slot_first_then_others_same_day(self):
        fb = {"slots": ["12:00", "19:00", "21:00"], "utc_offset_hours": 9}
        t = youtube.compute_publish_at(fb, kst(25, 8), times=["21:00", "12:00", "19:00"])
        self.assertEqual(t, z(kst(25, 21)))
        t2 = youtube.compute_publish_at(fb, kst(25, 8), taken={t}, times=["21:00", "12:00", "19:00"])
        self.assertEqual(t2, z(kst(25, 12)))          # cùng ngày, không lùi sang ngày sau


class QuotaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"YT_QUOTA_FILE": str(Path(self.tmp.name) / "q.json")})
        p.start(); self.addCleanup(p.stop)

    def test_counts_per_pacific_day_and_blocks_upload(self):
        now = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)        # 12:00 giờ Hàn = 19:00 ngày 24 giờ PT
        for _ in range(5):
            yt_quota.spend("upload", now=now)
        yt_quota.spend("search", 4, now=now)
        self.assertEqual(yt_quota.used(now), 5 * 1600 + 400)
        self.assertFalse(yt_quota.can_upload(now))                      # 8.400 + 1.600 > 9.000
        later = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)       # 18:00 giờ Hàn = 01:00 PT ngày 25
        self.assertEqual(yt_quota.used(later), 0)
        self.assertTrue(yt_quota.can_upload(later))
        self.assertEqual(yt_quota.reset_at(now).hour, 8)                # 0:00 PST = 08:00 UTC = 17:00 giờ Hàn

    def test_broken_file_never_blocks(self):
        Path(os.environ["YT_QUOTA_FILE"]).write_text("{rác", encoding="utf-8")
        self.assertEqual(yt_quota.used(), 0)
        yt_quota.spend("upload")
        self.assertEqual(yt_quota.used(), 1600)


class BotCase(p4.DbCase):
    """Như test_phase4.ReviewFlowTest nhưng không kế thừa các test của nó."""

    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("send_message", "send_video", "send_document", "answer_callback", "clear_buttons"):
            p = mock.patch.object(p4.tg, name, side_effect=lambda *a, _n=name, **k: self.sent.append((_n, a, k)) or 77)
            p.start(); self.addCleanup(p.stop)
        self.vid = self.new_video()
        db.update_video(self.con, self.vid, tg_message_id=50)

    def calls(self, name):
        return [c for c in self.sent if c[0] == name]

    def status(self):
        return db.get_video(self.con, self.vid)["status"]


class QuotaHoldTest(BotCase):
    """Hết hạn mức: giữ video lại (approved), báo Du một lần; housekeeping tải lên sau khi đặt lại."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        p = mock.patch.dict(os.environ, {"YT_QUOTA_FILE": str(Path(tmp.name) / "q.json")})
        p.start(); self.addCleanup(p.stop)

    def test_hold_then_upload_after_reset(self):
        cfg = json.loads(json.dumps(REVIEW_CFG))
        cfg["publish"]["youtube"]["mode"] = "api"
        res = {"id": "abcdefghijk", "url": "u", "privacy": "public", "requested_privacy": "public", "publish_at": None}
        with mock.patch.object(yt_quota, "can_upload", return_value=False), \
                mock.patch.object(youtube, "upload", return_value=res) as up:
            review.handle_update(self.con, cb(f"ok:{self.vid}"), cfg)
            review.handle_update(self.con, cb(f"retry:{self.vid}"), cfg)
        self.assertEqual(up.call_count, 0)
        self.assertEqual(self.status(), "approved")
        held = [c for c in self.calls("send_message") if "Hạn mức YouTube" in c[1][0]]
        self.assertEqual(len(held), 1)                                  # báo đúng một lần
        due = datetime.fromisoformat(db.get_state(self.con, f"yt_quota_wait_{self.vid}"))
        with mock.patch.object(yt_quota, "can_upload", return_value=True), \
                mock.patch.object(youtube, "upload", return_value=res) as up:
            self.assertEqual(review.retry_quota_waits(self.con, cfg, due - timedelta(minutes=5)), [])
            self.assertEqual(review.retry_quota_waits(self.con, cfg, due + timedelta(minutes=5)), [self.vid])
            self.assertEqual(review.retry_quota_waits(self.con, cfg, due + timedelta(hours=1)), [])
        self.assertEqual(up.call_count, 1)
        self.assertEqual(self.status(), "published")


class PostsPerDayTest(BotCase):
    def test_posts_today_counts_only_today_with_posts(self):
        cfg = {"daily": {"utc_offset_hours": 9}}
        self.assertEqual(review.posts_today(self.con, cfg), 0)
        db.update_video(self.con, self.vid, fb_post="bài")
        self.assertEqual(review.posts_today(self.con, cfg), 1)
        self.assertEqual(review.posts_today(self.con, cfg, exclude=self.vid), 0)
        self.assertEqual(review.posts_today(self.con, cfg, now=datetime.now(timezone.utc) + timedelta(days=1)), 0)


CFG2 = {"daily": {"videos_per_day": 2, "max_attempts": 3, "max_script_age_days": 3}}


class TwoPerDayTest(DailyCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(daily, "load_config", lambda: CFG2)
        p.start(); self.addCleanup(p.stop)

    def source(self, sid, name, title):
        self.con.execute("UPDATE ideas SET source_name = ?, title = ? WHERE id = ?", (name, title, sid))
        self.con.commit()

    def test_second_video_differs_in_family_and_kind(self):
        self.script(1, 27); self.source(1, OWID_SOURCE, "세계 지도: 2024년 A")           # the-gioi / ban-do
        self.script(2, 26); self.source(2, OWID_SOURCE, "B 순위 경쟁: …")                # cùng mảng -> bỏ
        self.script(3, 25); self.source(3, KOSIS_SOURCE, "한국 지도: 2025년 시도별 C")    # cùng dạng bản đồ -> bỏ
        self.script(4, 24); self.source(4, WB_SOURCE, "D: 한국과 일본")                   # viet-han / bieu-do
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 2)
        made = [a for k, a in self.ran if k == "review"]
        self.assertEqual(made, ["1", "4"])

    def test_only_clashing_scripts_left_reports_and_keeps_them(self):
        self.script(1, 27); self.source(1, OWID_SOURCE, "세계 지도: 2024년 A")
        self.script(2, 26); self.source(2, OWID_SOURCE, "세계 지도: 2024년 B")
        self.assertEqual(daily.run_daily(skip_ideas=True, runner=self.runner()), 1)
        self.assertTrue(any("1/2 video" in m and "#2" in m for m in self.msgs))
        self.assertFalse(any("chưa có video" in m for m in self.msgs))


class StartDateTest(unittest.TestCase):
    def test_new_cadence_only_from_its_date(self):
        cfg = {"daily": {"videos_per_day": 2, "cadence_since": "2026-11-25", "utc_offset_hours": 9}}
        self.assertEqual(daily.videos_wanted(cfg, kst(24, 18, 40)), 1)          # lượt chạy bù tối 24/11
        self.assertEqual(daily.videos_wanted(cfg, kst(25, 7, 30)), 2)
        self.assertEqual(daily.videos_wanted({"daily": {"videos_per_day": 2}}), 2)


class ChapterCapTest(unittest.TestCase):
    def test_keeps_most_viewed_in_date_order(self):
        videos = [{"id": k} for k in range(12)]
        views = [5, 100, 3, 90, 80, 1, 70, 60, 2, 50, 40, 30]
        kept, kv = longform.pick_chapters(videos, views, 8)
        self.assertEqual([v["id"] for v in kept], [1, 3, 4, 6, 7, 9, 10, 11])
        self.assertEqual(kv, [100, 90, 80, 70, 60, 50, 40, 30])
        self.assertEqual(longform.lead_chapter(kept, kv), 0)

    def test_without_views_keeps_latest_and_short_week_untouched(self):
        videos = [{"id": k} for k in range(10)]
        self.assertEqual([v["id"] for v in longform.pick_chapters(videos, None, 8)[0]], list(range(2, 10)))
        self.assertEqual(longform.pick_chapters(videos[:5], None, 8)[0], videos[:5])


class CadenceReportTest(unittest.TestCase):
    CFG = {"daily": {"videos_per_day": 2, "cadence_since": "2026-11-25"}}

    def rows(self, before, after):
        out = [{"script_id": 1, "views": v, "age_days": 10, "published_at": f"2026-11-{20 + k % 4}T10:00:00+00:00"}
               for k, v in enumerate(before)]
        out += [{"script_id": 1, "views": v, "age_days": 5, "published_at": f"2026-11-{25 + k % 5}T10:00:00+00:00"}
                for k, v in enumerate(after)]
        return out

    def test_waits_two_weeks_then_flags_drop(self):
        rows = self.rows([1000] * 4, [100] * 20)
        early = growth.cadence_lines(rows, self.CFG, datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertTrue(any("mới 6 ngày" in l for l in early))
        late = growth.cadence_lines(rows, self.CFG, datetime(2026, 12, 10, tzinfo=timezone.utc))
        self.assertTrue(any("Luật lùi" in l for l in late))

    def test_more_total_views_is_fine_and_no_config_no_lines(self):
        rows = self.rows([500] * 4, [400] * 20)
        late = growth.cadence_lines(rows, self.CFG, datetime(2026, 12, 10, tzinfo=timezone.utc))
        self.assertTrue(any("✅" in l for l in late))
        self.assertEqual(growth.cadence_lines(rows, {"daily": {}}), [])


if __name__ == "__main__":
    unittest.main()
