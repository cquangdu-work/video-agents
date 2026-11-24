"""Các template cảnh có tham số. Mỗi class = một loại chất liệu trong kho.

Quy ước: params là dict thuần (đến từ YAML/JSON do agent Sản xuất tạo),
mỗi template tự vẽ trong (seconds) giây — nằm trong nhịp 2-4s/cảnh.
"""
import re

from manim import (DOWN, LEFT, ORIGIN, PI, RIGHT, TAU, UP, Arc, Circle, Create, FadeIn,
                   GrowFromEdge, Line, Rectangle, Text, Transform, VGroup, ValueTracker,
                   always_redraw, Axes, Dot, linear)

from .base import BrandScene, fit_width, fmt_num, pick_font


def label_decimals(value: float, decimals: int) -> int:
    """Ít chữ số thập phân nhất mà vẫn KHÔNG làm tròn mất giá trị (tối đa `decimals`):
    2756.0 -> 0 ("2.756", không phải "2.756,0"), 98.9 -> 1, 0.75 -> 2."""
    d = 0
    while d < decimals and round(value, d) != round(value, decimals):
        d += 1
    return d


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
        # Cột cuối không xuống dưới y=-3,4: dưới đó là chữ đơn vị rồi tới vùng phụ đề (ca thật
        # kịch bản #7: 5 cột thì cột cuối đè chữ "tuổi", 6 cột thì rơi vào phụ đề)
        pitch = min((bar_h + gap) * 1.6, 6.0 / max(len(items) - 1, 1))
        y_last = 2.6 - (len(items) - 1) * pitch
        for idx, it in enumerate(items):
            y = 2.6 - idx * pitch
            color = c.get(it.get("color", ""), c["accent"] if idx == 0 else c["surface"])
            bar = Rectangle(width=max(it["value"] / vmax * max_w, 0.1), height=bar_h,
                            fill_color=color, fill_opacity=1, stroke_width=0)
            bar.move_to([-4.2, y, 0], aligned_edge=LEFT)
            label = Text(it["label"], font=pick_font(), font_size=30, color=c["text"])
            label.next_to([-4.2, y + bar_h, 0], UP + RIGHT, buff=0.08).align_to(bar, LEFT)
            val = Text(fmt_num(it["value"], label_decimals(float(it["value"]), dec)),
                       font=pick_font("number"), font_size=32,
                       color=c["text"], weight="BOLD").next_to(bar, RIGHT, buff=0.15)
            rows.add(label, val)
            anims.append(GrowFromEdge(bar, LEFT))
        if p.get("unit"):
            rows.add(Text(p["unit"], font=pick_font(), font_size=26,
                          color=c["muted"]).move_to([0, min(y_last - bar_h / 2 - 0.45, -2.0), 0]))
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
        left_c, right_c = versus_colors(p["left"].get("label"), p["right"].get("label"), c)
        sides = [(p["left"], left_c, -2.2, trL), (p["right"], right_c, 2.2, trR)]
        # Mỗi bên chỉ hiện số lẻ khi giá trị của CHÍNH nó có phần lẻ (98,9 bên này không được
        # biến 2.462 bên kia thành "2.462,0" — Kiểm định đã bắt lỗi này)
        side_dec = [label_decimals(float(s["value"]), dec) for s in (p["left"], p["right"])]
        # Cỡ chữ chung cho 2 bên, dò theo số DÀI nhất để không tràn cột (~3.9 đơn vị)
        widest = max(
            Text(fmt_num(s["value"], d), font=pick_font("number"), font_size=72,
                 weight="BOLD").width for s, d in zip((p["left"], p["right"]), side_dec))
        fsize = 72 * min(3.9 / widest, 1)
        for (side, color, x, tr), d in zip(sides, side_dec):
            lbl = Text(side["label"], font=pick_font(), font_size=40, color=color,
                       weight="BOLD").move_to([x, 2.2, 0])
            fit_width(lbl, 4.0)
            self.add(lbl)
            self.add(always_redraw(lambda tr=tr, color=color, x=x, d=d: Text(
                fmt_num(tr.get_value(), d), font=pick_font("number"), font_size=fsize,
                color=color, weight="BOLD").move_to([x, 0.6, 0])))
        self.add(Line([0, 2.6, 0], [0, -0.4, 0], color=c["muted"], stroke_width=2))
        if p.get("suffix"):
            self.add(Text(p["suffix"], font=pick_font(), font_size=36,
                          color=c["text"]).move_to([0, -1.6, 0]))
        self.play(trL.animate.set_value(p["left"]["value"]),
                  trR.animate.set_value(p["right"]["value"]),
                  run_time=self.seconds * 0.65)
        self.wait(self.seconds * 0.35)


