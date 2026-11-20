"""Test bộ nhớ TỰ HỌC (src/learning.py) — không gọi mạng, không gọi LLM.

    python -m unittest tests.test_learning -v
"""
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

from src import claims, crew, daily, db, learning, story
from src.analysis import learned
from src.sources import datatable as dt
from tests.test_claims import RACE, WOMEN
from tests.test_daily import CFG as DAILY_CFG, DailyCase
from tests.test_stage1 import CFG, script


def kinds(problems) -> set:
    return {learning.kind_of(p) for p in problems}


class KindTest(unittest.TestCase):
    """Lời báo lỗi THẬT của các cổng code (gọi chính các cổng, không chép tay câu chữ) được phân đúng
    loại. Đổi câu chữ một cổng mà quên cập nhật learning.KINDS thì test này đỏ."""

    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_content_gates(self):
        cases = {
            "so_sanh": "Hàn Quốc năm 2025 mới đạt tỷ lệ phụ nữ đi làm mà Việt Nam đã có từ năm 1990.",
            "xu_huong": "Trái lại, Hàn Quốc liên tục tăng trưởng từ 1990 đến năm 2025.",
            "nguyen_nhan": "Sự mở cửa đã thu hút phụ nữ đi làm.",
            "diem_phan_tram": "Năm 2025, tỷ lệ phụ nữ Việt Nam đi làm vẫn cao hơn Hàn Quốc 11,8%.",
        }
        for kind, voice in cases.items():
            got = crew.content_problems({"scenes": [{"voice": "Năm 1990 Việt Nam đạt 74,7%."},
                                                    {"voice": voice}]}, WOMEN)
            self.assertTrue(got, voice)
            self.assertEqual(kinds(got), {kind}, got)
        why = crew.content_problems({"scenes": [{"voice": "Vì sao phụ nữ Việt Nam đi làm nhiều hơn?"}]}, WOMEN)
        self.assertEqual(kinds(why), {"hook_vi_sao"})

    def test_wording_gates(self):
        for kind, voice in (("du_bao", "Năm 2025, quy mô kinh tế Việt Nam dự kiến đạt 515 tỷ USD."),
                            ("lich_su", "Giai đoạn 1990 đến 1995 tăng nhanh nhất lịch sử."),
                            ("nam_vuot", "Trung Quốc từ hạng 2 năm 1990 đã soán ngôi Nhật Bản năm 2025.")):
            got = claims.wording_problems([voice], RACE)
            self.assertIn(kind, kinds(got), got)

    def test_quoted_sentence_does_not_decide_the_kind(self):
        # câu bị trích nói "so sánh"/"lịch sử" nhưng lỗi là nguyên nhân
        got = claims.cause_claims(["Nhờ chính sách so sánh lịch sử, tỷ lệ tăng."], WOMEN)
        self.assertEqual(kinds(got), {"nguyen_nhan"})

    def test_script_gates(self):
        def check(kind, mutate=None, base=None, **kw):
            s = base or script()
            if mutate:
                mutate(s["scenes"])
            got = crew.script_problems(s, CFG, **kw)
            self.assertIn(kind, kinds(got), got)

        check("so_canh", base=script(scenes=5, words_each=40))
        check("so_tu", base=script(scenes=12, words_each=10))
        check("it_so", base=script(numbers=2))
        check("so_viet_chu", lambda sc: sc[5].update(voice="bảy mươi ba phần trăm " + "từ " * 10))
        check("moc_nam", lambda sc: [sc[k].update(voice=f"Năm {y}, Việt Nam đạt {100 + k} kWh từ từ")
                                     for k, y in enumerate(range(1990, 2025, 5))])
        check("doc_bang", lambda sc: [sc[k].update(voice=f"{500 + k} " + "từ " * 13) for k in (1, 3, 5)])
        check("dinh_nghia", lambda sc: sc[1].update(voice="Chỉ số này đo tỷ lệ người dân dùng điện mỗi năm"))
        check("hai_cau_khong_so", lambda sc: sc[2].update(voice="từ " * 14))
        check("cau_dem", lambda sc: sc[1].update(voice="Chiếc điện thoại trong tay bạn là một phần của hạ tầng"))
        check("lui_qua_khu", lambda sc: sc[1].update(voice="Nhìn lại năm 1960, mọi thứ còn rất khác từ từ"))
        check("cau_ket", lambda sc: sc[-1].update(voice="từ " * 14))
        check("hook_cam", lambda sc: sc[0].update(voice="Đừng bỏ qua con số 1000 này nữa từ từ từ"))
        hook = script()["scenes"][0]["voice"]
        check("hook_lap", recent_openers=[story.opener(hook)])

    def test_fact_check_feedback_lines(self):
        # dòng phản hồi main._script_one ghi vào bộ nhớ (bỏ "- " đầu dòng)
        self.assertEqual(learning.kind_of("SAI: Việt Nam gấp 3 lần -> nguồn ghi 2,5 lần"), "kiem_chung")
        self.assertEqual(learning.kind_of('SAI (cảnh 4): "Vì sao lịch sử…" -> trái nguồn'), "kiem_chung")
        self.assertEqual(learning.kind_of("BỊA SỐ: con số 99% trong lời đọc không có trong bài nguồn"), "bia_so")
        self.assertEqual(learning.kind_of("SAI/KHÔNG CÓ CĂN CỨ: câu “x” nói Hàn Quốc tăng liên tục nhưng"
                                          " bảng ghi 2005: 50,7 → 2010: 49,8"), "xu_huong")
        self.assertEqual(learning.kind_of("một lỗi chưa ai đặt tên"), "khac")


