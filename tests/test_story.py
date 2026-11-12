"""Test luật kể chuyện (src/story.py) và chỗ Biên kịch dùng chúng. Không gọi LLM.
Ví dụ lấy từ câu mở đầu THẬT của 18 kịch bản trên VM (12/11/2026).

    python -m unittest discover -s tests -v
"""
import json
import logging
import unittest
from unittest import mock

from src import crew, story
from tests.test_stage1 import CFG, script


class HookRuleTest(unittest.TestCase):
    def test_template_and_clickbait_openers_are_banned(self):
        for bad in ["Đừng phớt lờ những con số này sau 10 năm Thỏa thuận Paris!",          # #6
                    "Sai lầm 99% người ăn chay mắc phải khi chọn nguồn đạm!",              # #10
                    "Bạn có biết tuổi thọ trung bình của Việt Nam hiện đứng ở đâu?",       # #7 laptop
                    "Tuổi thọ trung bình của Việt Nam năm 2024 đạt bao nhiêu tuổi?",
                    "Hôm nay chúng ta cùng xem điện tiêu thụ của hai nước",
                    "Dòng iPhone gập mới của Apple đã tạo ra một cú sốc lớn."]:
            self.assertTrue(story.hook_problems(bad), bad)
        for good in ["Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991 về lượng điện tiêu thụ.",  # #17
                     "Trong 214 nước, Việt Nam đứng đúng chính giữa về tuổi thọ.",
                     "Vì sao Hàn Quốc sinh ít con nhất thế giới dù giàu gấp 7 lần?"]:
            self.assertEqual(story.hook_problems(good), [], good)

    def test_a_concrete_contrast_beats_a_vague_question(self):
        strong = story.hook_score("Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991 về điện.")
        number_only = story.hook_score("Việt Nam dùng 2.756 kWh điện mỗi người năm 2024.")
        vague = story.hook_score("Điện năng của Việt Nam thay đổi như thế nào qua các năm")
        self.assertGreater(strong, number_only)
        self.assertGreater(number_only, vague)

    def test_repeating_a_recent_opening_costs_points(self):
        h = "Việt Nam hôm nay mới bằng Hàn Quốc năm 1991."
        self.assertLess(story.hook_score(h, ["việt nam hôm"]), story.hook_score(h, ["hàn quốc từng"]))
        self.assertEqual(story.opener("“Việt Nam, hôm nay…"), "việt nam hôm")


class PickHookTest(unittest.TestCase):
    def test_strongest_sourced_option_replaces_scene_one(self):
        s = {"hooks": ["Sai lầm 99% người nghĩ về điện!",                         # cấm
                       "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991.",            # mạnh nhất
                       "Việt Nam dùng 2.756 kWh mỗi người."],
             "scenes": [{"voice": "Điện năng của hai nước thay đổi ra sao?", "visual": "bản đồ"}]}
        got = story.pick_hook(s)
        self.assertEqual(got, "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991.")
        self.assertEqual(s["scenes"][0], {"voice": got, "visual": "bản đồ"})       # giữ hình cảnh 1

    def test_option_with_an_invented_number_is_never_chosen(self):
        s = {"hooks": ["Việt Nam năm 2024 mới bằng Hàn Quốc năm 1987."],
             "scenes": [{"voice": "Việt Nam dùng điện ít hơn Hàn Quốc nhiều lần."}]}
        story.pick_hook(s, is_sourced=lambda text: "1987" not in text)
        self.assertEqual(s["scenes"][0]["voice"], "Việt Nam dùng điện ít hơn Hàn Quốc nhiều lần.")

    def test_report_fillers_are_trimmed(self):
        s = {"scenes": [{"voice": "Số liệu cho thấy Việt Nam đạt mức 74,7 tuổi năm 2024."},
                        {"voice": "Cụ thể, Nigeria thấp nhất bảng với 54,6 tuổi."},
                        {"voice": "Cụ thể là vậy."}]}                         # gọt xong quá ngắn -> giữ
        self.assertEqual(story.strip_fillers(s), 2)
        self.assertEqual([x["voice"] for x in s["scenes"]],
                         ["Việt Nam đạt mức 74,7 tuổi năm 2024.", "Nigeria thấp nhất bảng với 54,6 tuổi.",
                          "Cụ thể là vậy."])

    def test_clickbait_is_filtered_out_of_the_competitor_formula(self):
        rules = ["Dùng từ phủ định mạnh để cấm đoán thói quen cũ ('Đừng...').",
                 "Đưa ra nghịch lý hoặc con số sốc ngay từ giây đầu.",
                 "Tạo sự tò mò bằng câu hỏi tại sao cho hiện tượng quen thuộc."]
        self.assertEqual(story.safe_patterns(rules), [rules[2]])


class ScriptGateTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_reading_numbers_back_to_back_is_sent_back(self):
        s = script()
        for i in range(1, 6):                                 # cảnh 0-6 thành 7 câu có số liền (#16: 21)
            s["scenes"][i]["voice"] = f"Chỉ số đạt {5000 + i} đơn vị mỗi người dân từ từ từ"
        problems = crew.script_problems(s, CFG)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("7 câu có số đứng liền nhau", problems[0])

    def test_numbers_spelled_in_words_are_sent_back(self):
        # Ca thật khi thử dàn bài mới: "Bảy mươi ba phần trăm…", "Năm hai nghìn không trăm mười tám…"
        # — lọt qua cổng chống bịa số và cổng đếm mốc năm vì code chỉ nhận chữ số
        s = script()
        s["scenes"][3]["voice"] = "Năm hai nghìn không trăm mười tám, Việt Nam đạt tám phẩy chín tuổi"
        problems = crew.script_problems(s, CFG)
        self.assertTrue(any("viết bằng CHỮ" in p for p in problems), problems)
        self.assertEqual(story.spelled_numbers("ba lần, hai bên, năm nay, năm 2018"), [])
        s = script()
        s["scenes"][5]["voice"] = "Dân số vượt ngưỡng 적정 인구 của Trái Đất từ từ từ từ"
        self.assertTrue(any("chữ Hàn" in p for p in crew.script_problems(s, CFG)))
        # phương án mở đầu viết số bằng chữ thì không được chọn
        self.assertTrue(story.hook_problems("Bảy mươi ba phần trăm động vật hoang dã đã biến mất."))

    def test_specific_questions_are_still_allowed(self):
        self.assertEqual(story.hook_problems("Việt Nam cần bao nhiêu năm để bằng Hàn Quốc?"), [])

    def test_banned_or_repeated_opening_is_a_problem(self):
        s = script()
        s["scenes"][0]["voice"] = "Đừng nhìn tốc độ tiêu thụ điện 1000 của Việt Nam nữa!"
        self.assertTrue(any("câu mở đầu" in p for p in crew.script_problems(s, CFG)))
        s["scenes"][0]["voice"] = "Việt Nam năm 2024 dùng 1000 kWh, mới bằng Hàn Quốc 1991."
        self.assertEqual(crew.script_problems(s, CFG), [])
        self.assertTrue(any("lặp cách mở" in p for p in crew.script_problems(s, CFG, ["việt nam năm"])))

    def test_writer_picks_the_best_hook_and_is_told_what_recent_videos_opened_with(self):
        draft = script()
        draft["hooks"] = ["Sai lầm 99% người Việt mắc phải!",
                          "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991 về số 1000."]
        draft["scenes"][0]["voice"] = "Bạn có biết chỉ số 1000 của Việt Nam là bao nhiêu?"
        seen = []

        def fake(**kw):
            seen.append(kw["description"])
            return json.dumps(draft)
        idea = {"title": "T", "angle": "G", "source_url": "u", "summary": "năm 2024 và 1991"}
        with mock.patch.object(crew, "_run_single_task", fake), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            got = crew.write_script(idea, CFG, source_text="số 1000 1001 1002 1003 1004 1005",
                                    recent_hooks=["Hàn Quốc từng nghèo hơn Ghana năm 1960."])
        self.assertEqual(got["scenes"][0]["voice"], "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991 về số 1000.")
        self.assertEqual(len(seen), 1)                                     # đạt ngay, không viết lại
        self.assertIn("LUẬT HOOK", seen[0])
        self.assertIn("Hàn Quốc từng nghèo hơn Ghana năm 1960.", seen[0])  # biết video gần đây mở ra sao
        self.assertNotIn("mỗi con số một cảnh", seen[0])                    # dàn bài cũ gây "đọc bảng"


class RecentHooksTest(unittest.TestCase):
    def test_recent_openings_come_from_the_newest_scripts(self):
        import tempfile
        from pathlib import Path
        from src import db
        with tempfile.TemporaryDirectory() as d, mock.patch.object(db, "DB_PATH", Path(d) / "t.db"):
            con = db.connect()
            db.insert_raw_ideas(con, [{"title": "A", "summary": "", "url": "u1", "source": "s", "lang": "vi"}])
            idea = con.execute("SELECT id FROM ideas").fetchone()["id"]
            for h in ("Mở đầu cũ", "Mở đầu mới"):
                db.save_script(con, idea, [], f"- voice: {h}\n- voice: câu hai\n")
            db.save_script(con, idea, [], "không phải yaml: [")
            self.assertEqual(db.recent_hooks(con), ["Mở đầu mới", "Mở đầu cũ"])
            con.close()


if __name__ == "__main__":
    unittest.main()