COUNTRY_COLORS = {"việt nam": "vietnam", "vn": "vietnam", "hàn quốc": "korea", "kr": "korea",
                  "한국": "korea", "대한민국": "korea", "일본": "japan"}          # kênh tiếng Hàn


def country_color_key(label) -> str:
    """Tên màu trong bộ nhận diện cho một nhãn nước ("Việt Nam" -> "vietnam"), hoặc None."""
    return COUNTRY_COLORS.get(str(label or "").strip().lower())


def versus_colors(left_label, right_label, colors: dict) -> tuple:
    """Màu hai bên cảnh so găng: Việt Nam luôn đỏ, Hàn Quốc luôn xanh, bất kể đứng bên nào;
    nước khác lấy màu nhấn / màu chữ (trước đây trái luôn đỏ, phải luôn xanh: "Hàn Quốc vs
    Nhật Bản" tô Hàn Quốc màu của Việt Nam)."""
    keys = [country_color_key(left_label), country_color_key(right_label)]
    spare = [k for k in ("accent", "text") if k not in keys]
    keys = [k or spare.pop(0) for k in keys]
    return colors[keys[0]], colors[keys[1]]


def chart_series(p: dict, colors: dict) -> list:
    """Các đường của một line_chart -> [(nhãn, xs, ys, màu)].

    Một đường: {xs, ys, color?}. Nhiều đường (so hai nước qua các năm):
    {xs, series: [{label, ys, xs?, color?}, ...]} — mỗi đường được có trục năm riêng
    (số liệu hai nước hay lệch năm cuối: Việt Nam tới 2024, Hàn Quốc tới 2025).
    Màu đặt theo tên trong bộ nhận diện ("vietnam" đỏ, "korea" xanh); không ghi màu thì
    nhãn "Việt Nam"/"Hàn Quốc" tự nhận màu."""
    if p.get("series"):
        keys = [s.get("color") or country_color_key(s.get("label")) for s in p["series"]]
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
            val = Text(fmt_num(ys[-1], label_decimals(ys[-1], dec)), font=pick_font("number"),
                       font_size=40, color=color, weight="BOLD")
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