class SpecLessonTest(unittest.TestCase):
    """Agent Sản xuất: lỗi spec được ghi lại và bài học vào prompt lần sau."""
    from tests.test_produce import DesignScenesTest as _D

    def test_fabricated_chart_is_logged_and_lessons_reach_the_prompt(self):
        D = self._D
        bad = [{"template": "line_chart", "seconds": 4, "voice": D.SCENES[0]["voice"],
                "params": {"title": "Việt Nam", "xs": [2000, 2025], "ys": [404, 9999]}},
               {"template": "big_number", "seconds": 4, "voice": D.SCENES[1]["voice"],
                "params": {"title": "Hàn Quốc", "value": 36227}},
               {"template": "statement", "seconds": 4, "voice": D.SCENES[2]["voice"], "params": {"text": "x"}}]
        prompts, logged = [], []

        def fake(role, goal, description, expected_output):
            prompts.append(description)
            return json.dumps(bad)
        idea = dict(D.IDEA, summary="GDP đầu người năm 2000 là 404 USD.")      # bài báo: không tự điền số
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        with mock.patch.object(crew, "_run_single_task", fake):
            crew.design_scenes(idea, D.SCENES, D.CFG, log_problems=lambda p, stage: logged.append((stage, p)),
                               lessons="\nLỖI SẢN XUẤT HAY MẮC: ví dụ\n")
        self.assertIn("LỖI SẢN XUẤT HAY MẮC", prompts[0])
        self.assertEqual({stage for stage, _ in logged}, {"spec"})
        self.assertIn("spec_bia_so", kinds(p for _, ps in logged for p in ps))


class MemoryCase(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, attr, val in [(db, "DB_PATH", self.root / "t.db"),
                                  (learned, "LEARNED_PATH", self.root / "learned.yaml")]:
            p = mock.patch.object(target, attr, val); p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)


