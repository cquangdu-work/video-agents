"""Test công cụ vẽ avatar — không ghi file, chỉ kiểm ảnh tạo ra trong bộ nhớ.

    python -m unittest discover -s tests -v
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_tool():
    spec = importlib.util.spec_from_file_location("make_avatar", ROOT / "tools" / "make_avatar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class AvatarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.c = cls.tool.colors()

    def count_near(self, im, color, tol=30) -> int:
        """Số điểm ảnh có màu gần `color` (mọi kênh lệch không quá tol)."""
        import numpy as np
        px = np.asarray(im.convert("RGB"), dtype=int)
        return int((np.abs(px - np.array(hex_rgb(color))) <= tol).all(axis=2).sum())

    def test_both_avatars_are_800px_with_transparent_corners(self):
        for make in (self.tool.make_race, self.tool.make_vnkr):
            im = make(self.c)
            self.assertEqual(im.size, (800, 800))
            self.assertEqual(im.getpixel((2, 2))[3], 0)               # góc trong suốt: nền tảng tự cắt tròn

    def test_vnkr_shows_vietnam_and_korea_in_brand_colours(self):
        # Ca thật khi viết: Hàn Quốc bị đặt ra ngoài khung ảnh, không thấy đâu
        im = self.tool.make_vnkr(self.c)
        self.assertGreater(self.count_near(im, self.c["vietnam"]), 20000)
        self.assertGreater(self.count_near(im, self.c["korea"]), 3000)
        self.assertGreater(self.count_near(im, self.c["accent"]), 10000)   # viền + đường số liệu


if __name__ == "__main__":
    unittest.main()
