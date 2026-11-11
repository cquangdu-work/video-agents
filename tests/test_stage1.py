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
    """Kịch bản giả: `numbers` cảnh đầu mỗi cảnh có một con số khác nhau."""
    out = []
    for i in range(scenes):
        body = ["từ"] * words_each
        if i < numbers:
            body[0] = str(1000 + i)
        out.append({"voice": " ".join(body), "visual": "hình", "data_source": "nguồn"})
    return {"hooks": ["a", "b", "c"], "scenes": out, "claims": []}


class ScriptStandardTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.WARNING); self.addCleanup(logging.disable, logging.NOTSET)

    def test_word_budget_follows_measured_speech_rate(self):
        self.assertEqual(crew.word_budget(CFG), (204, 306))      # 60-90 giây x 3,4 từ/giây

    def test_problems_name_what_is_missing(self):
        self.assertEqual(crew.script_problems(script(), CFG), [])
        few = crew.script_problems(script(numbers=2), CFG)       # ca thật trên VM: 1-3 con số
        self.assertEqual(len(few), 1); self.assertIn("chỉ 2 con số", few[0])
        short = crew.script_problems(script(scenes=12, words_each=10), CFG)
        self.assertTrue(any("120 từ" in p for p in short))

    def test_writer_sees_the_source_text_and_keeps_the_least_broken_draft(self):
        drafts = [script(numbers=3), script(scenes=12, words_each=10, numbers=1)]   # bản 2 tệ hơn
        seen = []

        def fake_llm(role, goal, description, expected_output):
            seen.append(description)
            return json.dumps(drafts[len(seen) - 1])
        idea = {"title": "T", "angle": "G", "source_url": "https://x", "summary": "tóm tắt"}
        with mock.patch.object(crew, "_run_single_task", fake_llm), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            got = crew.write_script(idea, CFG, source_text="Bài gốc ghi 8.030 hệ thống. " * 400)
        self.assertEqual(got, drafts[0])                         # giữ bản ít lỗi nhất
        self.assertIn("TRÍCH BÀI NGUỒN", seen[0])
        self.assertIn("8.030 hệ thống", seen[0])
        self.assertLess(len(seen[0]), 9000)                      # bài dài được cắt bớt
        self.assertIn("BẢN NHÁP TRƯỚC BỊ TRẢ LẠI vì: chỉ 3 con số", seen[1])

    def test_malformed_llm_answers_are_normalised_not_fatal(self):
        scenes = script()["scenes"]
        self.assertEqual(crew.as_script(scenes)["scenes"], scenes)             # mảng cảnh trần
        self.assertEqual(crew.as_script([{"hooks": ["h"], "scenes": scenes}])["hooks"], ["h"])
        for junk in (None, "xin lỗi", ["a", "b"], {"scenes": "không phải mảng"}, 42):
            self.assertEqual(crew.as_script(junk), {"scenes": [], "hooks": [], "claims": []})

    def test_writer_survives_a_fallback_model_that_answers_with_a_list(self):
        # Ca thật trên VM 12/11/2026: model chính 503, model dự phòng trả mảng -> script.get() nổ
        answers = ['["chỉ có hook", "không có cảnh"]', "Xin lỗi, tôi không làm được.",]
        idea = {"title": "T", "angle": "G", "source_url": "https://x"}
        with mock.patch.object(crew, "_run_single_task", lambda **kw: answers.pop(0)), \
                mock.patch.object(crew, "_formula_block", lambda: ""):
            got = crew.write_script(idea, CFG, source_text="nguồn")
        self.assertEqual(got["scenes"], [])
        self.assertTrue(crew.script_problems(got, CFG))          # rỗng = hụt chuẩn, không lọt đi dựng

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

    def run_agents(self, bad_ideas, crash=(), no_source=()):
        from src import main, page_text
        written = []

        def write(idea, cfg, feedback=None, source_text=""):
            written.append(idea["id"])
            assert source_text == "toàn văn"                     # bài nguồn được tải TRƯỚC khi viết
            if idea["id"] in crash:
                raise RuntimeError("Mọi model đều quá tải")
            return dict(script(numbers=2 if idea["id"] in bad_ideas else 6))
        url_of = {f"https://s/{n}": i for n, i in enumerate(self.ids)}
        patches = [
            mock.patch.object(crew, "hunt_ideas",
                              lambda raw, cfg: [{"id": i, "angle": "góc"} for i in self.ids]),
            mock.patch.object(crew, "score_ideas", lambda ideas, cfg: [
                {"id": i, "total": 30 - n} for n, i in enumerate(self.ids)]),
            mock.patch.object(crew, "write_script", write),
            mock.patch.object(crew, "fact_check", lambda *a: {"pass": True, "verdicts": []}),
            mock.patch.object(page_text, "fetch_page_text",
                              lambda url: "" if url_of[url] in no_source else "toàn văn"),
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