class MistakesTest(MemoryCase):
    def test_most_frequent_first_with_latest_example_and_per_agent(self):
        learning.record_problems(self.con, ["chỉ 2 con số trong lời đọc (cần ít nhất 5)"], "writer", 1)
        learning.record_problems(self.con, ["chỉ 3 con số trong lời đọc (cần ít nhất 5)",
                                            "một lỗi chưa ai đặt tên"], "writer", 2)
        learning.record_problems(self.con, ["BỊA SỐ: con số 99% trong lời đọc không có trong bài nguồn"],
                                 "final", 2)
        learning.record_problems(self.con, ["BỊA SỐ LIỆU: các số [9999] không có trong kịch bản"], "spec", 2)
        self.assertEqual([(k, c) for k, c, _ in learning.top_mistakes(self.con)], [("it_so", 2), ("bia_so", 1)])
        block = learning.mistakes_block(self.con)
        self.assertLess(block.index("quá ít con số (2 lần)"), block.index("không có trong nguồn"))
        self.assertIn("chỉ 3 con số", block)                       # ví dụ là lần GẦN NHẤT
        self.assertNotIn("BỊA SỐ LIỆU", block)                     # lỗi spec không dạy Biên kịch
        self.assertNotIn("chưa ai đặt tên", block)                 # 'khac' không đưa vào prompt
        producer = learning.producer_lessons(self.con)
        self.assertIn("LỖI SẢN XUẤT", producer)
        self.assertIn("biểu đồ có số không có trong kịch bản", producer)
        self.assertNotIn("con số trong lời đọc", producer)

    def test_backfill_from_saved_fact_check_records_once(self):
        day = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        fc = json.dumps({"pass": True, "standard_problems": ["chỉ 2 con số trong lời đọc (cần ít nhất 5)",
                                                              "con số không có trong bài nguồn: 99%"]})
        for sid, factcheck, at in ((1, fc, day), (2, fc, old), (3, "không phải json", day), (4, "[]", day)):
            self.con.execute("INSERT INTO scripts (id, idea_id, status, factcheck, created_at)"
                             " VALUES (?, ?, 'draft', ?, ?)", (sid, sid, factcheck, at))
        self.con.commit()
        self.assertEqual(learning.backfill(self.con), 2)
        self.assertEqual(learning.backfill(self.con), 0)                       # chỉ nạp một lần
        self.assertEqual({k for k, _, _ in learning.top_mistakes(self.con)}, {"it_so", "bia_so"})
        self.assertEqual([r[0] for r in self.con.execute("SELECT DISTINCT at FROM learning_events")], [day])

    def test_old_mistakes_are_forgotten(self):
        old = (datetime.now(timezone.utc) - timedelta(days=learning.LESSON_DAYS + 1)).isoformat(timespec="seconds")
        self.con.execute("INSERT INTO learning_events (at, source, kind, stage, detail)"
                         " VALUES (?, 'gate', 'it_so', 'writer', 'cũ')", (old,))
        self.con.commit()
        self.assertEqual(learning.mistakes_block(self.con), "")

    def test_memory_failure_never_breaks_the_pipeline(self):
        self.con.execute("DROP TABLE learning_events")
        learning.record(self.con, "gate", "it_so", "x", "writer")             # không ném lỗi
        (self.root / "learned.yaml").write_text("du_rules: [oops", encoding="utf-8")   # YAML hỏng
        self.assertEqual(learning.writer_lessons(self.con, {"source_name": "S"}, CFG), "")
        self.assertEqual(learning.producer_lessons(self.con), "")
        self.assertEqual(learning.rules(), [])
        self.assertEqual(learning.preference_bonus({"hook": "doi-lap"}), 0.0)
        with self.assertRaises(yaml.YAMLError):                             # dạy luật: báo lỗi, KHÔNG ghi đè
            learning.add_rule("luật mới")
        self.assertIn("oops", (self.root / "learned.yaml").read_text(encoding="utf-8"))


class RulesTest(MemoryCase):
    def test_add_dedupe_cap_and_remove(self):
        learning.add_rule("  Không dùng   từ “chúng ta”  ")
        learning.add_rule("không dùng từ “chúng ta”")                         # trùng (khác hoa/thường)
        self.assertEqual([r["text"] for r in learning.rules()], ["Không dùng từ “chúng ta”"])
        for k in range(learning.MAX_RULES + 3):
            learning.add_rule(f"luật {k}")
        rs = learning.rules()
        self.assertEqual(len(rs), learning.MAX_RULES)
        self.assertEqual(rs[-1]["text"], f"luật {learning.MAX_RULES + 2}")    # giữ luật MỚI nhất
        self.assertIsNone(learning.remove_rule(0))
        self.assertIsNone(learning.remove_rule(learning.MAX_RULES + 1))
        self.assertEqual(learning.remove_rule(1)["text"], rs[0]["text"])
        self.assertEqual(len(learning.rules()), learning.MAX_RULES - 1)
        # những thứ khác trong learned.yaml (trọng số, bài học tuần) không bị đụng
        data = learned.load_learned(); data["insights"] = ["bài học"]; learned.save_learned(data)
        learning.add_rule("luật cuối")
        self.assertEqual(learned.load_learned()["insights"], ["bài học"])

    def test_du_block_has_rules_and_recent_notes(self):
        self.assertEqual(learning.du_block(self.con), "")
        learning.add_rule("Kết video bằng một câu hỏi mở")
        for k in range(7):
            learning.record(self.con, "du", "note", f"nhận xét {k}", "review", script_id=k)
        block = learning.du_block(self.con)
        self.assertIn("LUẬT DU ĐÃ DẠY", block)
        self.assertIn("Kết video bằng một câu hỏi mở", block)
        self.assertIn("nhận xét 6", block)
        self.assertNotIn("nhận xét 1", block)                                 # chỉ 5 nhận xét gần nhất


