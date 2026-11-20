"""Lớp nền cho mọi cảnh: nền tối, lưới chấm, nhãn nguồn — chữ ký hình ảnh của kênh.

Mọi template kế thừa BrandScene nên tự động cùng một bộ nhận diện;
đổi màu/font cả kênh = sửa config/brand.yaml.
"""
from functools import lru_cache
from pathlib import Path

from .. import lang

import yaml
from manim import (DOWN, UP, Dot, Scene, Text, VGroup, config)

BRAND_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "brand.yaml"
_brand_cache = None


def brand() -> dict:
    global _brand_cache
    if _brand_cache is None:
        _brand_cache = yaml.safe_load(BRAND_PATH.read_text(encoding="utf-8"))
    return _brand_cache


@lru_cache(maxsize=None)
def pick_font(kind: str = "primary") -> str:
    """Chọn font đầu tiên trong danh sách ưu tiên mà máy có (Windows/Linux khác nhau).

    Nhớ kết quả: hàm này được gọi ở MỖI KHUNG HÌNH trong các cảnh đếm số (always_redraw),
    mà liệt kê font của cả máy rất chậm — đo 12/11: cảnh số lớn 10 giây render mất 327 giây."""
    import manimpango
    installed = set(manimpango.list_fonts())
    for f in brand()["fonts"][kind]:
        if f in installed:
            return f
    return "Sans"   # Pango luôn có fallback


def fmt_num(x: float, decimals: int = 0) -> str:
    """1234567 -> '1.234.567' (kiểu số của kênh, src/lang.py: kênh Hàn '1,234,567')."""
    return lang.fixed(x, decimals)


class BrandScene(Scene):
    """params: dict tham số của cảnh; seconds: thời lượng mục tiêu."""

    def __init__(self, params: dict = None, seconds: float = 3.0, **kwargs):
        self.params = params or {}
        self.seconds = seconds
        self.b = brand()
        config.background_color = self.b["colors"]["background"]
        super().__init__(**kwargs)

    # ---- các mảnh nhận diện dùng chung ----
    def add_signature(self, source: str = None):
        c = self.b["colors"]
        if self.b["signature"]["grid"]:
            fh, fw = config.frame_height, config.frame_width
            dots = VGroup(*[
                Dot([x, y, 0], radius=0.012, color=c["muted"],
                    fill_opacity=self.b["signature"]["grid_opacity"])
                for x in _steps(-fw / 2 + 0.4, fw / 2 - 0.4, 0.75)
                for y in _steps(-fh / 2 + 0.4, fh / 2 - 0.4, 0.75)
            ])
            self.add(dots)
        if source and self.b["signature"]["source_label"]:
            lbl = Text(f"Nguồn: {source}", font=pick_font(), font_size=22,
                       color=c["muted"])
            lbl.to_edge(DOWN, buff=0.55)
            self.add(lbl)

    def title_text(self, s: str, font_size: int = 52) -> Text:
        # Tiêu đề dài: NGẮT DÒNG thay vì để fit_width thu nhỏ cả câu (trước đây tiêu đề
        # 9 từ co lại còn cỡ chữ phụ đề, xem trên điện thoại không đọc nổi)
        t = Text(wrap_title(s), font=pick_font(), font_size=font_size,
                 color=self.b["colors"]["text"], weight="BOLD",
                 line_spacing=0.9)
        fit_width(t, config.frame_width - 0.9)
        t.to_edge(UP, buff=self.b["frame"]["margin_top"])
        return t


TITLE_LINE_CHARS = 24     # ~ số ký tự vừa một dòng tiêu đề cỡ 52 trên khung dọc


def wrap_title(s: str, width: int = TITLE_LINE_CHARS) -> str:
    """Ngắt tiêu đề dài thành tối đa 2 dòng cân nhau. Đã có xuống dòng sẵn thì giữ nguyên."""
    import textwrap
    s = " ".join(str(s).split()) if "\n" not in str(s) else str(s)
    if "\n" in s or len(s) <= width:
        return s
    words = s.split()
    best = None
    for k in range(1, len(words)):           # chọn chỗ ngắt cho hai dòng dài gần bằng nhau
        a, b = " ".join(words[:k]), " ".join(words[k:])
        score = max(len(a), len(b))
        if best is None or score <= best[0]:  # hoà thì lấy dòng đầu dài hơn (dạng tam giác ngược)
            best = (score, a + "\n" + b)
    if best and best[0] <= width + 6:
        return best[1]
    return "\n".join(textwrap.wrap(s, width))   # dài quá: ngắt nhiều dòng, fit_width lo phần còn lại


def fit_width(mobj, max_w: float):
    """Chữ/đồ vật rộng quá khung thì co lại cho vừa (tránh tràn mép video dọc)."""
    if mobj.width > max_w:
        mobj.scale(max_w / mobj.width)
    return mobj


def _steps(lo: float, hi: float, step: float):
    v = lo
    while v <= hi:
        yield v
        v += step
