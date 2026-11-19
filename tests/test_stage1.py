"""Test khâu đầu dây chuyền (nguồn ý tưởng, Biên kịch, cổng chuẩn kịch bản).
Không gọi mạng, không gọi LLM.

    python -m unittest discover -s tests -v
"""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import crew, db
from src.sources import reddit, rss

CFG = {
    "channel": {"name": "Thế giới qua con số", "description": "kênh dữ liệu",
                "video_seconds_min": 60, "video_seconds_max": 90},
    "pacing": {"scene_seconds_min": 2, "scene_seconds_max": 4, "words_per_second": 3.4},
    "policy_rules": "không giật tít", "angle_rules": "phải có góc",
    "daily": {"shortlist": 2, "extra_script_tries": 2},
    "dedup": {"title_similarity_threshold": 0.55,
              "youtube_check": {"max_popular_allowed": 3}},
    "scoring_weights": {"min_total": 17},
}


def script(scenes=17, words_each=14, numbers=6):
    """Kịch bản giả: `numbers` con số khác nhau, rải CÁCH MỘT CẢNH (cảnh 0, 2, 4...) — kịch bản
    đạt chuẩn không được đọc số liền nhau như đọc bảng (story.longest_number_run)."""
    out = []
    for i in range(scenes):
        body = ["từ"] * words_each
        if i % 2 == 0 and i // 2 < numbers:
            body[0] = str(1000 + i // 2)
        out.append({"voice": " ".join(body), "visual": "hình", "data_source": "nguồn"})
    if numbers and scenes > 1:                     # câu kết nhắc lại con số của hook (story.ending_problem)
        out[-1]["voice"] = " ".join(["1000"] + ["từ"] * (words_each - 1))
    return {"hooks": ["a", "b", "c"], "scenes": out, "claims": []}


class ScriptStandardTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_word_budget_follows_measured_speech_rate(self):
        self.assertEqual(crew.word_budget(CFG), (204, 306))      # 60-90 giây x 3,4 từ/giây

    def test_problems_name_what_is_missing(self):
        self.assertEqual(crew.script_problems(script(), CFG), [])
        few = crew.script_problems(script(numbers=2), CFG)       # ca thật trên VM: 1-3 con số
        self.assertTrue(any("chỉ 2 con số" in x for x in few))
        short = crew.script_problems(script(scenes=12, words_each=10), CFG)
        self.assertTrue(any("120 từ" in p for p in short))

    def test_writer_sees_the_source_text_and_keeps_the_least_broken_draft(self):
        drafts = [script(numbers=3), script(scenes=12, words_each=10, numbers=1)]   # bản 2 tệ hơn
        seen = []

        def fake_llm(role, goal, description, expected_output, models=None):
            seen.append(description)
            return json.dumps(drafts[len(seen) - 1])
        idea = {"title": "T", "angle": "G", "source_url": "https://x", "summary": "tóm tắt"}
        with mock.patch.object(crew, "_run_single_task", fake_llm), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            # số của bản nháp (1000-1002) có trong nguồn: cảnh 1 đúng nên không bị phương án "a" thay
            got = crew.write_script(idea, CFG, source_text="Bài gốc ghi 8.030 hệ thống, 1000, 1001,"
                                                           " 1002. " * 400)
        self.assertEqual(got, drafts[0])                         # giữ bản ít lỗi nhất
        self.assertIn("TRÍCH BÀI NGUỒN", seen[0])
        self.assertIn("8.030 hệ thống", seen[0])
        self.assertLess(len(seen[0]), 11000)                     # bài dài (16 nghìn ký tự) được cắt bớt
        self.assertIn("BẢN NHÁP TRƯỚC BỊ TRẢ LẠI vì: chỉ 3 con số", seen[1])

    def test_malformed_llm_answers_are_normalised_not_fatal(self):
        scenes = script()["scenes"]
        self.assertEqual(crew.as_script(scenes)["scenes"], scenes)             # mảng cảnh trần
        self.assertEqual(crew.as_script([{"hooks": ["h"], "scenes": scenes}])["hooks"], ["h"])
        for junk in (None, "xin lỗi", ["a", "b"], {"scenes": "không phải mảng"}, 42):
            self.assertEqual(crew.as_script(junk), {"scenes": [], "hooks": [], "claims": []})

    def test_reading_out_a_table_year_by_year_is_rejected(self):
        # Ca thật (kịch bản #16): "Năm 1995 Việt Nam 159 kWh... Hàn Quốc năm 1995 3.957 kWh..."
        dump = script()
        for k, year in enumerate(range(1990, 2025, 5)):
            dump["scenes"][k]["voice"] = f"Năm {year}, Việt Nam đạt {100 + k} kWh mỗi người dân từ từ"
        problems = crew.script_problems(dump, CFG)
        self.assertTrue(any("đọc lần lượt 7 mốc năm" in p for p in problems))
        story = script()
        story["scenes"][0]["voice"] = "Việt Nam năm 2024 mới bằng Hàn Quốc năm 1991, cách 33 năm từ"
        story["scenes"][-1]["voice"] = "Khoảng cách 33 năm ấy là câu chuyện của cả một thế hệ từ"
        self.assertEqual(crew.script_problems(story, CFG), [])

    def test_data_ideas_get_storytelling_rules(self):
        from src.sources.worldbank import SOURCE_NAME
        seen = []

        def fake(**kw):
            seen.append(kw["description"])
            return json.dumps(script())
        with mock.patch.object(crew, "_run_single_task", fake), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            crew.write_script({"title": "T", "angle": "G", "source_url": "u", "source_name": SOURCE_NAME},
                              CFG, source_text="bảng 1000, 1001, 1002, 1003, 1004, 1005")
            crew.write_script({"title": "T", "angle": "G", "source_url": "u", "source_name": "Hani"},
                              CFG, source_text="bài 1000, 1001, 1002, 1003, 1004, 1005")
        self.assertIn("ĐÂY LÀ Ý TƯỞNG TỪ BẢNG SỐ LIỆU", seen[0])
        self.assertNotIn("ĐÂY LÀ Ý TƯỞNG TỪ BẢNG SỐ LIỆU", seen[1])

    def test_writer_survives_a_fallback_model_that_answers_with_a_list(self):
        # Ca thật trên VM 12/11/2026: model chính 503, model dự phòng trả mảng -> script.get() nổ
        answers = ['["chỉ có hook", "không có cảnh"]', "Xin lỗi, tôi không làm được.",]
        idea = {"title": "T", "angle": "G", "source_url": "https://x"}
        with mock.patch.object(crew, "_run_single_task", lambda **kw: answers.pop(0)), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            got = crew.write_script(idea, CFG, source_text="nguồn")
        self.assertEqual(got["scenes"], [])
        self.assertTrue(crew.script_problems(got, CFG))          # rỗng = hụt chuẩn, không lọt đi dựng

    def test_every_spoken_number_must_come_from_the_source(self):
        idea = {"title": "두부 36점, 체더치즈 13점", "summary": "폭염 사망 54만 명"}
        source = "Tofu scored 36 of 40. Beef emits 64.19kg, tofu 0.61kg. Sodium: 2,549.55mg per 100g."
        say = lambda *lines: {"scenes": [{"voice": l} for l in lines]}
        ok = say("Trên thang 40 điểm, đậu hũ đạt 36 điểm, Cheddar chỉ 13.",
                 "Thịt bò thải 64,19kg, đậu hũ 0,61kg; natri tới 2.549,55mg trong 100g.",
                 "Có 3 lý do, và 540.000 người chịu ảnh hưởng.")          # 54만 = 540.000
        self.assertEqual(crew.unsourced_numbers(ok, idea, source), [])
        bad = say("Sai lầm 99% người ăn chay mắc phải!", "Đậu hũ đạt 36 điểm, tăng 25 bậc.",
                  "Và 99% vẫn chưa biết.")
        self.assertEqual(crew.unsourced_numbers(bad, idea, source), ["99%", "25"])

    def test_spoken_lines_are_stripped_of_hashtags_emoji_and_channel_tail(self):
        self.assertEqual(crew.clean_spoken("Sai lầm khi chọn đạm! #Shorts"), "Sai lầm khi chọn đạm!")
        self.assertEqual(crew.clean_spoken("Vì sao đậu hũ thắng thịt bò? 🧐 | Thế giới qua con số"),
                         "Vì sao đậu hũ thắng thịt bò?")
        got = crew.as_script({"hooks": ["Hook #Shorts"], "scenes": [{"voice": "Câu 1 🔥 #viral"}]})
        self.assertEqual((got["hooks"], got["scenes"][0]["voice"]), (["Hook"], "Câu 1"))

    def test_fact_checker_answer_in_the_wrong_shape_counts_as_not_verified(self):
        for answer in ('["ok"]', "Tôi nghĩ là đúng.", '{"pass": true, "verdicts": "tất cả ổn"}'):
            with mock.patch.object(crew, "_run_single_task", lambda **kw: answer):
                fc = crew.fact_check(script(), {"source_url": "https://x"}, "nguồn", CFG)
            self.assertIsInstance(fc["verdicts"], list)
        self.assertFalse(crew.fact_check.__doc__ is None)
        with mock.patch.object(crew, "_run_single_task", lambda **kw: '["ok"]'):
            self.assertFalse(crew.fact_check(script(), {"source_url": "u"}, "n", CFG)["pass"])

    def test_fact_checker_reads_every_sentence_but_needs_a_second_opinion(self):
        s = script()
        s["claims"] = [{"claim": "c1", "source": "u"}]
        s["scenes"][0]["voice"] = "Hàn Quốc tăng trưởng liên tục suốt 35 năm."
        first = json.dumps({"verdicts": [{"claim": "c1", "ok": True}], "sentence_issues": [
            {"scene": 1, "kind": "sai_xu_huong", "note": "năm 2010 có giảm"},
            {"scene": 3, "kind": "khong_co_trong_nguon", "note": "giải thích"},     # loại không được chặn
            {"scene": 99, "kind": "sai_so", "note": "cảnh không tồn tại"}, "rác"]})
        seen = []

        def llm(confirm):
            def run(**kw):
                seen.append(kw["description"])
                return first if len(seen) == 1 else json.dumps({"results": [{"scene": 1, "wrong": confirm}]})
            return run
        with mock.patch.object(crew, "_run_single_task", llm(True)):
            fc = crew.fact_check(s, {"source_url": "u"}, "nguồn", CFG)
        self.assertFalse(fc["pass"])
        self.assertEqual([(i["scene"], i["kind"]) for i in fc["sentence_issues"]], [(1, "sai_xu_huong")])
        self.assertIn("TOÀN BỘ LỜI ĐỌC", seen[0])
        self.assertIn("Hàn Quốc tăng trưởng liên tục", seen[1])          # lượt 2 chỉ hỏi câu bị nghi
        seen.clear()
        with mock.patch.object(crew, "_run_single_task", llm("false")):   # lượt 2 không xác nhận
            fc = crew.fact_check(s, {"source_url": "u"}, "nguồn", CFG)
        self.assertTrue(fc["pass"])
        self.assertEqual(fc["sentence_issues"], [])

    def test_fact_checker_without_verdicts_for_declared_claims_is_not_a_pass(self):
        s = script()
        s["claims"] = [{"claim": "c1", "source": "u"}]
        with mock.patch.object(crew, "_run_single_task", lambda **kw: '{"pass": true, "verdicts": []}'):
            self.assertFalse(crew.fact_check(s, {"source_url": "u"}, "n", CFG)["pass"])
        with mock.patch.object(crew, "_run_single_task", lambda **kw: '{"verdicts": []}'):
            self.assertTrue(crew.fact_check(script(), {"source_url": "u"}, "n", CFG)["pass"])  # không khai claim

    def test_hunter_keeps_only_well_formed_picks(self):
        answer = ('[{"id": 1, "angle": "góc", "keyword": "tỷ suất sinh Hàn Quốc"}, "rác",'
                  ' {"id": 2}, {"angle": "thiếu id"}]')
        with mock.patch.object(crew, "_run_single_task", lambda **kw: answer):
            got = crew.hunt_ideas([{"id": 1, "source_name": "S", "lang": "vi", "title": "t",
                                    "summary": ""}], CFG)
        self.assertEqual(got, [{"id": 1, "angle": "góc", "keyword": "tỷ suất sinh Hàn Quốc"}])
        with mock.patch.object(crew, "_run_single_task", lambda **kw: "Không có ý tưởng nào hay."):
            self.assertEqual(crew.hunt_ideas([], CFG), [])

    def test_hunter_is_told_how_many_numbers_each_idea_has(self):
        seen = []
        raw = [{"id": 1, "source_name": "OWID", "lang": "en", "title": "540.000 deaths a year",
                "summary": "up 38% since 2015"},
               {"id": 2, "source_name": "arXiv", "lang": "en", "title": "AI is picky", "summary": ""}]
        with mock.patch.object(crew, "_run_single_task",
                               lambda **kw: seen.append(kw["description"]) or "[]"):
            crew.hunt_ideas(raw, CFG)
        self.assertIn("(OWID, en, 3 con số)", seen[0])
        self.assertIn("(arXiv, en, 0 con số)", seen[0])


class StandardGateTest(unittest.TestCase):
    """main.run_agents: kịch bản hụt chuẩn ở lại 'draft', dây chuyền viết ý tưởng kế tiếp."""

    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(db, "DB_PATH", Path(self.tmp.name) / "t.db")
        p.start(); self.addCleanup(p.stop)
        self.con = db.connect(); self.addCleanup(self.con.close)
        db.insert_raw_ideas(self.con, [
            {"title": f"chủ đề riêng số {w}", "url": f"https://s/{i}", "source": "S", "lang": "vi"}
            for i, w in enumerate(["alpha", "beta", "gamma", "delta", "epsilon"])])
        self.ids = [r["id"] for r in self.con.execute("SELECT id FROM ideas ORDER BY id")]

    SOURCE = "toàn văn bài nguồn có các số 1000, 1001, 1002, 1003, 1004 và 1005"

    def run_agents(self, bad_ideas, crash=(), no_source=(), invents=(), keeps_inventing=()):
        from src import main, page_text
        written, self.feedback = [], []

        def write(idea, cfg, feedback=None, source_text="", recent_hooks=None):
            written.append(idea["id"])
            self.feedback.append(feedback)
            assert source_text == self.SOURCE                    # bài nguồn được tải TRƯỚC khi viết
            if idea["id"] in crash:
                raise RuntimeError("Mọi model đều quá tải")
            s = script(numbers=2 if idea["id"] in bad_ideas else 6)
            if idea["id"] in keeps_inventing or (idea["id"] in invents and not feedback):
                s["scenes"][-1]["voice"] = "Sai lầm 99% người mắc phải " + "từ " * 9
            return s
        url_of = {f"https://s/{n}": i for n, i in enumerate(self.ids)}
        patches = [
            mock.patch.object(crew, "hunt_ideas",
                              lambda raw, cfg: [{"id": i, "angle": "góc"} for i in self.ids]),
            mock.patch.object(crew, "score_ideas", lambda ideas, cfg: [
                {"id": i, "total": 30 - n} for n, i in enumerate(self.ids)]),
            mock.patch.object(crew, "write_script", write),
            mock.patch.object(crew, "fact_check", lambda *a: {"pass": True, "verdicts": []}),
            mock.patch.object(page_text, "fetch_page_text",
                              lambda url: "" if url_of[url] in no_source else self.SOURCE),
            mock.patch.object(main, "count_popular_vietnamese_videos", lambda *a: None),
            mock.patch("builtins.print"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        main.run_agents(CFG, self.con, use_telegram=False)
        rows = self.con.execute("SELECT idea_id, status, factcheck FROM scripts ORDER BY id").fetchall()
        return written, [(r["idea_id"], r["status"]) for r in rows], rows

    def test_weak_scripts_stay_drafts_and_next_ideas_are_tried(self):
        a, b, c, d, e = self.ids
        written, statuses, rows = self.run_agents(bad_ideas={a, b})
        self.assertEqual(statuses, [(a, "draft"), (b, "draft"), (c, "verified"), (d, "verified")])
        self.assertEqual(written, [a, b, c, d])                  # đủ 2 bản đạt thì dừng, không viết e
        self.assertIn("chỉ 2 con số", json.loads(rows[0]["factcheck"])["standard_problems"][0])

    def test_one_crashing_idea_or_unreachable_source_does_not_sink_the_stage(self):
        a, b, c, d, e = self.ids
        written, statuses, _ = self.run_agents(bad_ideas=set(), crash={a}, no_source={b})
        self.assertEqual(written, [a, c, d])                     # b không tải được nguồn: khỏi gọi LLM
        self.assertEqual(statuses, [(c, "verified"), (d, "verified")])
        reasons = dict(self.con.execute("SELECT id, reject_reason FROM ideas WHERE status='rejected'"))
        self.assertIn("quá tải", reasons[a])
        self.assertEqual(reasons[b], "Không tải được bài nguồn")

    def test_invented_number_is_sent_back_and_blocks_the_script_if_it_stays(self):
        # Ca thật trên VM: hook "Sai lầm 99% người ăn chay mắc phải" — Kiểm chứng LLM cho qua
        a, b, c, d, e = self.ids
        written, statuses, rows = self.run_agents(bad_ideas=set(), invents={a}, keeps_inventing={b})
        self.assertEqual(written, [a, a, b, b, c])               # a, b mỗi cái bị trả lại viết lần 2
        self.assertIn("BỊA SỐ: con số 99%", self.feedback[1])
        self.assertEqual(statuses, [(a, "verified"), (b, "draft"), (c, "verified")])
        self.assertIn("con số không có trong bài nguồn: 99%",
                      json.loads(rows[1]["factcheck"])["standard_problems"])

    def test_no_extra_llm_calls_when_first_scripts_are_good(self):
        written, statuses, _ = self.run_agents(bad_ideas=set())
        self.assertEqual(written, self.ids[:2])
        self.assertEqual([s for _, s in statuses], ["verified", "verified"])


ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Why is the sky blue?</title><link href="https://www.reddit.com/r/askscience/comments/1/"/>
<content type="html">&lt;div&gt;&lt;p&gt;I always wondered about 450 nm light.&lt;/p&gt;&lt;/div&gt;
submitted by /u/someone [link] [comments]</content></entry></feed>"""
RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
<item><title>Bai moi</title><link>https://hani/1</link><description>tom tat</description></item>
</channel></rss>"""


def http(status, content=b"", payload=None):
    r = mock.Mock(status_code=status, content=content)
    r.json.return_value = payload
    r.raise_for_status.side_effect = None if status < 400 else reddit.requests.HTTPError(f"{status}")
    return r


class SourcesTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)
        p = mock.patch.object(reddit.time, "sleep"); self.sleep = p.start(); self.addCleanup(p.stop)

    def test_reddit_falls_back_to_rss_when_json_is_blocked(self):
        # Ca thật: VM Oracle nhận 403 ở đường JSON, RSS vẫn vào được
        calls = []

        def get(url, **kw):
            calls.append(url)
            return http(403) if ".json" in url else http(200, ATOM)
        with mock.patch.object(reddit.requests, "get", get):
            items = reddit.fetch_reddit({"subreddits": ["askscience", "eli5"]})
        self.assertEqual([i["source"] for i in items], ["r/askscience", "r/eli5"])
        self.assertEqual(items[0]["title"], "Why is the sky blue?")
        self.assertEqual(items[0]["summary"], "I always wondered about 450 nm light.")
        self.assertEqual(sum(".json" in u for u in calls), 1)    # sub sau đi thẳng RSS
        self.assertTrue(self.sleep.called)                       # có nghỉ giữa các lần gọi RSS

    def test_reddit_rss_retries_once_on_rate_limit(self):
        answers = [http(403), http(429), http(200, ATOM)]
        with mock.patch.object(reddit.requests, "get", lambda url, **kw: answers.pop(0)):
            items = reddit.fetch_reddit({"subreddits": ["askscience"]})
        self.assertEqual(len(items), 1)

    def test_rss_is_downloaded_with_requests_and_survives_a_dead_feed(self):
        answers = {"https://ok": http(200, RSS), "https://dead": http(503)}
        with mock.patch.object(rss.requests, "get", lambda url, **kw: answers[url]):
            items = rss.fetch_rss_sources([{"name": "Chết", "url": "https://dead"},
                                           {"name": "Hani", "url": "https://ok", "lang": "ko"}])
        self.assertEqual(items, [{"title": "Bai moi", "summary": "tom tat", "url": "https://hani/1",
                                  "source": "Hani", "lang": "ko"}])


if __name__ == "__main__":
    unittest.main()