class ViewerTest(MemoryCase):
    def test_hook_types(self):
        for text, want in (("Vì sao Hàn Quốc sinh ít con nhất thế giới dù giàu gấp 7 lần?", "cau-hoi"),
                           ("Việt Nam hôm nay mới bằng Hàn Quốc năm 1991.", "moc-thoi-gian"),
                           ("Trong 214 nước, Việt Nam đứng đúng chính giữa.", "thu-hang"),
                           ("Việt Nam đứng thứ 10 thế giới về xe điện.", "thu-hang"),
                           ("Hàn Quốc dùng điện gấp 5 lần Việt Nam — 30 năm trước thì ngược lại.", "doi-lap"),
                           ("Tỷ lệ dùng internet Việt Nam tăng từ 0,25% năm 2000 lên 84,2% năm 2024.", "doi-lap"),
                           ("Năm 2023 có 540.000 người Việt sống ở Hàn.", "khac"),
                           ("", "khac")):
            self.assertEqual(learning.hook_type(text), want, text)

    def test_video_kinds_follow_the_titles_the_sources_write(self):
        for title, source, want in (
                ("Bản đồ thế giới: điện tái tạo năm 2023 — Việt Nam thứ 25/180", dt.WB_SOURCE, "ban-do"),
                ("Bản đồ thế giới: lượng cà phê năm 2022", dt.OWID_SOURCE, "ban-do"),
                ("Cuộc đua GDP đầu người: 10 nền kinh tế châu Á", dt.WB_SOURCE, "cuoc-dua"),
                ("Người nước ngoài ở Hàn: cuộc đua theo quốc tịch từ 2015 đến 2024", dt.KOSIS_SOURCE, "cuoc-dua"),
                ("Điện tiêu thụ: Việt Nam và Hàn Quốc từ 1990 đến 2023", dt.WB_SOURCE, "bieu-do"),
                ("Bản đồ gen mới của lúa", "ScienceDaily", "bai-bao")):
            self.assertEqual(learning.video_kind(title, source), want, title)

    def add_video(self, n, hook, engaged_pct, views=1000, source=dt.WB_SOURCE, title="Chỉ số: A và B"):
        body = yaml.safe_dump([{"voice": hook}, {"voice": "câu hai"}], allow_unicode=True)
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,source_name) VALUES (?,?,?,?,?)",
                         (n, title, f"t{n}", f"u{n}", source))
        self.con.execute("INSERT INTO scripts (id,idea_id,body,status) VALUES (?,?,?,'verified')", (n, n, body))
        self.con.commit()
        return {"id": n, "script_id": n, "views": views, "engaged_pct": engaged_pct, "avg_view_pct": None}

    def test_learns_which_openings_hold_viewers_and_keeps_exploring(self):
        rows = ([self.add_video(k, "Hàn Quốc dùng điện gấp 5 lần Việt Nam.", 60 + k) for k in range(1, 4)]
                + [self.add_video(k, "Vì sao Việt Nam dùng ít điện?", 30 + k) for k in range(4, 7)]
                + [self.add_video(9, "Hàn Quốc gấp 3 lần?", None)])                # thiếu số liệu: bỏ qua
        prefs = learning.update_preferences(self.con, rows)
        self.assertEqual((prefs["metric"], prefs["based_on"]), ("engaged_pct", 6))
        hooks = prefs["hook"]
        self.assertEqual((hooks["doi-lap"]["n"], hooks["doi-lap"]["mean"]), (3, 62.0))
        # co về trung bình: điểm nằm giữa trung bình nhóm và trung bình chung (48,5)
        self.assertLess(hooks["doi-lap"]["score"], 62.0)
        self.assertGreater(hooks["doi-lap"]["score"], 48.5)
        self.assertEqual(learned.load_learned()["preferences"], prefs)            # đã lưu cho daily/hook
        good, bad = learning.hook_bonus("Việt Nam kém Hàn Quốc 4 lần."), learning.hook_bonus("Vì sao vậy?")
        self.assertGreater(good, bad)
        # kiểu chưa thử lần nào được thưởng thăm dò: hơn kiểu đã thử mà kém
        self.assertGreater(learning.hook_bonus("Việt Nam đứng thứ 10 thế giới."), bad)
        block = learning.viewer_block()
        self.assertIn("“doi-lap” giữ chân tốt nhất (62.0)", block)
        self.assertIn("“cau-hoi” kém nhất (35.0)", block)

    def test_hook_bonus_only_breaks_ties_between_hooks_that_follow_the_rules(self):
        prefs = {"metric": "engaged_pct", "based_on": 10, "mean": 40.0, "sd": 10.0,
                 "hook": {"thu-hang": {"n": 5, "mean": 70.0, "score": 65.0},
                          "doi-lap": {"n": 5, "mean": 20.0, "score": 25.0}}}
        bonus = lambda text: learning.hook_bonus(text, prefs)
        self.assertEqual(bonus("Việt Nam đứng thứ 10 trong 59 nước"), learning.HOOK_BONUS_CAP)
        current = "Hàn Quốc bán xe điện gấp 5 lần Việt Nam năm 2024"
        liked = "Việt Nam đứng thứ 10 trong 59 nước về xe điện"
        self.assertEqual(story.hook_score(current), story.hook_score(liked))          # ngang điểm luật
        tie = {"hooks": [liked], "scenes": [{"voice": current}]}
        self.assertEqual(story.pick_hook(dict(tie, scenes=[{"voice": current}])), current)   # chưa học: giữ
        self.assertEqual(story.pick_hook(tie, bonus=bonus), liked)                    # người xem thích hơn
        # kiểu được thích nhưng KHÔNG có con số thì không thắng được câu có số
        no_number = {"hooks": ["Việt Nam đứng chót bảng xe điện châu Á"], "scenes": [{"voice": current}]}
        self.assertEqual(story.pick_hook(no_number, bonus=bonus), current)

    def test_metric_falls_back_and_too_few_videos_teach_nothing(self):
        rows = [dict(self.add_video(k, "Hàn Quốc gấp 2 lần.", None, views=10 ** k)) for k in range(1, 5)]
        self.assertEqual(learning.update_preferences(self.con, rows)["metric"], "views")
        (self.root / "learned.yaml").unlink()
        self.assertEqual(learning.update_preferences(self.con, rows[:2]), {})
        self.assertFalse((self.root / "learned.yaml").exists())
        self.assertEqual(learning.preference_bonus({"hook": "doi-lap"}), 0.0)    # chưa học gì: không cộng
        self.assertEqual(learning.viewer_block(), "")


