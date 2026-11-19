"""Test học CÁCH DỰNG video (src/style.py) — không gọi mạng, không gọi LLM, không render.

    python -m unittest tests.test_style -v
"""
import json
import logging
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from src import assemble, db, learning, review, style
from src import telegram_bot as tg
from src.analysis import learned

OWNER = "12345"


class StyleCase(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, attr, val in [(db, "DB_PATH", self.root / "t.db"),
                                  (learned, "LEARNED_PATH", self.root / "learned.yaml")]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)

    def stats(self, knob, groups, mean=50.0, sd=10.0):
        """learned.yaml giả: số liệu từng mức của một núm {giá trị: (n, % xem TB)}."""
        data = style._data()
        data["stats"] = {"metric": "avg_view_pct", "based_on": sum(n for n, _ in groups.values()), "mean": mean,
                         "sd": sd, "knobs": {knob: {style._key(v): {"n": n, "mean": m} for v, (n, m) in groups.items()}}}
        style._save(data)


class ArmsTest(StyleCase):
    def test_default_windows_keep_todays_look_as_one_of_the_arms(self):
        self.assertEqual(style.arms("tempo"), [1.0, 1.05, 1.1])
        self.assertEqual(style.arms("music"), [-3.0, 0.0, 3.0])
        self.assertEqual(style.arms("pace"), [3.0, 3.5, 4.0])           # trước 19/11: tối đa 4 giây/hình
        self.assertEqual(style.arms("captions"), [80.0, 88.0, 96.0])    # trước 19/11: phụ đề 80 px
        self.assertEqual(style.fmt("tempo", 1.05), "×1,05")
        self.assertEqual(style.fmt("music", -3), "-3 dB")
        self.assertEqual(style.fmt("music", 0), "0 dB")
        self.assertEqual(style.fmt("pace", 3.5), "3,5 giây")

    def test_hard_limits_are_never_crossed(self):
        for _ in range(5):
            style.shift("tempo", +1)
        self.assertEqual(style.arms("tempo"), [1.07, 1.12])             # kẹp ở ×1,12 (assemble.MAX_TEMPO)
        for _ in range(9):
            style.shift("captions", -1)
        self.assertEqual(style.arms("captions"), [72.0, 80.0])


class AssignTest(StyleCase):
    def test_assigned_once_reproducible_and_inside_the_window(self):
        st = style.assign(self.con, 7)
        self.assertEqual(style.assign(self.con, 7), st)                 # dựng lại: y hệt
        for knob, v in st.items():
            self.assertIn(v, style.arms(knob))
        self.assertEqual(style.get(self.con, 7)["applied"], {})
        legacy = style.assign(self.con, 8, legacy_spec=True)
        self.assertIsNone(legacy["pace"])                               # spec cũ: không thử nhịp cảnh

    def test_without_data_it_is_a_fair_random_experiment(self):
        counts = Counter(style.assign(self.con, sid)["tempo"] for sid in range(1, 301))
        self.assertEqual(set(counts), {1.0, 1.05, 1.1})
        self.assertTrue(all(c >= 70 for c in counts.values()), counts)

    def test_better_arm_is_chosen_more_but_others_are_still_tried(self):
        self.stats("tempo", {1.0: (6, 40.0), 1.05: (6, 50.0), 1.1: (6, 62.0)})
        counts = Counter(style.assign(self.con, sid)["tempo"] for sid in range(1, 301))
        self.assertGreater(counts[1.1], 180)
        self.assertGreater(counts[1.0] + counts[1.05], 0)              # vẫn thăm dò

    def test_paused_or_disabled_uses_the_window_center(self):
        style.set_paused(True)
        self.assertEqual(style.assign(self.con, 1),
                         {"tempo": 1.05, "music": 0.0, "pace": 3.5, "captions": 88.0})
        style.set_paused(False)
        off = {"style": {"experiments": False}}
        self.assertEqual(style.assign(self.con, 2, off)["captions"], 88.0)

    def test_broken_memory_means_default_video_not_a_crash(self):
        (self.root / "learned.yaml").write_text("style: [oops", encoding="utf-8")
        self.assertIn(style.assign(self.con, 3)["tempo"], [1.0, 1.05, 1.1])
        broken = mock.Mock(execute=mock.Mock(side_effect=RuntimeError("db hỏng")))
        self.assertEqual(style.assign(broken, 4), {})                   # = dựng như mặc định

    def test_pacing_reaches_the_producer_config_without_touching_the_original(self):
        cfg = {"pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4, "words_per_second": 3.4}}
        got = style.with_pacing(cfg, {"pace": 3.0})
        self.assertEqual(got["pacing"]["scene_seconds_max"], 3.0)
        self.assertEqual(cfg["pacing"]["scene_seconds_max"], 4)
        self.assertIs(style.with_pacing(cfg, {"pace": None}), cfg)


class ProduceTest(StyleCase):
    def test_new_spec_uses_and_records_the_assigned_pace(self):
        import sys
        import yaml
        from src import crew, produce
        voice = "Năm 2024 Việt Nam có 12 triệu thuê bao."
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,summary,source_name)"
                         " VALUES (1,'t','t','u','tóm tắt','S')")
        self.con.execute("INSERT INTO scripts (id,idea_id,body,status) VALUES (5,1,?,'verified')",
                         (yaml.safe_dump([{"voice": voice}], allow_unicode=True),))
        self.con.commit()
        seen = {}

        def fake_design(idea, scenes, cfg, log_problems=None, lessons=""):
            seen["pace"] = cfg["pacing"]["scene_seconds_max"]
            return [{"template": "statement", "seconds": 3, "voice": voice, "params": {"text": "12 triệu"}}]
        (self.root / "specs").mkdir()
        with mock.patch.object(crew, "design_scenes", fake_design), \
                mock.patch.object(produce, "SPEC_DIR", self.root / "specs"), \
                mock.patch.object(sys, "argv", ["produce", "5", "--spec-only"]), mock.patch("builtins.print"):
            produce.main()
        st = style.get(self.con, 5)
        self.assertIn(st["assigned"]["pace"], style.arms("pace"))
        self.assertEqual(seen["pace"], st["assigned"]["pace"])          # agent Sản xuất nhận đúng nhịp
        self.assertEqual(st["applied"]["pace"], st["assigned"]["pace"])  # và được ghi lại để so


