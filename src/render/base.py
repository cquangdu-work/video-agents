"""Lớp nền cho mọi cảnh: nền tối, lưới chấm, nhãn nguồn — chữ ký hình ảnh của kênh.

Mọi template kế thừa BrandScene nên tự động cùng một bộ nhận diện;
đổi màu/font cả kênh = sửa config/brand.yaml.
"""
from pathlib import Path

import yaml
from manim import (DOWN, UP, Dot, Scene, Text, VGroup, config)

BRAND_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "brand.yaml"
_brand_cache = None


def brand() -> dict:
    global _brand_cache
    if _brand_cache is None:
        _brand_cache = yaml.safe_load(BRAND_PATH.read_text(encoding="utf-8"))
    return _brand_cache


def pick_font(kind: str = "primary") -> str:
    """Chọn font đầu tiên trong danh sách ưu tiên mà máy có (Windows/Linux khác nhau)."""
    import manimpango
    installed = set(manimpango.list_fonts())
    for f in brand()["fonts"][kind]:
        if f in installed:
            return f
    return "Sans"   # Pango luôn có fallback


def fmt_num(x: float, decimals: int = 0) -> str:
    """1234567 -> '1.234.567' (kiểu Việt Nam)."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


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
        t = Text(s, font=pick_font(), font_size=font_size,
                 color=self.b["colors"]["text"], weight="BOLD",
                 line_spacing=0.9)
        fit_width(t, config.frame_width - 0.9)
        t.to_edge(UP, buff=self.b["frame"]["margin_top"])
        return t


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