class SubjectHookTest(unittest.TestCase):
    """Câu mở đầu phải nói ĐANG ĐO CÁI GÌ — câu thật của các video đã đăng (19/11/2026)."""
    EV_HOOK = "Năm 2018 Việt Nam xếp chót bảng nhưng năm 2025 đã vượt qua Mỹ và Anh."         # #11: 35 lượt xem
    AGRI_HOOK = "Tỷ lệ lao động nông nghiệp Việt Nam năm 2025 gấp 4,91 lần Hàn Quốc."         # #10: 1.235 lượt

    def test_subject_is_read_from_summaries_and_idea_titles(self):
        ev = {"tô", "điện", "xe"}
        self.assertEqual(story.subject_words("Chỉ số: Tỷ lệ ô tô điện trong số xe mới bán (%). Nguồn: OWID"), ev)
        self.assertEqual(story.subject_words("Cuộc đua tỷ lệ ô tô điện trong số xe mới bán: Việt Nam và 9 nền"
                                             " kinh tế lớn"), ev)
        self.assertEqual(story.subject_words("Tỷ lệ lao động làm nông nghiệp: Việt Nam và Hàn Quốc từ 1991"),
                         {"lao", "động", "nông", "nghiệp"})
        self.assertEqual(story.subject_words("Bản đồ thế giới: điện tái tạo năm 2023 — Việt Nam thứ 25/180"),
                         {"điện", "tái", "tạo"})
        self.assertEqual(story.subject_words("Cuộc đua GDP bình quân đầu người: 10 nền kinh tế châu Á"), {"gdp"})
        self.assertEqual(story.subject_words('<img align="left" src="https://dimg.donga.com/x.jpg"> Sao lớn'), set())

    def test_the_real_hooks(self):
        ev = story.subject_words("Chỉ số: Tỷ lệ ô tô điện trong số xe mới bán (%).")
        self.assertFalse(story.names_subject(self.EV_HOOK, ev))
        self.assertTrue(story.names_subject(self.AGRI_HOOK, story.subject_words("Chỉ số: Tỷ lệ lao động làm nông nghiệp (%).")))
        self.assertFalse(story.names_subject("Việt Nam từng xếp hạng 10 trong mười nền kinh tế năm 1990.", {"gdp"}))  # #4
        self.assertTrue(story.names_subject("GDP đầu người Việt Nam năm 2025 là 5.066 USD.", {"gdp"}))
        self.assertTrue(story.names_subject("bất kỳ câu nào", set()))                     # bài báo: không xét

    def test_machine_prefers_the_hook_that_names_the_subject(self):
        clear = "Tỷ lệ ô tô điện Việt Nam từ 0% năm 2018 lên 40% năm 2025."
        self.assertEqual(story.hook_score(clear), story.hook_score(self.EV_HOOK))       # ngang điểm luật cũ
        ev = story.subject_words("Chỉ số: Tỷ lệ ô tô điện trong số xe mới bán (%).")
        self.assertEqual(story.pick_hook({"hooks": [clear], "scenes": [{"voice": self.EV_HOOK}]}), self.EV_HOOK)
        self.assertEqual(story.pick_hook({"hooks": [clear], "scenes": [{"voice": self.EV_HOOK}]}, subject=ev), clear)

    def test_viewer_learning_tracks_the_hypothesis(self):
        f = learning.features(self.EV_HOOK, "Cuộc đua tỷ lệ ô tô điện trong số xe mới bán: Việt Nam và 9 nền kinh tế",
                              dt.OWID_SOURCE)
        self.assertEqual(f["subject"], "khong")
        f = learning.features(self.AGRI_HOOK, "Tỷ lệ lao động làm nông nghiệp: Việt Nam và Hàn Quốc từ 1991 đến 2025",
                              dt.WB_SOURCE)
        self.assertEqual(f["subject"], "co")
        self.assertNotIn("subject", learning.features("Sao lớn nuốt sao nhỏ?", "Bài báo thiên văn", "Donga Science"))