class TempoTest(unittest.TestCase):
    def test_style_tempo_applies_only_when_the_video_stays_long_enough(self):
        total = lambda t: 54.0 / t                                      # 54 giây ở tốc độ gốc
        self.assertEqual(assemble.styled_tempo(1.0, 1.1, total, 45), 1.1)
        self.assertEqual(assemble.styled_tempo(1.0, 1.1, total, 50), 1.0)    # 49,1 giây < 50: không
        self.assertEqual(assemble.styled_tempo(1.08, 1.05, total, 45), 1.08)  # cần nhanh hơn để vừa khung
        self.assertEqual(assemble.styled_tempo(1.0, None, total, 45), 1.0)
        self.assertEqual(assemble.styled_tempo(1.0, 1.3, total, 45), assemble.MAX_TEMPO)


class WeeklyLearningTest(StyleCase):
    def video(self, sid, metric, **applied):
        """Một video đã đo: phong cách được gán = đã dùng (trừ khi truyền applied khác)."""
        assigned = {"tempo": 1.05, "music": 0.0, "pace": 3.5, "captions": 88.0}
        assigned.update({k: v for k, v in applied.items() if not k.startswith("real_")})
        real = dict(assigned, **{k[5:]: v for k, v in applied.items() if k.startswith("real_")})
        self.con.execute("INSERT INTO video_styles (script_id, assigned, applied, at) VALUES (?,?,?,'x')",
                         (sid, json.dumps(assigned), json.dumps(real)))
        self.con.commit()
        return {"script_id": sid, "avg_view_pct": metric}

    def test_compares_arms_and_drops_videos_that_did_not_get_their_arm(self):
        rows = [self.video(1, 60.0, tempo=1.1), self.video(2, 40.0, tempo=1.0),
                self.video(3, 50.0, tempo=1.05),
                self.video(4, 99.0, tempo=1.0, real_tempo=1.083),    # giọng chậm: phải đọc nhanh hơn mức gán
                {"script_id": 5, "avg_view_pct": 70.0},              # video đời trước thử nghiệm
                {"script_id": 1, "avg_view_pct": None}]
        self.assertEqual(style.update(self.con, rows), [])
        stats = learned.load_learned()["style"]["stats"]
        self.assertEqual(stats["based_on"], 4)
        self.assertEqual(stats["knobs"]["tempo"], {"1": {"n": 1, "mean": 40.0}, "1.05": {"n": 1, "mean": 50.0},
                                                   "1.1": {"n": 1, "mean": 60.0}})
        self.assertEqual(stats["knobs"]["captions"]["88"]["n"], 4)    # các núm khác của video 4 vẫn tính

    def test_too_few_videos_change_nothing(self):
        style.update(self.con, [self.video(1, 60.0), self.video(2, 40.0)])
        self.assertFalse((self.root / "learned.yaml").exists())

    def test_window_moves_toward_a_clear_winner_but_never_against_du(self):
        rows = ([self.video(k, 64.0 + k % 2, tempo=1.1) for k in range(1, 6)]
                + [self.video(k, 45.0 + k % 2, tempo=1.05) for k in range(6, 11)]
                + [self.video(k, 44.0, tempo=1.0) for k in range(11, 13)])
        notes = style.update(self.con, rows)
        self.assertEqual(style.arms("tempo"), [1.05, 1.1, 1.12])        # tự dời khung lên một nấc
        self.assertEqual(len(notes), 1)
        self.assertIn("Tốc độ đọc: tự dời khung về ×1,10", notes[0])
        history = learned.load_learned()["style"]["history"]
        self.assertEqual((history[-1]["knob"], history[-1]["by"]), ("tempo", "tự học"))
        # Du chê đọc nhanh: khung lùi xuống và việc tự học không được kéo lên lại
        style.shift("tempo", -1)
        self.assertEqual(style.update(self.con, rows), [])
        self.assertEqual(style.arms("tempo"), [1.0, 1.05, 1.1])

    def test_small_differences_do_not_move_the_window(self):
        # chênh 1 điểm % giữa hai mức trong khi mỗi video lệch nhau cả chục điểm: chưa nói được gì
        rows = ([self.video(k, v, music=3.0) for k, v in zip(range(1, 6), (40, 62, 51, 45, 57))]
                + [self.video(k, v, music=0.0) for k, v in zip(range(6, 11), (60, 38, 52, 47, 53))])
        self.assertEqual(style.update(self.con, rows), [])
        self.assertEqual(style.arms("music"), [-3.0, 0.0, 3.0])


