"""Các template cảnh có tham số. Mỗi class = một loại chất liệu trong kho.

Quy ước: params là dict thuần (đến từ YAML/JSON do agent Sản xuất tạo),
mỗi template tự vẽ trong (seconds) giây — nằm trong nhịp 2-4s/cảnh.
"""
import re

from manim import (DOWN, LEFT, ORIGIN, PI, RIGHT, TAU, UP, Arc, Circle, Create, FadeIn,
                   GrowFromEdge, Line, Rectangle, Text, VGroup, ValueTracker, always_redraw,
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
        # Cỡ chữ chung cho 2 bên, dò theo số DÀI nhất để không tràn cột (~3.9 đơn vị)
        widest = max(
            Text(fmt_num(s["value"], dec), font=pick_font("number"), font_size=72,
                 weight="BOLD").width for s in (p["left"], p["right"]))
        fsize = 72 * min(3.9 / widest, 1)
        for side, color, x, tr in sides:
            lbl = Text(side["label"], font=pick_font(), font_size=40, color=color,
                       weight="BOLD").move_to([x, 2.2, 0])
            fit_width(lbl, 4.0)
            self.add(lbl)
            self.add(always_redraw(lambda tr=tr, color=color, x=x: Text(
                fmt_num(tr.get_value(), dec), font=pick_font("number"), font_size=fsize,
                color=color, weight="BOLD").move_to([x, 0.6, 0])))
        self.add(Line([0, 2.6, 0], [0, -0.4, 0], color=c["muted"], stroke_width=2))
        if p.get("suffix"):
            self.add(Text(p["suffix"], font=pick_font(), font_size=36,
                          color=c["text"]).move_to([0, -1.6, 0]))
        self.play(trL.animate.set_value(p["left"]["value"]),
                  trR.animate.set_value(p["right"]["value"]),
                  run_time=self.seconds * 0.65)
        self.wait(self.seconds * 0.35)


def chart_series(p: dict, colors: dict) -> list:
    """Các đường của một line_chart -> [(nhãn, xs, ys, màu)].

    Một đường: {xs, ys, color?}. Nhiều đường (so hai nước qua các năm):
    {xs, series: [{label, ys, xs?, color?}, ...]} — mỗi đường được có trục năm riêng
    (số liệu hai nước hay lệch năm cuối: Việt Nam tới 2024, Hàn Quốc tới 2025).
    Màu đặt theo tên trong bộ nhận diện ("vietnam" đỏ, "korea" xanh); không ghi màu thì
    nhãn "Việt Nam"/"Hàn Quốc" tự nhận màu."""
    auto = {"việt nam": "vietnam", "vn": "vietnam", "hàn quốc": "korea", "kr": "korea"}
    if p.get("series"):
        keys = [s.get("color") or auto.get(str(s.get("label", "")).strip().lower())
                for s in p["series"]]
        spare = [k for k in ("accent", "good", "korea", "bad", "vietnam") if k not in keys]
        out = []
        for s, key in zip(p["series"], keys):
            if not key:                          # đường không rõ nước: lấy màu chưa ai dùng
                key = spare.pop(0) if spare else "accent"
            out.append((str(s.get("label", "")), list(s.get("xs") or p["xs"]), list(s["ys"]),
                        colors.get(key, colors["accent"])))
        return out
    return [("", list(p["xs"]), list(p["ys"]),
             colors.get(p.get("color", "accent"), colors["accent"]))]


class LineChart(BrandScene):
    """Đường xu hướng tự vẽ — params:
    {title, xs: [...], ys: [...], unit, source, color(=accent), decimals(=0)}
    hoặc nhiều đường trên cùng trục (Việt Nam vs Hàn Quốc qua các năm):
    {title, xs: [...], series: [{label, ys, color?}, ...], unit, source, decimals}"""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        lines = chart_series(p, c)
        x0 = min(min(xs) for _, xs, _, _ in lines)
        x1 = max(max(xs) for _, xs, _, _ in lines)
        top = max(max(ys) for _, _, ys, _ in lines)
        dec = p.get("decimals", 0)
        ax = Axes(x_range=[x0, x1, max((x1 - x0) // 4, 1)],
                  y_range=[0, top * 1.15, max(top / 4, 1e-9)],
                  x_length=7.2, y_length=6.0, tips=False,
                  axis_config={"color": c["muted"], "stroke_width": 2,
                               "include_numbers": False}).move_to([0.1, -0.4, 0])
        graphs, ends = [], VGroup()
        for label, xs, ys, color in lines:
            graphs.append(ax.plot_line_graph(xs, ys, line_color=color, stroke_width=7,
                                             add_vertex_dots=False))
            end = Dot(ax.c2p(xs[-1], ys[-1]), color=color, radius=0.1)
            val = Text(fmt_num(ys[-1], dec), font=pick_font("number"), font_size=40,
                       color=color, weight="BOLD")
            val.next_to(end, UP + LEFT, buff=0.12)
            ends.add(end, val)
        # Hai đường kết thúc gần nhau -> hai nhãn số dính vào nhau (đo được: hở 0,15 đơn vị
        # là đã dính khi xem trên điện thoại). Nhãn của đường THẤP chuyển xuống dưới điểm cuối.
        pairs = [(ends[k], ends[k + 1]) for k in range(0, len(ends), 2)]
        if len(pairs) == 2:
            (dot_lo, val_lo), (_, val_hi) = sorted(pairs, key=lambda d_v: d_v[0].get_center()[1])
            if val_hi.get_bottom()[1] - val_lo.get_top()[1] < 0.35:
                val_lo.next_to(dot_lo, DOWN + LEFT, buff=0.12)
        span = Text(f"{x0} → {x1}" + (f"  ·  {p['unit']}" if p.get("unit") else ""),
                    font=pick_font(), font_size=28, color=c["muted"]).move_to([0, -4.5, 0])
        self.add(ax, span)
        if len(lines) > 1:                       # chú thích màu ngay dưới tiêu đề
            legend = VGroup(*[
                VGroup(Line(ORIGIN, RIGHT * 0.6, color=color, stroke_width=8),
                       Text(label, font=pick_font(), font_size=34, color=color, weight="BOLD")
                       ).arrange(RIGHT, buff=0.2)
                for label, _, _, color in lines]).arrange(RIGHT, buff=0.8).move_to([0, 3.4, 0])
            fit_width(legend, 8.0)
            self.add(legend)
        self.play(*[Create(g) for g in graphs], run_time=self.seconds * 0.6)
        self.play(FadeIn(ends), run_time=0.3)
        self.wait(max(self.seconds * 0.4 - 0.3, 0.1))


def highlights(text: str) -> list:
    """Những mẩu chữ đáng tô màu nhấn trong một câu: con số ('8.030', '38,4%') và
    chữ viết tắt in hoa ('AI', 'GDP'). Kênh tên là "qua con số" nên số luôn phát sáng."""
    # số có thể kèm dấu chấm/phẩy/gạch chéo ở giữa: "8.030", "38,4%", "05/2023"
    found = re.findall(r"\d[\d.,/]*\d%?|\d%?|\b[A-ZĐ]{2,}\b", text)
    return sorted(set(found), key=len, reverse=True)


STATEMENT_STYLES = 3


class Statement(BrandScene):
    """Câu dẫn/chuyển tiếp KHÔNG có biểu đồ — params: {text, source?, style?, n?}

    Một video có thể có 10-18 cảnh chữ; cùng một bố cục lặp mãi là "nội dung theo
    mẫu". Nên có 3 kiểu, produce.validate_spec xoay vòng (params.style):
      0  chữ giữa màn + gạch nhấn bên dưới
      1  chữ canh trái + thanh dọc màu nhấn chạy từ trên xuống
      2  số thứ tự khổng lồ mờ phía sau (params.n) + chữ bên dưới
    Con số và chữ viết tắt trong câu luôn được tô màu nhấn.
    """

    def construct(self):
        import textwrap
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        text = str(p["text"])
        style = p.get("style")
        if style is None:                       # spec đời cũ chưa gắn kiểu: suy từ chính câu chữ
            style = sum(map(ord, text)) % 2     # (kiểu 2 cần params.n nên không tự chọn)
        if style == 2 and not p.get("n"):
            style = 0
        body = "\n".join(textwrap.wrap(text, 20 if style != 1 else 18))
        t = Text(body, font=pick_font(), font_size=58, color=c["text"], weight="BOLD",
                 line_spacing=1.05, t2c={h: c["accent"] for h in highlights(text)})
        intro = min(self.seconds * 0.4, 0.8)
        if style == 1:
            fit_width(t, 7.0)
            t.move_to(ORIGIN).align_to([-3.3, 0, 0], LEFT)
            bar = Line([-3.85, t.get_top()[1] + 0.15, 0], [-3.85, t.get_bottom()[1] - 0.15, 0],
                       color=c["accent"], stroke_width=10)
            self.play(GrowFromEdge(bar, UP), FadeIn(t, shift=RIGHT * 0.5), run_time=intro)
        elif style == 2:
            fit_width(t, 7.9)
            ghost = Text(f"{int(p['n']):02d}", font=pick_font("number"), font_size=400,
                         color=c["surface"], weight="BOLD").move_to([0, 2.7, 0])
            t.next_to(ghost, DOWN, buff=0.9)
            dot = Dot(t.get_corner(UP + LEFT) + UP * 0.45 + RIGHT * 0.12, radius=0.11,
                      color=c["accent"])
            self.play(FadeIn(ghost, scale=1.15), FadeIn(t, shift=UP * 0.4), FadeIn(dot),
                      run_time=intro)
        else:
            fit_width(t, 7.9)
            t.move_to(ORIGIN)
            bar = Line(ORIGIN, RIGHT * 1.6, color=c["accent"], stroke_width=8)
            bar.next_to(t, DOWN, buff=0.7)
            self.play(FadeIn(t, shift=UP * 0.4), GrowFromEdge(bar, LEFT), run_time=intro)
        self.wait(max(self.seconds - intro, 0.1))


class PercentRing(BrandScene):
    """Vòng tròn tô dần tới X% — params: {title, value (0-100), label?, source, decimals(=0)}
    Dùng cho MỘT tỷ lệ phần trăm; mắt thấy ngay "phần đó to cỡ nào" thay vì chỉ đọc số."""

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        value = max(0.0, min(float(p["value"]), 100.0))
        dec = p.get("decimals", 0)
        center, radius, width = [0, -0.3, 0], 2.5, 46
        track = Circle(radius=radius, color=c["surface"], stroke_width=width).move_to(center)
        tr = ValueTracker(0)
        arc = always_redraw(lambda: Arc(
            radius=radius, start_angle=PI / 2, angle=-TAU * max(tr.get_value(), 0.05) / 100,
            arc_center=center, color=c["accent"], stroke_width=width))
        probe = Text(fmt_num(value, dec) + "%", font=pick_font("number"), font_size=110,
                     weight="BOLD")
        fsize = 110 * min(3.5 / probe.width, 1)
        num = always_redraw(lambda: Text(
            fmt_num(tr.get_value(), dec) + "%", font=pick_font("number"), font_size=fsize,
            color=c["accent"], weight="BOLD").move_to(center))
        self.add(track, arc, num)
        if p.get("label"):
            lbl = Text(p["label"], font=pick_font(), font_size=40, color=c["text"])
            fit_width(lbl, 7.6)
            self.add(lbl.move_to([0, -3.9, 0]))
        self.play(tr.animate.set_value(value), run_time=self.seconds * 0.7)
        self.wait(self.seconds * 0.3)


TEMPLATES = {
    "statement": Statement,
    "intro": Intro,
    "big_number": BigNumber,
    "bar_chart": BarChart,
    "versus": Versus,
    "line_chart": LineChart,
    "percent": PercentRing,
}
