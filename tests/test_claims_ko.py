"""Test cổng soát câu cho kịch bản TIẾNG HÀN (src/claims_ko.py, src/story.py bản ko): câu SAI phải bị bắt,
câu ĐÚNG phải qua — cùng các ca thật của bản Việt, viết lại bằng tiếng Hàn.

    python -m unittest tests.test_claims_ko -v
"""
import unittest

from src import claims, lang, learning, story
from src.sources import worldbank

KOR = [(1960, 5.99), (1970, 4.53), (1980, 2.82), (1990, 1.57), (2000, 1.48), (2010, 1.23), (2024, 0.75)]
JPN = [(1960, 2.0), (1970, 2.13), (1980, 1.75), (1990, 1.54), (2000, 1.36), (2010, 1.39), (2024, 1.15)]


def summary() -> str:
    ind = {"code": "SP.DYN.TFRT.IN", "name": "합계출산율", "unit": "명"}
    countries = [{"iso3": "KOR", "iso2": "KR", "name": "한국"}, {"iso3": "JPN", "iso2": "JP", "name": "일본"}]
    return worldbank.build_item(ind, countries, {"KOR": KOR, "JPN": JPN})["summary"]


class KoreanClaimsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = lang.using("ko")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.s = summary()

    def bad(self, fn, text):
        got = fn([text], self.s)
        self.assertTrue(got, f"phải bắt: {text}")
        return got[0]

    def ok(self, fn, text):
        self.assertEqual(fn([text], self.s), [], f"không được bắt: {text}")

    def test_direction(self):
        why = self.bad(claims.comparison_problems, "2024년 한국은 일본보다 출산율이 높습니다.")
        self.assertIn("ngược chiều", why)
        self.ok(claims.comparison_problems, "2024년 한국은 일본보다 출산율이 낮습니다.")
        self.ok(claims.comparison_problems, "한국은 일본보다 더 빠르게 감소했습니다.")      # nói về mức thay đổi
        self.assertIn("ngược chiều", self.bad(claims.comparison_problems, "현재 한국은 일본보다 높습니다."))

    def test_times(self):
        why = self.bad(claims.comparison_problems, "2024년 한국은 일본의 1.53배입니다.")
        self.assertIn("đảo chiều", why)
        self.ok(claims.comparison_problems, "2024년 일본은 한국의 1.53배입니다.")

    def test_catch_up(self):
        why = self.bad(claims.comparison_problems, "2024년 한국은 1980년 일본 수준입니다.")
        self.assertIn("so sánh mốc thời gian SAI", why)
        self.ok(claims.comparison_problems, "2024년 한국은 1980년 일본 수준에 못 미칩니다.")   # phủ định

    def test_cause_trend_wording_overtake(self):
        self.assertIn("nguyên nhân/bối cảnh", self.bad(claims.cause_claims, "정부 정책 때문에 출산율이 떨어졌습니다."))
        self.ok(claims.cause_claims, "왜 이렇게 됐을까요?")
        self.assertIn("liên tục nhưng", self.bad(claims.trend_problems, "일본은 1960년부터 계속 감소했습니다."))
        self.ok(claims.trend_problems, "한국은 1960년 이후 꾸준히 감소했습니다.")            # dãy KOR giảm đều
        self.assertIn("nói như dự báo", self.bad(claims.wording_problems, "2024년에는 0.75명이 될 것으로 예상됩니다."))
        self.assertIn("bảng chỉ có từ năm", self.bad(claims.wording_problems, "역대 최저 수준입니다."))
        why = self.bad(claims.wording_problems, "일본이 2024년 한국을 앞질렀습니다.")
        self.assertIn("đã vượt", why)

    def test_why_hook(self):
        script = {"scenes": [{"voice": "왜 한국의 출산율은 이렇게 낮을까요?"}]}
        self.assertIn("không trả lời được nguyên nhân", claims.why_hook_problem(script, self.s))

    def test_messages_feed_the_learning_memory(self):
        """Lời báo lỗi bản Hàn phải được bộ nhớ tự học phân loại như bản Việt (không rơi vào "khac")."""
        cases = {
            "so_sanh": self.bad(claims.comparison_problems, "2024년 한국은 일본보다 출산율이 높습니다."),
            "nguyen_nhan": self.bad(claims.cause_claims, "정부 정책 때문에 출산율이 떨어졌습니다."),
            "xu_huong": self.bad(claims.trend_problems, "일본은 1960년부터 계속 감소했습니다."),
            "du_bao": self.bad(claims.wording_problems, "2024년에는 0.75명이 될 것으로 예상됩니다."),
        }
        for kind, message in cases.items():
            self.assertEqual(learning.kind_of(message), kind, message)


