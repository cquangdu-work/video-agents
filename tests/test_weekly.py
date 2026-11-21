"""Test agent Phân tích — số liệu YouTube đều là giả lập.

    python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

from src import db
from src import telegram_bot as tg
from src.analysis import learned, weekly
from src.publish import youtube

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
WEIGHTS = {"curiosity": 1.0, "novelty": 1.0, "verifiability": 1.0, "accessibility": 1.0,
           "visualizability": 1.5, "min_total": 17}


class StatsTest(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(weekly.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(weekly.spearman([1, 2, 3, 4], [9, 7, 5, 1]), -1.0)
        self.assertAlmostEqual(weekly.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]), 0.8)
        self.assertAlmostEqual(weekly.spearman([1, 1, 2, 2], [1, 2, 3, 4]), 0.894, places=3)  # có hạng bằng nhau
        self.assertIsNone(weekly.spearman([5, 5, 5], [1, 2, 3]))      # một bên không đổi
        self.assertIsNone(weekly.spearman([1, 2], [1, 2]))            # quá ít điểm

    def rows(self, n, key=lambda i: i):
        # curiosity tăng cùng % xem; novelty ngược chiều; verifiability không đổi
        return [{"scores": {"curiosity": 1 + i % 5 + i / 100, "novelty": 100 - i, "verifiability": 5,
                            "accessibility": (i * 7) % 5, "visualizability": (i * 3) % 4},
                 "avg_view_pct": 40 + key(i), "views": 1000} for i in range(n)]

    def test_weights_need_enough_videos(self):
        new, notes = weekly.propose_weights(self.rows(9), WEIGHTS, "avg_view_pct")
        self.assertEqual(new, WEIGHTS)
        self.assertIn("9/10", notes[0])

    def test_weights_move_one_small_step_and_rescale_threshold(self):
        rows = self.rows(12)
        for r in rows:                       # curiosity đồng biến hoàn toàn với % xem
            r["scores"]["curiosity"] = r["avg_view_pct"]
        new, notes = weekly.propose_weights(rows, WEIGHTS, "avg_view_pct")
        self.assertEqual(new["curiosity"], 1.1)
        self.assertEqual(new["novelty"], 0.9)
        self.assertEqual(new["verifiability"], 1.0)          # không tính được -> giữ
        self.assertEqual(len([n for n in notes if "→" in n]),
                         sum(1 for c in weekly.CRITERIA if new[c] != WEIGHTS[c]))
        s_old = sum(WEIGHTS[c] for c in weekly.CRITERIA)
        s_new = sum(new[c] for c in weekly.CRITERIA)
        self.assertEqual(new["min_total"], round(17 * s_new / s_old, 1))

    def test_weights_are_clamped(self):
        rows = self.rows(12)
        for r in rows:
            r["scores"]["curiosity"] = r["avg_view_pct"]
        new, _ = weekly.propose_weights(rows, dict(WEIGHTS, curiosity=2.5, novelty=0.5), "avg_view_pct")
        self.assertEqual((new["curiosity"], new["novelty"]), (2.5, 0.5))

    def test_pick_metric(self):
        self.assertEqual(weekly.pick_metric([{"avg_view_pct": 50}] * 3), "avg_view_pct")
        self.assertEqual(weekly.pick_metric([{"views": 5}] * 3 + [{"avg_view_pct": 50}]), "views")

    def test_retention_maps_drop_to_scene(self):
        timeline = [(0, 2, "intro", ""), (2, 10, "statement", "hook"),
                    (10, 20, "bar_chart", "lời cảnh 3"), (20, 40, "big_number", "lời cảnh 4")]
        # 40 giây; rớt nhẹ đều, riêng quanh giây 14 rớt mạnh
        ret = [(i / 20, 1.0 - 0.01 * i - (0.25 if i >= 7 else 0)) for i in range(1, 21)]
        f = weekly.retention_findings(ret, timeline)
        self.assertEqual(f["drop_scene"], 3)
        self.assertEqual(f["drop_template"], "bar_chart")
        self.assertEqual(f["drop_at"], 14.0)
        self.assertEqual(f["hook_hold"], 98)               # điểm đầu tiên sau 3s (giây 4)
        self.assertIsNone(weekly.retention_findings([], timeline))
        self.assertIsNone(weekly.retention_findings(ret, []))

    def test_losses_per_scene_type(self):
        # 19/11: đo bằng số cảnh chữ có đuổi người xem hơn cảnh biểu đồ không
        timeline = [(0, 10, "statement", "a"), (10, 20, "line_chart", "b"), (20, 30, "statement", "c")]
        ret = [(i / 30, 1.0 - (0.02 * i if i <= 10 else 0.2 + 0.005 * (i - 10) if i <= 20
                                else 0.25 + 0.02 * (i - 20))) for i in range(0, 31)]
        losses = weekly.scene_losses(ret, timeline)
        self.assertEqual([x[0] for x in losses], ["statement", "line_chart", "statement"])
        self.assertAlmostEqual(losses[0][1], 7.0)                  # bỏ 3 giây đầu (chuyện của hook)
        by = weekly.loss_by_template([{"losses": losses}])
        self.assertGreater(by["statement"], by["line_chart"])
        self.assertEqual(weekly.loss_by_template([{"losses": [("map", 5.0, 0.1)]}]), {})   # dưới 10 giây
        self.assertEqual(weekly.scene_losses([], timeline), [])


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.text = status, body or {}, json.dumps(body or {})

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class ApiTest(unittest.TestCase):
    def test_analytics_video_falls_back_to_core_metrics(self):
        ok = Resp(200, {"columnHeaders": [{"name": "views"}, {"name": "averageViewPercentage"}],
                        "rows": [[1200, 71.5]]})
        get = mock.Mock(side_effect=[Resp(400, {"error": "bad metric combo"}), ok])
        with mock.patch.object(youtube.requests, "get", get):
            out = youtube.analytics_video("abcdefghijk", "2026-11-20", "2026-12-01", "AT")
        self.assertEqual(out, {"views": 1200, "averageViewPercentage": 71.5})
        self.assertIn("engagedViews", get.call_args_list[0].kwargs["params"]["metrics"])
        self.assertNotIn("engagedViews", get.call_args_list[1].kwargs["params"]["metrics"])
        self.assertEqual(get.call_args.kwargs["params"]["filters"], "video==abcdefghijk")
        self.assertEqual(get.call_args.kwargs["params"]["ids"], "channel==MINE")

    def test_retention_and_public_stats(self):
        ret = Resp(200, {"rows": [[0.01, 1.2], [0.02, 0.9]]})
        with mock.patch.object(youtube.requests, "get", return_value=ret):
            self.assertEqual(youtube.analytics_retention("v", "a", "b", "AT"), [(0.01, 1.2), (0.02, 0.9)])
        pub = Resp(200, {"items": [{"id": "v1", "statistics": {"viewCount": "15", "likeCount": "2"}}]})
        with mock.patch.object(youtube.requests, "get", return_value=pub):
            self.assertEqual(youtube.public_stats(["v1", "v2"], "KEY"),
                             {"v1": {"views": 15, "likes": 2, "comments": 0}})


class WeeklyRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "specs").mkdir()
        cfgp = root / "channel.yaml"
        cfgp.write_text(yaml.safe_dump({"channel": {"name": "K", "description": "d"},
                                        "scoring_weights": dict(WEIGHTS)}), encoding="utf-8")
        for target, attr, val in [(db, "DB_PATH", root / "t.db"), (weekly, "CONFIG_PATH", cfgp),
                                  (weekly, "SPEC_DIR", root / "specs"),
                                  (learned, "LEARNED_PATH", root / "learned.yaml"),
                                  (youtube, "TOKEN_PATH", root / "no_token.json")]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.msgs = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.msgs.append(t) or 1)
        p.start(); self.addCleanup(p.stop)
        # agent Hiểu YouTube / Tin YouTube gọi mạng thật (Analytics, RSS) — có test riêng (test_yt_agents)
        for target in ("src.yt_news.fetch_feeds", "src.yt_insights.update", "src.analysis.big_channels.update",
                       "src.fb_insights.update", "src.ig_insights.update", "src.backup.send_weekly",
                       "src.publish.playlists.backfill"):
            p = mock.patch(target, return_value=[]); p.start(); self.addCleanup(p.stop)
        self.root, self.con = root, db.connect()
        self.addCleanup(self.con.close)

    def video(self, n, days_ago=10, pct=None, views=100, scores=None):
        scores = scores or {c: 4 for c in weekly.CRITERIA}
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,scores) VALUES (?,?,?,?,?)",
                         (n, f"t{n}", f"t{n}", f"u{n}", json.dumps(scores)))
        self.con.execute("INSERT INTO scripts (id,idea_id,status) VALUES (?,?,'verified')", (n, n))
        pub = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
        self.con.execute("INSERT INTO videos (id,script_id,file,title,status,youtube_id,published_at)"
                         " VALUES (?,?,?,?,'published',?,?)", (n, n, "f", f"Video {n}", f"yt{n:09d}", pub))
        self.con.commit()
        if views is not None:
            db.save_video_stats(self.con, n, "analytics" if pct else "public",
                                {"views": views, "avg_view_pct": pct})

    def test_real_run_updates_learning_and_dry_run_does_not(self):
        # ca thật 20/11: khi thêm agent Hiểu YouTube, hai bước tự học lọt vào nhánh dry_run -> lượt Chủ nhật thật
        # không cập nhật sở thích người xem lẫn học cách dựng
        self.video(1, pct=60.0)
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}), \
                mock.patch("src.learning.update_preferences", return_value={}) as prefs, \
                mock.patch("src.style.update", return_value=[]) as style_up:
            weekly.run_weekly(now=NOW)
            self.assertEqual((prefs.call_count, style_up.call_count), (1, 1))
            weekly.run_weekly(dry_run=True, now=NOW)
            self.assertEqual((prefs.call_count, style_up.call_count), (1, 1))

    def test_few_videos_report_honestly_and_change_nothing(self):
        self.video(1, pct=60.0); self.video(2, days_ago=1, pct=90.0)     # video 2 còn quá mới
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}, clear=False), \
             mock.patch("src.analysis.weekly.synthesize_insights") as llm:
            report = weekly.run_weekly(now=NOW)
        llm.assert_not_called()                                          # < 3 video -> không gọi LLM
        self.assertIn("2 video đã đăng, 1 video đủ", report)
        self.assertIn("Chưa chỉnh trọng số: mới có 1/10", report)
        self.assertFalse((self.root / "learned.yaml").exists())
        self.assertEqual(self.msgs, [report])

    def test_public_fallback_stores_stats(self):
        self.video(1, views=None)
        pub = {"yt000000001": {"views": 321, "likes": 4, "comments": 1}}
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": "K"}), \
             mock.patch.object(youtube, "public_stats", return_value=pub):
            report = weekly.run_weekly(now=NOW)
        self.assertIn("321 xem", report)
        self.assertIn("chưa có % xem", report)
        row = self.con.execute("SELECT source, views FROM video_stats").fetchone()
        self.assertEqual((row["source"], row["views"]), ("public", 321))

    def test_analytics_path_with_retention_insights_and_learning(self):
        for n in range(1, 13):               # 12 video: curiosity càng cao % xem càng cao
            sc = {c: 4 for c in weekly.CRITERIA}; sc["curiosity"] = n
            self.video(n, views=None, scores=sc)
        (self.root / "specs" / "script_1_final.yaml").write_text(yaml.safe_dump(
            [{"template": "intro", "seconds": 2}, {"template": "statement", "seconds": 8, "voice": "hook"},
             {"template": "bar_chart", "seconds": 10, "voice": "lời cảnh 3"},
             {"template": "big_number", "seconds": 20, "voice": "lời cảnh 4"}], allow_unicode=True),
            encoding="utf-8")
        (self.root / "no_token.json").write_text("{}")
        ret = [(i / 20, 1.0 - 0.01 * i - (0.25 if i >= 7 else 0)) for i in range(1, 21)]

        def video_stats(vid, start, end, token):
            n = int(vid[2:])
            return {"views": 100 * n, "likes": n, "averageViewPercentage": 40.0 + n,
                    "averageViewDuration": 30, "subscribersGained": 1, "engagedViews": 43 * n}
        snap = {"date": "2026-11-15", "subscribers": 312, "views_28d": 18420, "shorts_views_28d": 17170,
                "long_hours_28d": 37.0, "net_subs_28d": 41, "shorts_views_90d": 25000, "long_hours_365d": 37.0}
        with mock.patch.dict(os.environ, {"YT_CLIENT_ID": "c", "YT_CLIENT_SECRET": "s"}), \
             mock.patch("src.growth.snapshot", return_value=snap), \
             mock.patch.object(youtube, "access_token", return_value="AT"), \
             mock.patch.object(youtube, "analytics_video", side_effect=video_stats), \
             mock.patch.object(youtube, "analytics_retention",
                               side_effect=lambda vid, *a: ret if vid.endswith("1") and not vid.endswith("11") else []), \
             mock.patch("src.analysis.weekly.synthesize_insights", return_value=["Video #12: hook có số giữ chân tốt"]):
            report = weekly.run_weekly(now=NOW)
        self.assertIn("Nguồn: YouTube Analytics", report)
        self.assertIn("rớt mạnh nhất ở giây 14.0 (cảnh 3, bar_chart)", report)
        self.assertIn("qua vài giây đầu 43%", report)                # engaged views / views
        self.assertIn("Người xem mất đi theo loại cảnh", report)
        self.assertIn("curiosity: 1.0 → 1.1", report)
        self.assertLess(report.index("#12 "), report.index("#1 Video 1 "))      # xếp theo % xem giảm dần
        # agent Tăng trưởng: số liệu cả kênh + tiến độ YPP + dự báo (+41 sub / 28 ngày -> ~67 tuần tới 1.000)
        self.assertIn("Người đăng ký: 312 (+41 trong 28 ngày)", report)
        self.assertIn("Tiến độ YPP: sub 312/1.000", report)
        self.assertIn("sau khoảng 67 tuần", report)
        self.assertEqual(learned.load_learned()["growth"]["latest"]["subscribers"], 312)
        saved = learned.load_learned()
        self.assertEqual(saved["scoring_weights"]["curiosity"], 1.1)
        self.assertEqual(saved["insights"], ["Video #12: hook có số giữ chân tốt"])
        self.assertEqual(saved["based_on_videos"], 12)
        # các agent khác đọc được thứ vừa học
        cfg = learned.apply_learned({"scoring_weights": dict(WEIGHTS)})
        self.assertEqual(cfg["scoring_weights"]["curiosity"], 1.1)
        from src import crew
        with mock.patch("src.analysis.formula.load_formula", return_value=None):
            self.assertIn("Video #12: hook có số giữ chân tốt", crew._formula_block())

    def test_apply_learned_ignores_unknown_keys(self):
        learned.save_learned({"scoring_weights": {"curiosity": 1.3, "hack": 99, "novelty": "x"}})
        cfg = learned.apply_learned({"scoring_weights": dict(WEIGHTS)})
        self.assertEqual(cfg["scoring_weights"]["curiosity"], 1.3)
        self.assertNotIn("hack", cfg["scoring_weights"])
        self.assertEqual(cfg["scoring_weights"]["novelty"], 1.0)

    def test_dry_run_touches_nothing(self):
        self.video(1, pct=55.0)
        with mock.patch("builtins.print"), mock.patch.object(weekly, "fetch_and_store") as fetch:
            report = weekly.run_weekly(dry_run=True, now=NOW)
        fetch.assert_not_called()
        self.assertIn("số liệu đã lưu", report)
        self.assertEqual(self.msgs, [])
        self.assertFalse((self.root / "learned.yaml").exists())


if __name__ == "__main__":
    unittest.main()