class ExemplarTest(MemoryCase):
    def approved(self, n, scenes, source=dt.WB_SOURCE, status="approved", engaged=None):
        self.con.execute("INSERT INTO ideas (id,title,title_norm,source_url,source_name,summary)"
                         " VALUES (?,?,?,?,?,'')", (n, f"t{n}", f"t{n}", f"u{n}", source))
        self.con.execute("INSERT INTO scripts (id,idea_id,body,status) VALUES (?,?,?,'verified')",
                         (n, n, yaml.safe_dump(scenes, allow_unicode=True)))
        self.con.execute("INSERT INTO videos (id,script_id,file,title,status) VALUES (?,?,'f','T',?)",
                         (n, n, status))
        if engaged is not None:
            db.save_video_stats(self.con, n, "analytics", {"views": 100, "engaged_views": engaged})
        self.con.commit()

    def test_only_approved_scripts_that_pass_todays_gates(self):
        idea = {"id": 50, "source_name": dt.WB_SOURCE}
        self.assertEqual(learning.exemplar_block(self.con, idea, CFG), "")
        self.approved(1, script(numbers=2)["scenes"])                     # đời cũ, rớt cổng hôm nay
        self.approved(2, script()["scenes"], status="rejected")           # Du loại
        self.approved(3, script()["scenes"], source="ScienceDaily")       # khác dạng (bài báo)
        self.assertEqual(learning.exemplar_block(self.con, idea, CFG), "")
        good = script()["scenes"]
        good[1]["voice"] = "câu mẫu đã duyệt " + "từ " * 10
        self.approved(4, good)
        block = learning.exemplar_block(self.con, idea, CFG)
        self.assertIn("VÍ DỤ MỘT KỊCH BẢN DU ĐÃ DUYỆT", block)
        self.assertIn("2. câu mẫu đã duyệt", block)
        self.assertIn("KHÔNG chép câu chữ", block)
        self.assertEqual(learning.exemplar_block(self.con, dict(idea, id=4), CFG), "")   # không tự làm mẫu
        self.assertIn("2. câu mẫu đã duyệt", learning.writer_lessons(self.con, idea, CFG))

    def test_the_one_viewers_kept_watching_wins(self):
        a, b = script()["scenes"], script()["scenes"]
        a[1]["voice"] = "mẫu giữ chân kém " + "từ " * 10
        b[1]["voice"] = "mẫu giữ chân tốt " + "từ " * 10
        self.approved(5, b, engaged=70)
        self.approved(6, a, engaged=30)                                  # mới hơn nhưng kém hơn
        self.assertIn("mẫu giữ chân tốt", learning.exemplar_block(self.con, {"id": 50, "source_name": dt.WB_SOURCE}, CFG))