class KoreanStoryTest(unittest.TestCase):
    def setUp(self):
        self.ctx = lang.using("ko")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_banned_hooks_and_scripts(self):
        self.assertTrue(story.hook_problems("충격! 한국 출산율의 진실"))
        self.assertTrue(story.hook_problems("안녕하세요, 오늘은 출산율을 알아봅니다"))
        self.assertTrue(story.hook_problems("출산율이 칠십삼 퍼센트 줄었습니다"))           # số viết bằng chữ
        self.assertTrue(story.hook_problems("Hàn Quốc 출산율 0.75명"))                      # lẫn tiếng Việt
        self.assertEqual(story.hook_problems("한국 출산율 0.75명, 일본의 절반 수준입니다"), [])
        self.assertGreater(story.hook_score("한국 출산율 0.75명, 일본의 절반 수준입니다"),
                           story.hook_score("출산율 이야기를 해 보겠습니다"))

    def test_subject_and_numbers(self):
        words = story.subject_words("지표: 합계출산율(명). 출처: World Bank")
        self.assertEqual(words, {"합계출산율"})
        self.assertTrue(story.names_subject("한국의 합계출산율은 0.75명입니다", words))
        self.assertEqual(story.data_numbers("일본은 한국의 1.53배, 129개국 중 73위, 10명 중 4명"), set())
        self.assertEqual(story.data_numbers("한국은 0.75명입니다"), {"075"})

    def test_opening_definition_is_blocked(self):
        script = {"scenes": [{"voice": "한국 출산율 0.75명"}, {"voice": "이 지표는 여성 한 명이 낳는 아이 수를 뜻합니다"},
                             {"voice": "일본은 1.15명"}, {"voice": "2018년 1명 아래로"}]}
        hard, _ = story.opening_problems(script)
        self.assertTrue(any("định nghĩa" in h for h in hard))


class KoreanLearningTest(unittest.TestCase):
    """Bộ tự học phân loại được video kênh Hàn (không rơi hết vào "khac")."""

    def test_hook_type_and_kind(self):
        with lang.using("ko"):
            self.assertEqual(learning.hook_type("2024년 한국은 1980년 일본 수준입니다"), "moc-thoi-gian")
            self.assertEqual(learning.hook_type("OECD 38개국 중 꼴찌, 한국 재생에너지"), "thu-hang")
            self.assertEqual(learning.hook_type("한국 출산율, 일본보다 낮습니다"), "doi-lap")
            self.assertEqual(learning.hook_type("한국 출산율은 왜 이렇게 낮을까?"), "cau-hoi")
            src = "Our World in Data"
            self.assertEqual(learning.video_kind("세계 지도: 2024년 재생에너지 발전 비율 — 한국 …", src), "ban-do")
            self.assertEqual(learning.video_kind("1인당 GDP 순위 경쟁: 아시아 10개 경제", src), "cuoc-dua")
        with lang.using("vi"):
            self.assertEqual(learning.hook_type("Việt Nam đứng thứ 5 Đông Nam Á"), "thu-hang")


class KoreanTopicTest(unittest.TestCase):
    """/chude và đề xuất của người xem trên kênh Hàn: gõ tiếng Hàn (từ ghép, trợ từ) hoặc Du gõ tiếng Việt."""

    def test_match(self):
        import yaml
        from pathlib import Path
        from src import topics
        cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "channel_ko.yaml")
                             .read_text(encoding="utf-8"))
        with lang.using("ko"):
            self.assertEqual(topics.match(cfg, "출산율을 다뤄 주세요"), ["wb:SP.DYN.TFRT.IN"])
            self.assertEqual(topics.match(cfg, "tỷ suất sinh"), ["wb:SP.DYN.TFRT.IN"])     # Du gõ tiếng Việt
            got = topics.match(cfg, "GDP")
            self.assertIn("wb:NY.GDP.PCAP.CD", got)
            self.assertNotIn("wb:GB.XPD.RSDV.GD.ZS", got)                                  # "GDP 대비 연구개발비"
            self.assertEqual(topics.match(cfg, "영상 만들어 주세요"), [])


class KoreanCommunityTest(unittest.TestCase):
    def test_cards_carry_a_vietnamese_translation(self):
        from src import community
        cards = [{"id": "c1", "text": "한국은 몇 위예요?", "reply": "2024년 한국은 23위예요."},
                 {"id": "c2", "text": "영상 잘 봤어요"}]
        seen = {}

        def llm(role, goal, description, expected_output, models=None):
            seen["prompt"] = description
            return "Tiêu đề: \nMô tả: \n1. Hàn Quốc hạng mấy?\n2. Năm 2024 Hàn Quốc hạng 23.\n3. Video hay quá"
        community.translate_cards(cards, llm)
        self.assertIn("1. 한국은 몇 위예요?", seen["prompt"])
        self.assertEqual(cards[0]["text_vi"], "Hàn Quốc hạng mấy?")
        self.assertEqual(cards[0]["reply_vi"], "Năm 2024 Hàn Quốc hạng 23.")
        self.assertEqual(cards[1]["text_vi"], "Video hay quá")
        text = community.card_text({**cards[0], "kind": "cau_hoi", "video_id": 1, "youtube_id": "abc", "author": "A"})
        self.assertIn("🇻🇳 Hàn Quốc hạng mấy?", text)
        self.assertIn("🇻🇳 Năm 2024 Hàn Quốc hạng 23.", text)


if __name__ == "__main__":
    unittest.main()