class BarRace(BrandScene):
    """Cuộc đua số liệu: thanh ngang của nhiều nước đổi độ dài và ĐỔI CHỖ theo thứ hạng
    qua từng mốc năm — params:
    {title, years: [...], items: [{label, values: [...], color?}], unit, source, decimals}
    mỗi "values" dài bằng "years". Việt Nam đỏ, Hàn Quốc xanh, nước khác màu trung tính.

    Chạy hết các mốc trong 75% thời lượng cảnh rồi DỪNG ở năm cuối: khung Kiểm định lấy
    mẫu ở 85% cảnh sẽ thấy đúng số liệu năm cuối, không phải số đang chuyển."""

    LABEL_X, BAR_X, BAR_W, TOP_Y = -1.6, -1.45, 4.2, 3.7

    def construct(self):
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        years, items = list(p["years"]), list(p["items"])
        n, dec = len(items), p.get("decimals", 0)
        row_h = min(0.72, 7.2 / max(n, 1))
        bar_h = row_h * 0.64
        keys = [it.get("color") or country_color_key(it.get("label")) for it in items]
        fill = [c.get(k, c["accent"]) if k else c["muted"] for k in keys]
        ink = [c.get(k, c["accent"]) if k else c["text"] for k in keys]

        def layout(k: int) -> list:
            """Mốc năm thứ k -> [(y, độ dài thanh, giá trị)] cho từng nước, theo thứ hạng."""
            vals = [float(it["values"][k]) for it in items]
            vmax = max(vals) or 1.0
            rank = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: -vals[i]))}
            return [(self.TOP_Y - rank[i] * row_h, max(vals[i] / vmax * self.BAR_W, 0.04), vals[i])
                    for i in range(n)]

        def bar(i, y, w):
            return Rectangle(width=w, height=bar_h, fill_color=fill[i], stroke_width=0,
                             fill_opacity=1 if keys[i] else 0.45).move_to([self.BAR_X + w / 2, y, 0])

        def value(i, y, w, v):
            t = Text(fmt_num(v, label_decimals(v, dec)), font=pick_font("number"), font_size=26,
                     color=ink[i], weight="BOLD")
            return t.move_to([self.BAR_X + w + 0.12, y, 0], aligned_edge=LEFT)

        def year(k):
            # Sát dưới thanh cuối, KHÔNG xuống vùng phụ đề (đáy khung ~ y -4,7 trở xuống):
            # bản đầu đặt thấp hơn 0,5 đơn vị và số năm bị phụ đề đè lên
            return Text(str(years[k]), font=pick_font("number"), font_size=100, color=c["muted"],
                        weight="BOLD").move_to([2.2, self.TOP_Y - n * row_h - 0.4, 0])

        first = layout(0)
        bars = [bar(i, y, w) for i, (y, w, _) in enumerate(first)]
        vals = [value(i, y, w, v) for i, (y, w, v) in enumerate(first)]
        labels = [fit_width(Text(str(it["label"]), font=pick_font(), font_size=28, color=ink[i],
                                 weight="BOLD" if keys[i] else "NORMAL"), 2.6)
                  .move_to([self.LABEL_X, first[i][0], 0], aligned_edge=RIGHT)
                  for i, it in enumerate(items)]
        stamp = year(0)
        extra = []
        if p.get("unit"):
            extra.append(Text(p["unit"], font=pick_font(), font_size=26, color=c["muted"])
                         .move_to([-2.0, stamp.get_center()[1], 0]))
        self.play(FadeIn(VGroup(*bars, *vals, *labels, stamp, *extra)), run_time=0.4)
        race_time = max(self.seconds * 0.75 - 0.4, 0.5)
        now = first
        for k in range(1, len(years)):
            target = layout(k)
            # Năm và con số đổi NGAY đầu chặng (biến hình từng nét chữ thì nhòe "20↯5" và
            # render chậm gấp mấy lần); sau đó thanh, nhãn, số cùng trượt tới chỗ mới.
            new_stamp = year(k)
            self.remove(stamp)
            self.add(new_stamp)
            stamp = new_stamp
            anims = []
            for i, ((y0, w0, _), (y, w, v)) in enumerate(zip(now, target)):
                fresh = value(i, y0, w0, v)
                self.remove(vals[i])
                self.add(fresh)
                vals[i] = fresh
                anims += [Transform(bars[i], bar(i, y, w)),
                          fresh.animate.move_to([self.BAR_X + w + 0.12, y, 0], aligned_edge=LEFT),
                          labels[i].animate.move_to([self.LABEL_X, y, 0], aligned_edge=RIGHT)]
            self.play(*anims, run_time=race_time / (len(years) - 1))
            now = target
        self.wait(max(self.seconds - 0.4 - race_time, 0.1))


