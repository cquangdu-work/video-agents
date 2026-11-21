"""Ảnh bìa trang kênh (src/brand_kit.py) + chữ hồ sơ kênh trong cấu hình: luật bản đồ theo góc nhìn từng kênh, mọi
phần được nhấn nằm trong vùng mọi thiết bị đều thấy, chữ hồ sơ không vượt giới hạn của từng nền tảng."""
import unittest
from pathlib import Path

import yaml

from src import brand_kit as bk, lang
from src.render import web

ROOT = Path(__file__).resolve().parent.parent


def extents(kind: str, colors: dict) -> dict:
    """Khung bao của từng nước được nhấn, từng quần đảo và từng dòng chữ trên bản đồ (bề ngang chữ ước lượng rộng tay)."""
    lay = bk.map_layer(kind, colors)
    boxes = dict(lay["boxes"])
    for l in lay["labels"]:
        w = len(l["text"]) * l["size"] * (0.95 if lang.code() == "ko" else 0.6)
        x0 = l["x"] if l["anchor"] == "start" else l["x"] - w / 2
        boxes["chữ " + l["text"]] = (x0, l["y"] - l["size"] / 2, x0 + w, l["y"] + l["size"] / 2)
    return boxes


class BrandMapTest(unittest.TestCase):
    def setUp(self):
        self.colors = web.brand_props()

    def assert_inside(self, kind: str):
        x0, y0, x1, y1 = bk.SPECS[kind]["safe"]
        for name, (a, b, c, d) in extents(kind, self.colors).items():
            self.assertTrue(x0 <= a and c <= x1 and y0 <= b and d <= y1,
                            f"{lang.code()} {kind}: {name} {a:.0f},{b:.0f}-{c:.0f},{d:.0f} ra ngoài vùng an toàn")
        # khối chữ không đè lên phần được nhấn của bản đồ
        box = bk.SPECS[kind]["box"]
        left = min(a for a, *_ in extents(kind, self.colors).values())
        self.assertLess(box["x"] + box["w"], left, f"{lang.code()} {kind}: chữ đè lên bản đồ")

    def test_vietnamese_channel_always_draws_hoang_sa_truong_sa(self):
        with lang.using("vi"):
            for kind in bk.SPECS:
                lay = bk.map_layer(kind, self.colors)
                names = {l["text"] for l in lay["labels"]}
                self.assertTrue({"Hoàng Sa", "Trường Sa"} <= names, kind)
                self.assertTrue(lay["dots"])
                self.assertTrue(all(d[3] == self.colors["vietnam"] for d in lay["dots"]))   # cùng màu Việt Nam
                self.assertEqual({p["fill"] for p in lay["paths"] if p.get("glow")},
                                 {self.colors["vietnam"], self.colors["korea"]})
                self.assert_inside(kind)

    def test_korean_channel_draws_dokdo_and_east_sea_not_the_vietnamese_islands(self):
        with lang.using("ko"):
            for kind in bk.SPECS:
                lay = bk.map_layer(kind, self.colors)
                names = {l["text"] for l in lay["labels"]}
                self.assertIn("독도", names)
                self.assertIn("동해", names)
                self.assertFalse({"Hoàng Sa", "Trường Sa"} & names)
                self.assertTrue(all(d[3] == self.colors["korea"] for d in lay["dots"]))     # cùng màu Hàn Quốc
                self.assertEqual({p["fill"] for p in lay["paths"] if p.get("glow")}, {self.colors["korea"]})
                self.assert_inside(kind)

    def test_props_carry_channel_texts(self):
        cfg = yaml.safe_load((ROOT / "config" / "channel_ko.yaml").read_text(encoding="utf-8"))
        with lang.using("ko"):
            p = bk.props("banner", cfg)
        self.assertEqual(p["lang"], "ko")
        self.assertEqual(p["title"], ["숫자세계"])
        self.assertEqual(p["accent"], "숫자")
        self.assertNotIn("guides", p)
        self.assertNotIn("boxes", p["map"])


class ProfileTextTest(unittest.TestCase):
    """Giới hạn của từng nền tảng (tra 21/11/2026): mô tả kênh YouTube 1.000 ký tự, từ khoá kênh 500, giới thiệu
    Trang Facebook ~100, tiểu sử TikTok 80, tiểu sử Instagram 150, tên Instagram 64."""

    def check(self, name: str):
        cfg = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))
        p = cfg["profile"]
        self.assertLessEqual(len(p["youtube"]["description"]), 1000)
        kw = " ".join(f'"{k}"' if " " in k else k for k in p["youtube"]["keywords"])
        self.assertLessEqual(len(kw), 500)
        self.assertLessEqual(len(p["facebook_about"]), 100)
        self.assertNotIn("@", p["youtube"]["description"])          # repo công khai: không email cá nhân trong file
        for key, limit in (("tiktok_bio", 80), ("instagram_bio", 150), ("instagram_name", 64)):
            if key in p:
                self.assertLessEqual(len(p[key]), limit, key)
        b = p["banner"]
        self.assertTrue(any(b["accent"] in line for line in b["title"]))
        return p

    def test_vietnamese_channel(self):
        p = self.check("channel.yaml")
        self.assertIn("AI", p["youtube"]["description"])             # minh bạch giọng AI (chính sách YouTube)

    def test_korean_channel(self):
        p = self.check("channel_ko.yaml")
        self.assertIn("AI", p["youtube"]["description"])
        self.assertIn("instagram_bio", p)


if __name__ == "__main__":
    unittest.main()