class ProductionTest(StyleCase):
    def test_scene_types_and_openings_viewers_responded_to(self):
        rows = [{"losses": [("statement", 12.0, 0.09), ("bar_race", 10.0, 0.02)], "opening": "line_chart",
                 "engaged_pct": 55},
                {"losses": [("statement", 10.0, 0.06), ("bar_race", 12.0, 0.03)], "opening": "big_number",
                 "engaged_pct": 40},
                {"losses": [("statement", 8.0, 0.05), ("map", 30.0, 0.03)], "opening": "line_chart",
                 "engaged_pct": 51},
                {"losses": [], "opening": "big_number", "engaged_pct": 36}]
        prod = style.production_prefs(rows)
        self.assertEqual(prod["based_on"], 3)
        self.assertEqual(prod["template_loss"]["statement"], {"loss10": 6.7, "seconds": 30.0, "videos": 3})
        self.assertNotIn("map", prod["template_loss"])                 # mới 1 video: chưa nói gì
        self.assertEqual(prod["opening"]["line_chart"], {"n": 2, "engaged": 53.0})
        block = style.production_block({"production": prod})
        self.assertIn("rời đi nhanh nhất: \"statement\"", block)
        self.assertIn("giữ chân tốt nhất: \"bar_race\"", block)
        self.assertLess(block.index("\"line_chart\" giữ 53%"), block.index("\"big_number\" giữ 38%"))
        self.assertEqual(style.production_block({}), "")
        # agent Sản xuất đọc được (qua learning.producer_lessons)
        style.update(self.con, rows)
        self.assertIn("rời đi nhanh nhất: \"statement\"", learning.producer_lessons(self.con))