class MapScene(BrandScene):
    """Bản đồ tô màu theo số liệu (choropleth) — params:
    {title, year?, items: [{label, value, code?, rank?}], unit, source, decimals,
     region: "asia" | "world" (cửa kiểm spec tự chọn: mọi nước ở châu Á -> bản đồ châu Á)}
    Nước có số: tô từ màu nền phụ (thấp) tới màu nhấn (cao) THEO THỨ HẠNG (một nước vượt trội
    như Singapore không làm cả bản đồ nhạt đi). Nước không có số: chỉ vẽ viền mờ.
    Việt Nam và Hàn Quốc: viền màu riêng + nhãn số. Nước quá nhỏ (Singapore): thêm chấm tròn."""

    MAP_W, MAP_H, MAP_CENTER = 8.4, 6.6, (0.0, 0.3)

    def construct(self):
        from manim import interpolate_color, ManimColor
        from .geo import code_of
        p, c = self.params, self.b["colors"]
        self.add_signature(p.get("source"))
        self.add(self.title_text(p["title"]))
        from ..sources.datatable import ranks_desc
        data, given_rank = {}, {}
        for it in p["items"]:
            code = it.get("code") or code_of(it["label"])
            if code:
                data[code] = (it["label"], float(it["value"]))
                if isinstance(it.get("rank"), int):
                    given_rank[code] = it["rank"]
        # thứ hạng từ cao xuống thấp: lấy hạng đã điền sẵn (khớp lời đọc), thiếu thì tự tính
        self.rank = {**ranks_desc({k: v[1] for k, v in data.items()}), **given_rank}
        order = sorted(data, key=lambda k: data[k][1])
        low, high = ManimColor(c["surface"]), ManimColor(c["accent"])
        shade = {k: interpolate_color(low, high, 0.15 + 0.85 * r / max(len(order) - 1, 1))
                 for r, k in enumerate(order)}
        if p.get("region") == "world":
            return self.world(data, order, shade, low, high)
        if p.get("region") == "kr":
            return self.provinces(data, order, shade, low, high)
        self.asia(data, order, shade, low, high)

    def legend(self, data, order, low, high, y: float):
        """Thang màu thấp -> cao kèm số hai đầu và dòng "năm · đơn vị"."""
        from manim import interpolate_color
        p, c, dec = self.params, self.b["colors"], self.params.get("decimals", 0)
        if not order:
            return VGroup()
        bar = VGroup(*[Rectangle(width=0.32, height=0.18, stroke_width=0,
                                 fill_color=interpolate_color(low, high, 0.15 + 0.85 * i / 9),
                                 fill_opacity=1) for i in range(10)]).arrange(RIGHT, buff=0)
        lo_v, hi_v = data[order[0]][1], data[order[-1]][1]
        lo_t = Text(fmt_num(lo_v, label_decimals(lo_v, dec)), font=pick_font("number"),
                    font_size=24, color=c["text"]).next_to(bar, LEFT, buff=0.15)
        hi_t = Text(fmt_num(hi_v, label_decimals(hi_v, dec)), font=pick_font("number"),
                    font_size=24, color=c["text"]).next_to(bar, RIGHT, buff=0.15)
        caption = " · ".join(x for x in (str(p.get("year") or ""), p.get("unit", "")) if x)
        cap = Text(caption, font=pick_font(), font_size=24, color=c["muted"])
        return VGroup(VGroup(lo_t, bar, hi_t), cap).arrange(DOWN, buff=0.12).move_to([0, y, 0])

    # ---------------------------------------------------------------- bản đồ thế giới
    # Tiêu đề hai dòng kết thúc ở y≈4,1 -> mép trên bản đồ (cao 3,76) phải thấp hơn mức đó
    WORLD_W, WORLD_H, WORLD_CENTER = 8.6, 4.6, (0.0, 1.85)
    INSET_W, INSET_CENTER = 2.6, (2.8, -1.6)

    def world(self, data, order, shade, low, high):
        """Thế giới + ô phóng to Việt Nam/Biển Đông (đủ chỗ ghi tên Hoàng Sa, Trường Sa) +
        khung số: Việt Nam, Hàn Quốc (giá trị, thứ hạng) và nơi cao nhất."""
        from manim import Polygon, LaggedStart
        from .. import lang
        from .geo import clip_ring, display_name, focus_countries, inset_bbox, islands, load_map, projector, sea_labels
        # theo góc nhìn của kênh: Hoàng Sa/Trường Sa + Biển Đông (Việt) | Dokdo + 동해 (Hàn)
        VN_ISLANDS, INSET_BBOX, FOCUS = islands(), inset_bbox(), focus_countries()
        anchor, anchor_key = FOCUS[0]
        p, c, dec = self.params, self.b["colors"], self.params.get("decimals", 0)
        to_xy = projector(self.WORLD_W, self.WORLD_H, self.WORLD_CENTER, "world")
        world = load_map("world")["countries"]

        def shapes(rings, project, **style):
            return VGroup(*[Polygon(*[project(lon, lat) for lon, lat in ring[:-1]], **style)
                            for ring in rings if len(ring) >= 4])

        base = VGroup()
        bands = [VGroup() for _ in range(10)]        # tô theo 10 nhóm thứ hạng (nhẹ hơn 200 hiệu ứng)
        n = len(order)
        rank_of = {k: r for r, k in enumerate(order)}
        for code, country in world.items():
            outline = shapes(country["rings"], to_xy, stroke_color=c["muted"], stroke_width=0.6,
                             stroke_opacity=0.5, fill_opacity=0)
            base.add(outline)
            if code not in data:
                continue
            band = bands[min(int(10 * rank_of[code] / max(n, 1)), 9)]
            band.add(outline.copy().set_fill(shade[code], opacity=1)
                     .set_stroke(c["background"], width=0.5, opacity=1))
            xs = [q[0] for ring in country["rings"] for q in ring]
            ys = [q[1] for ring in country["rings"] for q in ring]
            if max(xs) - min(xs) < 1.5 and max(ys) - min(ys) < 1.5:   # nhỏ quá: thêm chấm
                band.add(Dot(to_xy((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                             radius=0.035, color=shade[code]))
        vn_color = shade.get(anchor, c["muted"])
        for _, spots, _, _ in VN_ISLANDS:            # đảo tự vẽ luôn có, cùng màu nước "ta"
            base.add(*[Dot(to_xy(lon, lat), radius=0.012, color=vn_color) for lon, lat in spots])

        # Ô phóng to: vẽ từ bản đồ châu Á (chi tiết hơn), cắt đa giác theo khung ô
        lon0, lat0, lon1, lat1 = INSET_BBOX
        to_in = projector(self.INSET_W, self.INSET_W, self.INSET_CENTER, "asia", bbox=INSET_BBOX)
        frame_pts = [to_in(lon0, lat0), to_in(lon1, lat0), to_in(lon1, lat1), to_in(lon0, lat1)]
        inset = VGroup(Polygon(*frame_pts, stroke_color=c["muted"], stroke_width=1.5,
                               fill_color=c["background"], fill_opacity=1))
        for code, country in load_map("asia")["countries"].items():
            rings = [r for r in (clip_ring(ring, INSET_BBOX) for ring in country["rings"]) if len(r) >= 3]
            if not rings:
                continue
            filled = code in data
            edge = (c[anchor_key], 2) if code == anchor else (c["background"], 1) if filled else (c["muted"], 0.8)
            inset.add(VGroup(*[Polygon(*[to_in(lon, lat) for lon, lat in ring],
                                       stroke_color=edge[0], stroke_width=edge[1],
                                       stroke_opacity=1 if filled else 0.5,
                                       fill_color=shade.get(code, c["background"]),
                                       fill_opacity=1 if filled else 0) for ring in rings]))
        for name, spots, (lab_lon, lab_lat), align in VN_ISLANDS:
            inset.add(*[Dot(to_in(lon, lat), radius=0.03, color=vn_color) for lon, lat in spots])
            label = Text(name, font=pick_font(), font_size=14, color=c[anchor_key])
            label.move_to(to_in(lab_lon, lab_lat), aligned_edge=LEFT if align == "left" else ORIGIN)
            overflow = label.get_right()[0] - (frame_pts[1][0] - 0.06)   # chữ không chạm mép ô
            if overflow > 0:
                label.shift(LEFT * overflow)
            inset.add(label)
        for name, (lon, lat) in sea_labels():          # tên biển theo góc nhìn của kênh (동해)
            inset.add(Text(name, font=pick_font(), font_size=14, color=c["muted"]).move_to(to_in(lon, lat)))
        # khung nhỏ trên bản đồ thế giới + hai tia nối xuống ô phóng to
        mark = [to_xy(lon0, lat0), to_xy(lon1, lat0), to_xy(lon1, lat1), to_xy(lon0, lat1)]
        zoom = VGroup(Polygon(*mark, stroke_color=c["text"], stroke_width=1.5, fill_opacity=0),
                      Line(mark[0], frame_pts[3], color=c["muted"], stroke_width=1),
                      Line(mark[1], frame_pts[2], color=c["muted"], stroke_width=1))

        # Viền Việt Nam, Hàn Quốc trên bản đồ thế giới + khung số bên trái
        outlines, rows = VGroup(), []
        for code, key in FOCUS:
            if code not in data:
                continue
            outlines.add(shapes(world[code]["rings"], to_xy, stroke_color=c[key], stroke_width=2.5,
                                fill_opacity=0))
            rows.append((data[code][0], data[code][1], c[key], self.rank[code]))
        if order and order[-1] not in [k for k, _ in FOCUS]:
            top = order[-1]
            rows.append((lang.pick(vi="Cao nhất: ", ko="1위: ") + display_name(top), data[top][1], c["accent"],
                         self.rank[top]))
        n = int(p.get("total") or n)
        panel = VGroup()
        for label, value, color, rank in rows:
            head = Text(label, font=pick_font(), font_size=24, color=color, weight="BOLD")
            fit_width(head, 4.6)
            num = Text(fmt_num(value, label_decimals(value, dec)), font=pick_font("number"),
                       font_size=36, color=color, weight="BOLD")
            # nửa dưới bảng nói "thấp thứ 2/214" (khớp tóm tắt), không "cao thứ 213/214"
            from_bottom = 1 + sum(1 for _, v in data.values() if v < value)
            pos = Text(lang.pick(vi=f"cao thứ {rank}/{n}", ko=f"{n}곳 중 {rank}위") if rank <= n / 2
                       else lang.pick(vi=f"thấp thứ {from_bottom}/{n}", ko=f"하위 {from_bottom}위/{n}"),
                       font=pick_font(), font_size=20, color=c["text"])
            panel.add(VGroup(head, VGroup(num, pos).arrange(RIGHT, buff=0.2, aligned_edge=DOWN))
                      .arrange(DOWN, aligned_edge=LEFT, buff=0.08))
        if len(panel):
            panel.arrange(DOWN, aligned_edge=LEFT, buff=0.32)
            panel.move_to([0, self.INSET_CENTER[1], 0]).align_to([-4.25, 0, 0], LEFT)
        legend = self.legend(data, order, low, high, self.INSET_CENTER[1] - self.INSET_W / 2 - 0.75)

        self.play(FadeIn(base), run_time=0.5)
        fill_time = max(self.seconds * 0.4, 0.6)
        self.play(LaggedStart(*[FadeIn(b) for b in bands if len(b)], lag_ratio=0.3), run_time=fill_time)
        self.play(FadeIn(zoom), FadeIn(inset), FadeIn(outlines), FadeIn(panel), FadeIn(legend),
                  run_time=0.5)
        self.wait(max(self.seconds - 0.5 - fill_time - 0.5, 0.1))

    # ---------------------------------------------------------------- bản đồ châu Á
    def asia(self, data, order, shade, low, high):
        from manim import Polygon, LaggedStart
        from .geo import country_box, load_map, projector
        p, c = self.params, self.b["colors"]
        dec = p.get("decimals", 0)
        to_xy = projector(self.MAP_W, self.MAP_H, self.MAP_CENTER)

        base, fills, marks = VGroup(), [], []
        for code, country in load_map()["countries"].items():
            shapes = VGroup(*[Polygon(*[to_xy(lon, lat) for lon, lat in ring[:-1]],
                                      stroke_color=c["muted"], stroke_width=1.2,
                                      stroke_opacity=0.55, fill_opacity=0)
                              for ring in country["rings"]])
            base.add(shapes)
            if code in data:
                fills.append((data[code][1], shapes.copy().set_fill(shade[code], opacity=1)
                              .set_stroke(c["background"], width=1.2, opacity=1)))
                box = country_box(code)
                if (box[2] - box[0]) < 1.0:              # nhỏ quá không thấy: thêm chấm
                    marks.append(Dot(to_xy((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
                                     radius=0.07, color=shade[code]))
        # Hoàng Sa, Trường Sa của Việt Nam (geo.VN_ISLANDS): luôn vẽ, cùng màu với Việt Nam
        # (kênh Hàn: Dokdo + chữ 동해 — geo.islands()/sea_labels() theo góc nhìn của kênh)
        from .geo import focus_countries, islands as own_islands, sea_labels
        FOCUS = focus_countries()
        anchor, anchor_key = FOCUS[0]
        isle_color = shade.get(anchor, c["muted"])
        islands = VGroup()
        for name, spots, (lab_lon, lab_lat), align in own_islands():
            islands.add(*[Dot(to_xy(lon, lat), radius=0.028, color=isle_color) for lon, lat in spots])
            islands.add(Text(name, font=pick_font(), font_size=12,
                             color=c[anchor_key] if anchor in data else c["muted"])
                        .move_to(to_xy(lab_lon, lab_lat), aligned_edge=LEFT if align == "left" else ORIGIN))
        for name, (lon, lat) in sea_labels():
            islands.add(Text(name, font=pick_font(), font_size=12, color=c["muted"]).move_to(to_xy(lon, lat)))
        base.add(islands)
        self.play(FadeIn(base), run_time=0.5)
        fills.sort(key=lambda f: f[0])                   # tô từ thấp lên cao: mắt theo được thứ hạng
        fill_time = max(self.seconds * 0.45, 0.6)
        self.play(LaggedStart(*[FadeIn(g) for _, g in fills], *[FadeIn(m) for m in marks],
                              lag_ratio=0.25), run_time=fill_time)

        callouts = VGroup()
        for code, key in FOCUS:
            if code not in data:
                continue
            box = country_box(code)
            outline = VGroup(*[Polygon(*[to_xy(lon, lat) for lon, lat in ring[:-1]],
                                       stroke_color=c[key], stroke_width=4, fill_opacity=0)
                               for ring in load_map()["countries"][code]["rings"]])
            label, value = data[code]
            tag = VGroup(Text(label, font=pick_font(), font_size=24, color=c[key], weight="BOLD"),
                         Text(fmt_num(value, label_decimals(value, dec)), font=pick_font("number"),
                              font_size=32, color=c[key], weight="BOLD")).arrange(DOWN, buff=0.06)
            # Nhãn đặt ở vùng biển trống (geo.LABEL_AT), có đường dẫn về nước đó, và luôn nằm
            # trong khung (bản đầu: nhãn Hàn Quốc tràn mép phải, đè lên Nhật Bản)
            from .geo import LEAD_TO, label_at
            LABEL_AT = label_at()
            centre = to_xy(*LEAD_TO.get(code, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)))
            if code in LABEL_AT:
                tag.move_to(to_xy(*LABEL_AT[code]))
            else:
                tag.next_to(to_xy(box[2], (box[1] + box[3]) / 2), RIGHT, buff=0.25)
            overflow = tag.get_right()[0] - 4.3
            if overflow > 0:
                tag.shift(LEFT * overflow)
            lead = Line(tag.get_corner(UP + LEFT) if code == "KOR" else tag.get_left(), centre,
                        color=c[key], stroke_width=2, buff=0.08)
            callouts.add(outline, lead, tag)

        legend = self.legend(data, order, low, high, self.MAP_CENTER[1] - self.MAP_H / 2 - 0.55)
        self.play(FadeIn(callouts), FadeIn(legend), run_time=0.4)
        self.wait(max(self.seconds - 0.5 - fill_time - 0.4, 0.1))

    def provinces(self, data, order, shade, low, high):
        """Dự phòng khi Remotion lỗi: bản đồ 17 시도 (kênh Hàn) — tô theo thứ hạng, Dokdo cùng màu 경북 + tên, thang màu.
        Bản Remotion (web_map.province_props) đầy đủ hơn (nền Triều Tiên, tên tỉnh, bảng số)."""
        from manim import Polygon, LaggedStart
        from .geo import KR_DOKDO, KR_SEAS, load_map, projector
        c = self.b["colors"]
        to_xy = projector(self.MAP_W, self.MAP_H, self.MAP_CENTER, "kr")
        base, fills = VGroup(), []
        for code, prov in load_map("kr")["countries"].items():
            shapes = VGroup(*[Polygon(*[to_xy(lon, lat) for lon, lat in ring[:-1]], stroke_color=c["muted"],
                                      stroke_width=1.2, stroke_opacity=0.55, fill_opacity=0) for ring in prov["rings"]])
            base.add(shapes)
            if code in data:
                fills.append((data[code][1], shapes.copy().set_fill(shade[code], opacity=1)
                              .set_stroke(c["background"], width=1.2, opacity=1)))
        owner, spots, (lab_lon, lab_lat), _ = KR_DOKDO
        base.add(*[Dot(to_xy(lon, lat), radius=0.05, color=shade.get(owner, c["muted"])) for lon, lat in spots])
        base.add(Text("독도", font=pick_font(), font_size=18, color=c["text"]).move_to(to_xy(lab_lon, lab_lat)))
        for name, (lon, lat) in KR_SEAS:
            base.add(Text(name, font=pick_font(), font_size=18, color=c["muted"]).move_to(to_xy(lon, lat)))
        self.play(FadeIn(base), run_time=0.5)
        fills.sort(key=lambda f: f[0])
        fill_time = max(self.seconds * 0.45, 0.6)
        self.play(LaggedStart(*[FadeIn(g) for _, g in fills], lag_ratio=0.25), run_time=fill_time)
        legend = self.legend(data, order, low, high, self.MAP_CENTER[1] - self.MAP_H / 2 - 0.55)
        self.play(FadeIn(legend), run_time=0.4)
        self.wait(max(self.seconds - 0.5 - fill_time - 0.4, 0.1))


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
    "bar_race": BarRace,
    "map": MapScene,
}
AsiaMap = MapScene          # tên cũ
