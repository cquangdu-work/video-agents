"""Engine Remotion (src/render/web.py): dịch spec -> props.

    python -m unittest tests.test_web -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.audio import music
from src.render import web

VN = {"label": "Việt Nam", "xs": [1960, 1990, 2010, 2024], "ys": [0.0, 0.0, 128.0, 128.0]}
KR = {"label": "Hàn Quốc", "xs": [1960, 1990, 2010, 2024], "ys": [0.0, 0.18, 104.0, 173.0]}


def _spec():
    chart = {"title": "Thuê bao di động trên 100 dân", "unit": "thuê bao", "decimals": 2,
             "xs": [1960, 1990, 2010, 2024], "series": [dict(VN), dict(KR)], "source": "World Bank"}
    return [
        {"template": "intro", "seconds": 1.2, "params": {}},
        {"template": "statement", "seconds": 3.0, "voice": "Chiếc điện thoại trong tay bạn.",
         "params": {"text": "Điện thoại trong tay bạn", "style": 0, "n": 1}},
        {"template": "versus", "seconds": 4.0, "voice": "Năm 2024 Việt Nam 128, Hàn Quốc 173.",
         "params": {"title": "Thuê bao năm 2024", "left": {"label": "Việt Nam", "value": 128},
                    "right": {"label": "Hàn Quốc", "value": 173}, "suffix": "thuê bao"}},
        {"template": "line_chart", "seconds": 4.0, "voice": "Đến 2024 Việt Nam đạt 128 thuê bao.",
         "params": chart},
        {"template": "big_number", "seconds": 3.0, "voice": "Khoảng cách chỉ là 6 năm.",
         "params": {"title": "Khoảng cách thời gian", "value": 6, "suffix": "năm"}},
        {"template": "map", "seconds": 5.0, "voice": "Cả châu Á.", "params": {"title": "Bản đồ"}},
    ]


def _timed(spec):
    """Mốc giả: mỗi cảnh chia đều thời lượng cho các từ của nó."""
    out, t = [], 0.0
    for sc in spec:
        words = str(sc.get("voice") or "").split()
        for w in words:
            d = float(sc["seconds"]) / len(words)
            out.append((w, round(t, 3), round(t + d * 0.9, 3)))
            t += d
        if not words:
            t += float(sc["seconds"])
    return out


class TestHelpers(unittest.TestCase):
    def test_pick_icon(self):
        self.assertEqual(web.pick_icon("Thuê bao di động tăng mạnh"), "smartphone")
        self.assertEqual(web.pick_icon("Điện mặt trời bùng nổ"), "sun")      # cụm cụ thể thắng "điện"
        self.assertEqual(web.pick_icon("Ứng dụng AI trong y tế"), "bot")      # AI viết hoa
        self.assertNotEqual(web.pick_icon("ai cũng có một chiếc"), "bot")     # "ai" là đại từ
        self.assertIsNone(web.pick_icon("Một câu không có từ khoá nào"))

    def test_clean_label_and_flags(self):
        self.assertEqual(web._clean_label("Việt Nam (2024)"), ("Việt Nam", 2024))
        self.assertEqual(web._clean_label(" Hàn  Quốc "), ("Hàn Quốc", None))
        self.assertEqual(web.flag_of("Việt Nam"), "vn")
        self.assertEqual(web.flag_of("Hàn Quốc (2018)"), "kr")
        self.assertIsNone(web.flag_of("Đài Loan (Trung Quốc)"))              # góc nhìn Việt Nam
        self.assertIsNone(web.flag_of("không phải nước nào"))

    def test_match_points_only_when_unique(self):
        world = web.build_world(_spec(), web.brand()["colors"])
        vn, kr = 0, 1
        self.assertEqual(web._match_points(world, "Việt Nam", 128, 0, set()), [])   # 2010 và 2024 đều 128
        self.assertEqual(web._match_points(world, "Việt Nam", 128, 0, {2024}), [(vn, 2024)])
        self.assertEqual(web._match_points(world, "Việt Nam (2010)", 128, 0, set()), [(vn, 2010)])
        self.assertEqual(web._match_points(world, "Hàn Quốc", 173, 0, set()), [(kr, 2024)])
        self.assertEqual(web._match_points(world, "Hàn Quốc", 999, 0, set()), [])
        self.assertEqual(web._match_points(world, "Hàn Quốc", 0.18, 2, set()), [(kr, 1990)])

    def test_mix_filter_with_sfx_has_three_inputs(self):
        f = music.mix_filter(60.0, -20.0, sfx=True)
        self.assertIn("[0:a]", f)
        self.assertIn("amix=inputs=3", f)
        self.assertTrue(f.endswith("[aout]"))
        self.assertIn("amix=inputs=2", music.mix_filter(60.0, -20.0))

    def test_words_from_ass_roundtrip(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            ass = tmp / "s.ass"
            ass.write_text(
                "[Events]\n"
                "Dialogue: 0,0:00:01.00,0:00:01.40,Word,,0,0,0,,{\\c&H0003B7FF&}Vì{\\c&H00D8EBF0&} sao\n"
                "Dialogue: 0,0:00:01.40,0:00:01.80,Word,,0,0,0,,Vì {\\c&H0003B7FF&}sao{\\c&H00D8EBF0&}\n"
                "Dialogue: 0,0:00:02.00,0:00:02.30,Word,,0,0,0,,{\\c&H0003B7FF&}128{\\c&H00D8EBF0&}\n",
                encoding="utf-8")
            w = web.words_from_ass(ass)
            self.assertEqual([x["w"] for x in w], ["Vì", "sao", "128"])
            self.assertEqual([x["c"] for x in w], [0, 0, 1])
            self.assertEqual(web.find_word(w, "128"), 2.0)
        finally:
            shutil.rmtree(tmp)


class TestBuildStory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(web, "CLIPS", self.tmp / "clips")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_maps_every_template(self):
        clip = self.tmp / "manim.mp4"
        clip.write_bytes(b"x")
        calls = []
        spec = _spec()
        props = web.build_story(spec, _timed(spec), "t1", render_clip=lambda sc, i: calls.append(i) or clip)
        st = props["scenes"]
        self.assertEqual([s["kind"] for s in st],
                         ["intro", "statement", "versus", "line_chart", "big_number", "clip"])
        self.assertEqual(calls, [5])                                     # chỉ bản đồ dựng bằng Manim
        self.assertTrue((self.tmp / "clips" / "t1" / "scene_05.mp4").exists())
        self.assertEqual(st[1]["icon"], "smartphone")
        # so găng 2024 nằm trên biểu đồ chính: 2 điểm số liệu thật, vẽ tới 2024
        self.assertEqual(st[2]["chart"], {"mode": "panel", "drawTo": 2024,
                                          "focus": [{"s": 0, "x": 2024}, {"s": 1, "x": 2024}]})
        self.assertEqual((st[2]["left"]["flag"], st[2]["right"]["flag"]), ("vn", "kr"))
        # line_chart: lời đọc nói "128" -> chú thích lớn đúng mốc của từ đó
        co = st[3]["chart"]["callout"]
        self.assertEqual((co["value"], co["s"]), ("128", 0))
        self.assertTrue(st[3]["start"] <= co["at"] < st[3]["end"])
        # "6 năm" không cùng chủ đề với biểu đồ -> không bị gắn nhầm vào điểm nào
        self.assertNotIn("chart", st[4])
        self.assertEqual(props["world"]["reference"]["y"], 100)
        # Kiểm định biết những số biểu đồ có thể hiện
        self.assertIn(173.0, spec[2]["shown"])
        self.assertIn(2010, spec[2]["shown"])
        # thời gian liền mạch
        self.assertTrue(all(a["end"] == b["start"] for a, b in zip(st, st[1:])))
        self.assertAlmostEqual(props["duration"], sum(sc["seconds"] for sc in spec), places=3)
        self.assertTrue(props["sfx"])

    def test_unsupported_without_clip_renderer_raises(self):
        spec = _spec()
        with self.assertRaises(ValueError):
            web.build_story(spec, _timed(spec), "t2", render_clip=None)

    def test_share_isotype_only_for_population_shares(self):
        spec = [{"template": "intro", "seconds": 1.2, "params": {}},
                {"template": "big_number", "seconds": 3, "voice": "38,8% dân số sống ở thành thị.",
                 "params": {"title": "Tỷ lệ dân số thành thị", "value": 38.8, "suffix": "%", "decimals": 1}},
                {"template": "big_number", "seconds": 3, "voice": "GDP tăng 16,2%.",
                 "params": {"title": "Tăng trưởng GDP", "value": 16.2, "suffix": "%", "decimals": 1}}]
        st = web.build_story(spec, _timed(spec), "t3")["scenes"]
        self.assertEqual(st[1]["isotype"], {"mode": "share", "count": 39, "noun": "người"})
        self.assertNotIn("isotype", st[2])                 # % tăng trưởng không phải "x/100 người"
        self.assertEqual((st[1]["dec"], st[1]["value"]), (1, 38.8))


if __name__ == "__main__":
    unittest.main()