class TelegramTest(StyleCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        p = mock.patch.object(tg, "send_message", side_effect=lambda t, **k: self.sent.append(t) or 1)
        p.start(); self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": OWNER}); env.start(); self.addCleanup(env.stop)

    def say(self, text, user=OWNER):
        review.handle_update(self.con, {"update_id": 1, "message": {
            "message_id": 9, "chat": {"id": int(user)}, "from": {"id": int(user)}, "text": text}}, {})
        return self.sent[-1] if self.sent else ""

    def test_du_steers_with_or_without_diacritics(self):
        self.assertIn("Phong cách dựng đang thử", self.say("/kieu"))
        self.assertIn("Nhạc nền: khung thử mới -6 dB · -3 dB · 0 dB", self.say("/Nhạc  nhỏ"))
        self.assertIn("khung thử mới ×1,05 · ×1,10 · ×1,12", self.say("/giong nhanh"))
        self.assertIn("khung thử mới 2,5 giây · 3 giây · 3,5 giây", self.say("/nhịp nhanh"))
        self.assertEqual(style.arms("music"), [-6.0, -3.0, 0.0])
        self.assertIn("Lệnh chỉnh cách dựng", self.say("/nhac"))
        self.assertIn("Tạm dừng thử nghiệm", self.say("/kiểu tắt"))
        self.assertIn("TẠM DỪNG", self.say("/kieu"))
        self.say("/kieu bat")
        self.assertFalse(style._data()["paused"])

    def test_limits_and_strangers(self):
        for _ in range(4):
            self.say("/chu to")
        self.assertIn("đã ở giới hạn an toàn", self.say("/chu to"))
        before = style.arms("music")
        n = len(self.sent)
        self.say("/nhac to", user="999")                                # người lạ: không làm gì
        self.assertEqual((style.arms("music"), len(self.sent)), (before, n))


class BuildErrorTest(StyleCase):
    def test_qc_failures_become_lessons_or_code_alerts(self):
        self.assertEqual(learning.kind_of("Hình khớp lời (AI soát): 12s [clipped]: chữ bị cắt ở mép"), "qc_chu_tran")
        self.assertEqual(learning.kind_of("Hình khớp lời (AI soát): 30s [number]: hình ghi 54.000"), "qc_hinh_lech")
        self.assertEqual(learning.kind_of("Độ dài: 96.3s"), "qc_do_dai")
        self.assertEqual(learning.kind_of("Remotion lỗi: CalledProcessError: exit 1"), "render_loi")
        # gửi duyệt mà Kiểm định trượt -> ghi vào bộ nhớ
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url) VALUES (1,'t','t','u')")
        self.con.execute("INSERT INTO scripts (id,idea_id,hooks,body,status) VALUES (6,1,'[]','- voice: x','verified')")
        self.con.commit()
        (self.root / "output").mkdir()
        (self.root / "output" / "final_6.mp4").write_bytes(b"x")
        checks = [{"name": "Độ dài", "value": "50.0s", "ok": True},
                  {"name": "Hình khớp lời (AI soát)", "value": "12s [clipped]: chữ bị cắt", "ok": False},
                  {"name": "Khung hình đen", "value": "2 đoạn", "ok": False}]
        from src import qc
        with mock.patch.object(review, "OUTPUT", self.root / "output"), \
                mock.patch.object(qc, "collect_checks", return_value=checks), mock.patch("builtins.print"):
            self.assertIsNone(review._send_for_review({}, self.con, 6, force=False, skip_qc=False))
        kinds = [r[0] for r in self.con.execute("SELECT kind FROM learning_events WHERE stage='qc'")]
        self.assertEqual(kinds, ["qc_chu_tran", "qc_khung_den"])
        lessons = learning.producer_lessons(self.con)
        self.assertIn("chữ tràn/bị cắt", lessons)                       # Sản xuất sửa được -> vào lời dặn
        self.assertNotIn("khung hình đen", lessons)                     # lỗi code -> chỉ báo cáo
        self.assertIn("có khung hình đen — 1 lần (lỗi phía code — cần sửa tay)",
                      "\n".join(learning.weekly_lines(self.con)))


class ReportTest(StyleCase):
    def test_weekly_section(self):
        text = "\n".join(style.weekly_lines(self.con))
        self.assertIn("🎬 Học cách dựng", text)
        self.assertIn("đang thử: tốc độ đọc ×1,00 / ×1,05 / ×1,10".lower(), text.lower())
        self.stats("tempo", {1.0: (3, 41.0), 1.05: (2, 55.0)})
        text = "\n".join(style.weekly_lines(self.con, notes=["Tốc độ đọc: tự dời khung"]))
        self.assertIn("Tốc độ đọc: ×1,00 41% (n=3) · ×1,05 55% (n=2)", text)
        self.assertIn("↪ Tốc độ đọc: tự dời khung", text)
        self.assertIn("dẫn: ×1,05 (55% thời lượng được xem, 2 video)", style.status_text())


if __name__ == "__main__":
    unittest.main()
