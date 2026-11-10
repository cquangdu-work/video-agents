"""5 template cảnh có tham số. Mỗi class = một loại chất liệu trong kho.

Quy ước: params là dict thuần (đến từ YAML/JSON do agent Sản xuất tạo),
mỗi template tự vẽ trong (seconds) giây — nằm trong nhịp 2-4s/cảnh.
"""
from manim import (DOWN, LEFT, ORIGIN, RIGHT, UP, Create, FadeIn, GrowFromEdge,
                   Line, Rectangle, Text, VGroup, ValueTracker, always_redraw,
                   Axes, Dot, linear)

from .base import BrandScene, fit_width, fmt_num, pick_font


class Intro(BrandScene):
    """Intro 1 giây: '0' nhảy thành '1' rồi hiện tên kênh — rẻ mà nhớ được."""

    def construct(self):
        c = self.b["colors"]
        self.add_signature()
        tr = ValueTracker(0)
        num = always_redraw(lambda: Text(
            f"{tr.get_value():.0f}", font=pick_font("number"), font_size=180,
            color=c["accent"], weight="BOLD").move_to(ORIGIN + UP * 1.2))
        self.add(num)
        name = Text(self.b["intro"]["text"], font=pick_font(), font_size=54,
                    color=c["text"], weight="BOLD").next_to(ORIGIN, DOWN, buff=0.6)
        self.play(tr.animate(rate_func=linear).set_value(1), FadeIn(name, shift=UP * 0.3),
                  run_time=max(self.seconds - 0.2, 0.5))
        self.wait(0.2)


class BigNumber(BrandScene):
    """Một con số khổng lồ đếm từ 0 — params:
    {title, value, suffix, source, decimals(=0), color(=accent)}"""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        tr = ValueTracker(0)
        dec = p.get("decimals", 0)
        color = c.get(p.get("color", "accent"), c["accent"])
        # Chọn cỡ chữ theo con số CUỐI (dài nhất) để không bao giờ tràn mép
        probe = Text(fmt_num(p["value"], dec), font=pick_font("number"),
                     font_size=140, weight="BOLD")
        fsize = 140 * min(7.9 / probe.width, 1)
        num = always_redraw(lambda: Text(
            fmt_num(tr.get_value(), dec), font=pick_font("number"), font_size=fsize,
            color=color, weight="BOLD").move_to(ORIGIN))
        self.add(num)
        if p.get("suffix"):
            self.add(Text(p["suffix"], font=pick_font(), font_size=44,
                          color=c["text"]).next_to(ORIGIN, DOWN, buff=1.4))
        self.play(tr.animate.set_value(p["value"]), run_time=self.seconds * 0.7)
        self.wait(self.seconds * 0.3)


class BarChart(BrandScene):
    """Thanh ngang mọc dần — params:
    {title, items: [{label, value, color?}], unit, source, decimals(=0)}"""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        items = sorted(p["items"], key=lambda i: -i["value"])[:6]
        vmax = max(i["value"] for i in items)
        max_w, bar_h, gap = 5.6, 0.62, 0.42
        dec = p.get("decimals", 0)
        rows, anims = VGroup(), []
        for idx, it in enumerate(items):
            y = 2.6 - idx * (bar_h + gap) * 1.6
            color = c.get(it.get("color", ""), c["accent"] if idx == 0 else c["surface"])
            bar = Rectangle(width=max(it["value"] / vmax * max_w, 0.1), height=bar_h,
                            fill_color=color, fill_opacity=1, stroke_width=0)
            bar.move_to([-4.2, y, 0], aligned_edge=LEFT)
            label = Text(it["label"], font=pick_font(), font_size=30, color=c["text"])
            label.next_to([-4.2, y + bar_h, 0], UP + RIGHT, buff=0.08).align_to(bar, LEFT)
            val = Text(fmt_num(it["value"], dec), font=pick_font("number"), font_size=32,
                       color=c["text"], weight="BOLD").next_to(bar, RIGHT, buff=0.15)
            rows.add(label, val)
            anims.append(GrowFromEdge(bar, LEFT))
        if p.get("unit"):
            rows.add(Text(p["unit"], font=pick_font(), font_size=26,
                          color=c["muted"]).move_to([0, -4.3, 0]))
        self.play(FadeIn(rows), *anims, run_time=self.seconds * 0.6)
        self.wait(self.seconds * 0.4)


class Versus(BrandScene):
    """So găng Việt - Hàn (hoặc 2 bên bất kỳ) — params:
    {title, left: {label, value}, right: {label, value}, suffix, source, decimals(=0)}"""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        dec = p.get("decimals", 0)
        trL, trR = ValueTracker(0), ValueTracker(0)
        sides = [(p["left"], c["vietnam"], -2.2, trL), (p["right"], c["korea"], 2.2, trR)]
        for side, color, x, tr in sides:
            self.add(Text(side["label"], font=pick_font(), font_size=40, color=color,
                          weight="BOLD").move_to([x, 2.2, 0]))
            self.add(always_redraw(lambda tr=tr, color=color, x=x: Text(
                fmt_num(tr.get_value(), dec), font=pick_font("number"), font_size=72,
                color=color, weight="BOLD").move_to([x, 0.6, 0])))
        self.add(Line([0, 2.6, 0], [0, -0.4, 0], color=c["muted"], stroke_width=2))
        if p.get("suffix"):
            self.add(Text(p["suffix"], font=pick_font(), font_size=36,
                          color=c["text"]).move_to([0, -1.6, 0]))
        self.play(trL.animate.set_value(p["left"]["value"]),
                  trR.animate.set_value(p["right"]["value"]),
                  run_time=self.seconds * 0.65)
        self.wait(self.seconds * 0.35)


class LineChart(BrandScene):
    """Đường xu hướng tự vẽ — params:
    {title, xs: [...], ys: [...], unit, source, color(=accent), decimals(=0)}"""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        xs, ys = p["xs"], p["ys"]
        color = c.get(p.get("color", "accent"), c["accent"])
        ax = Axes(x_range=[min(xs), max(xs), max((max(xs) - min(xs)) // 4, 1)],
                  y_range=[0, max(ys) * 1.15, max(max(ys) / 4, 1)],
                  x_length=7.2, y_length=6.0, tips=False,
                  axis_config={"color": c["muted"], "stroke_width": 2,
                               "include_numbers": False}).move_to([0.1, -0.4, 0])
        graph = ax.plot_line_graph(xs, ys, line_color=color, stroke_width=7,
                                   add_vertex_dots=False)
        end = Dot(ax.c2p(xs[-1], ys[-1]), color=color, radius=0.1)
        endval = Text(fmt_num(ys[-1], p.get("decimals", 0)), font=pick_font("number"),
                      font_size=40, color=color, weight="BOLD")
        endval.next_to(end, UP + LEFT, buff=0.12)
        span = Text(f"{xs[0]} → {xs[-1]}" + (f"  ·  {p['unit']}" if p.get("unit") else ""),
                    font=pick_font(), font_size=28, color=c["muted"]).move_to([0, -4.5, 0])
        self.add(ax, span)
        self.play(Create(graph, run_time=self.seconds * 0.6))
        self.play(FadeIn(end), FadeIn(endval), run_time=0.3)
        self.wait(max(self.seconds * 0.4 - 0.3, 0.1))


TEMPLATES = {
    "intro": Intro,
    "big_number": BigNumber,
    "bar_chart": BarChart,
    "versus": Versus,
    "line_chart": LineChart,
}