class WeeklyLinesTest(MemoryCase):
    def test_report_says_what_was_learned(self):
        self.assertEqual(learning.weekly_lines(self.con), [])
        now = datetime.now(timezone.utc)
        for sid, status, days in ((1, "verified", 1), (2, "draft", 2), (3, "draft", 9)):
            self.con.execute("INSERT INTO scripts (id, idea_id, status, created_at) VALUES (?,?,?,?)",
                             (sid, sid, status, (now - timedelta(days=days)).isoformat(timespec="seconds")))
        self.con.commit()
        learning.record_problems(self.con, ["chỉ 2 con số trong lời đọc (cần ít nhất 5)"], "writer")
        learning.record_problems(self.con, ["cảnh đứng yên quá lâu: cảnh 3 (versus) mang 48 từ cho 1 hình"], "spec")
        learning.record(self.con, "du", "approve", "T", "review", script_id=1)
        learning.add_rule("Kết bằng câu hỏi mở")
        text = "\n".join(learning.weekly_lines(self.con, now))
        self.assertIn("Kịch bản đạt cổng tuần này: 1/2 (tuần trước 0/1)", text)
        self.assertIn("Lỗi Biên kịch hay gặp: quá ít con số — 1 lần", text)
        self.assertIn("Lỗi Sản xuất hay gặp: một hình gánh quá nhiều lời — 1 lần", text)
        self.assertIn("Du: duyệt 1, loại 0", text)
        self.assertIn("Luật Du đã dạy: 1", text)


class DailyPreferenceTest(DailyCase):
    def test_what_viewers_liked_moves_a_script_up(self):
        self.script(1, 26.0)                     # mở đầu kiểu "khac"
        self.script(2, 22.0)
        body = json.loads(self.con.execute("SELECT body FROM scripts WHERE id=2").fetchone()["body"])
        body[0]["voice"] = "Hàn Quốc dùng điện gấp 5 lần Việt Nam " + "từ " * 4
        self.con.execute("UPDATE scripts SET body=? WHERE id=2", (json.dumps(body, ensure_ascii=False),))
        self.con.commit()
        self.assertEqual([c["id"] for c in daily.pick_candidates(self.con, DAILY_CFG)], [1, 2])
        learned.save_learned({"preferences": {
            "metric": "engaged_pct", "based_on": 10, "mean": 40.0, "sd": 10.0,
            "hook": {"doi-lap": {"n": 5, "mean": 60.0, "score": 55.0},
                     "khac": {"n": 5, "mean": 25.0, "score": 30.0}}}})
        picked = daily.pick_candidates(self.con, DAILY_CFG)
        self.assertEqual([c["id"] for c in picked], [2, 1])
        self.assertGreater(picked[0]["learned"], picked[1]["learned"])


if __name__ == "__main__":
    unittest.main()
