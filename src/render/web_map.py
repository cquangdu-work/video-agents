"""Bản đồ và cuộc đua số liệu cho engine Remotion — phần ĐỊA LÝ và SỐ LIỆU tính ở đây.

Python làm hết những gì có luật: phép chiếu (src/render/geo.py), Hoàng Sa + Trường Sa
(geo.VN_ISLANDS, luôn vẽ, cùng màu Việt Nam, có tên), ô phóng to Biển Đông trên bản đồ thế giới
(geo.INSET_BBOX), tên nước theo cách gọi của Việt Nam, thứ hạng (cùng hàm với lời đọc).
Kết quả là đường vẽ SVG theo điểm ảnh khung 1080x1920 — Remotion (render-web/src/scenes/
MapRace.tsx) chỉ tô màu và cho chuyển động, không tự quyết định gì về bản đồ.
"""
from .. import lang
from .base import fmt_num
from .templates import country_color_key, label_decimals

# Khung Manim 9 x 16 đơn vị <-> 1080 x 1920 điểm ảnh
U = 120.0


def _px(pt) -> tuple:
    return round((pt[0] + 4.5) * U, 1), round((8.0 - pt[1]) * U, 1)


def _units(cx_px: float, cy_px: float) -> tuple:
    return (cx_px - 540) / U, (960 - cy_px) / U


def _path(rings, to_xy, close=True) -> str:
    out = []
    for ring in rings:
        if len(ring) < 3:
            continue
        pts = [_px(to_xy(lon, lat)) for lon, lat in ring]
        out.append("M" + " L".join(f"{x},{y}" for x, y in pts) + (" Z" if close else ""))
    return " ".join(out)


def _mix(a: str, b: str, k: float) -> str:
    """Pha màu hex a -> b theo tỷ lệ k (giống interpolate_color của Manim)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02X}" for x, y in zip(ca, cb))


def _label_width(text: str, size: float) -> float:
    return len(text) * size * 0.56              # ước lượng bề ngang chữ đậm (để không tràn mép)


# ------------------------------------------------------------------------- bản đồ
ASIA_BOX = dict(cx=540, cy=790, w=1000, h=780)          # bản đồ châu Á: y 400..1180
WORLD_BOX = dict(cx=540, cy=720, w=1040, h=540)         # bản đồ thế giới: y ~466..974
INSET = dict(cx=872, cy=1170, size=320)                 # ô phóng to Biển Đông (thế giới)


def map_props(p: dict, colors: dict) -> dict:
    from ..sources.datatable import ranks_desc
    from .geo import (LEAD_TO, clip_ring, code_of, country_box, display_name, focus_countries, inset_bbox,
                      islands, label_at, load_map, projector, sea_labels)
    ISLANDS, INSET_BBOX, LABEL_AT = islands(), inset_bbox(), label_at()     # theo góc nhìn của kênh
    FOCUS = focus_countries()                    # [(mã, khoá màu)]: Việt+Hàn (kênh Việt) | Hàn+Nhật (kênh Hàn)
    anchor, anchor_key = FOCUS[0]
    dec = int(p.get("decimals", 0) or 0)
    region = "world" if p.get("region") == "world" else "asia"
    data, given = {}, {}
    for it in p.get("items") or []:
        code = it.get("code") or code_of(it.get("label"))
        if code:
            data[code] = (str(it.get("label")), float(it["value"]))
            if isinstance(it.get("rank"), int):
                given[code] = it["rank"]
    rank = {**ranks_desc({k: v[1] for k, v in data.items()}), **given}
    order = sorted(data, key=lambda k: data[k][1])           # thấp -> cao
    n = len(order)
    low, high = colors["surface"], colors["accent"]
    shade = {k: _mix(low, high, 0.15 + 0.85 * r / max(n - 1, 1)) for r, k in enumerate(order)}
    vn_color = shade.get(anchor, colors["muted"])         # màu đảo tự vẽ = màu nước "ta"
    fmt = lambda v: fmt_num(v, label_decimals(v, dec))

    box = WORLD_BOX if region == "world" else ASIA_BOX
    cx, cy = _units(box["cx"], box["cy"])
    to_xy = projector(box["w"] / U, box["h"] / U, (cx, cy), region)
    countries = load_map(region)["countries"]
    small = 1.5 if region == "world" else 1.0

    fills, outline = [], []
    for code, c in countries.items():
        d = _path(c["rings"], to_xy)
        outline.append(d)
        if code not in data:
            continue
        xs = [q[0] for ring in c["rings"] for q in ring]
        ys = [q[1] for ring in c["rings"] for q in ring]
        f = {"code": code, "d": d, "color": shade[code], "k": order.index(code) / max(n - 1, 1)}
        if max(xs) - min(xs) < small and max(ys) - min(ys) < small:   # nhỏ quá không thấy: thêm chấm
            f["dot"] = list(_px(to_xy((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))) + [
                5 if region == "world" else 8]
        fills.append(f)
    fills.sort(key=lambda f: f["k"])

    # Hoàng Sa, Trường Sa (kênh Việt) / Dokdo (kênh Hàn): LUÔN vẽ (Natural Earth không có), cùng màu nước "ta"
    island_pts = [list(_px(to_xy(lon, lat))) for _, spots, _, _ in ISLANDS for lon, lat in spots]
    island_labels = []
    if region == "asia":
        # cỡ 19: bản đồ châu Á ~12,5 điểm ảnh/độ kinh -> "Hoàng Sa" dài ~85 điểm ảnh, dừng ở ~119,9°E
        # sát bờ Luzon; cỡ 23 thì chữ đè lên Philippines (đo 16/11/2026)
        for name, _, (lab_lon, lab_lat), align in ISLANDS:
            x, y = _px(to_xy(lab_lon, lab_lat))
            island_labels.append({"text": name, "x": x, "y": y, "anchor": "start" if align == "left" else "middle",
                                  "size": 19, "color": colors[anchor_key] if anchor in data else colors["muted"]})
        for name, (lon, lat) in sea_labels():                  # tên biển theo góc nhìn của kênh (동해)
            x, y = _px(to_xy(lon, lat))
            island_labels.append({"text": name, "x": x, "y": y, "anchor": "middle", "size": 19,
                                  "color": colors["muted"]})

    marks = []
    for code, key in FOCUS:
        if code in data:
            marks.append({"d": _path(countries[code]["rings"], to_xy), "color": colors[key]})

    out = {"region": region, "title": str(p.get("title", "")), "outline": " ".join(outline), "fills": fills,
           "islands": island_pts, "islandColor": vn_color, "islandLabels": island_labels, "marks": marks}

    # thang màu thấp -> cao
    if order:
        caption = " · ".join(x for x in (str(p.get("year") or ""), str(p.get("unit") or "")) if x)
        out["legend"] = {"stops": [_mix(low, high, 0.15 + 0.85 * i / 9) for i in range(10)],
                         "lo": fmt(data[order[0]][1]), "hi": fmt(data[order[-1]][1]), "caption": caption,
                         "y": 1000 if region == "world" else 1205}

    if region == "asia":
        callouts = []
        for code, key in FOCUS:
            if code not in data:
                continue
            b = country_box(code)
            lead = LEAD_TO.get(code, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
            tag = LABEL_AT.get(code, (b[2] + 3, (b[1] + b[3]) / 2))
            tx, ty = _px(to_xy(*tag))
            callouts.append({"label": data[code][0], "value": fmt(data[code][1]), "color": colors[key],
                             "x": min(tx, 1040 - 110), "y": ty, "to": list(_px(to_xy(*lead)))})
        out["callouts"] = callouts
        return out

    # ---- thế giới: ô phóng to Biển Đông (vẽ từ bản đồ châu Á, chi tiết hơn) + khung số
    lon0, lat0, lon1, lat1 = INSET_BBOX
    icx, icy = _units(INSET["cx"], INSET["cy"])
    to_in = projector(INSET["size"] / U, INSET["size"] / U, (icx, icy), "asia", bbox=INSET_BBOX)
    frame = [_px(to_in(lon0, lat1)), _px(to_in(lon1, lat0))]          # góc trên-trái, dưới-phải
    inset_shapes = []
    for code, c in load_map("asia")["countries"].items():
        rings = [r for r in (clip_ring(ring, INSET_BBOX) for ring in c["rings"]) if len(r) >= 3]
        if not rings:
            continue
        filled = code in data
        inset_shapes.append({
            "d": _path(rings, to_in), "fill": shade.get(code), "vn": code == anchor,
            "stroke": colors[anchor_key] if code == anchor else colors["background"] if filled else colors["muted"]})
    inset_islands = [list(_px(to_in(lon, lat))) for _, spots, _, _ in ISLANDS for lon, lat in spots]
    inset_labels = []
    for name, (lon, lat) in sea_labels():
        x, y = _px(to_in(lon, lat))
        inset_labels.append({"text": name, "x": x, "y": y, "anchor": "middle", "size": 20, "color": colors["muted"]})
    for name, _, (lab_lon, lab_lat), align in ISLANDS:
        x, y = _px(to_in(lab_lon, lab_lat))
        size = 20
        text_anchor = "start" if align == "left" else "middle"
        right = x + (_label_width(name, size) if text_anchor == "start" else _label_width(name, size) / 2)
        x -= max(0.0, right - (frame[1][0] - 8))                   # chữ không chạm mép ô
        inset_labels.append({"text": name, "x": round(x, 1), "y": y, "anchor": text_anchor, "size": size,
                             "color": colors[anchor_key]})
    mark = [_px(to_xy(lon0, lat1)), _px(to_xy(lon1, lat0))]
    total = int(p.get("total") or n)
    rows = []
    for code, key in FOCUS:
        if code in data:
            rows.append((data[code][0], data[code][1], colors[key], rank[code]))
    if order and order[-1] not in [c for c, _ in FOCUS]:
        top = order[-1]
        rows.append((lang.pick(vi="Cao nhất: ", ko="1위: ") + display_name(top), data[top][1], colors["accent"],
                     rank[top]))
    panel, ranks_shown = [], []
    for label, value, color, r in rows:
        # nửa dưới bảng nói "thấp thứ 2/214" (khớp tóm tắt), không "cao thứ 213/214"
        from_bottom = 1 + sum(1 for _, v in data.values() if v < value)
        pos = (lang.pick(vi=f"cao thứ {r}/{total}", ko=f"{total}곳 중 {r}위") if r <= total / 2
               else lang.pick(vi=f"thấp thứ {from_bottom}/{total}", ko=f"하위 {from_bottom}위/{total}"))
        ranks_shown += [r, from_bottom, total]
        panel.append({"label": label, "value": fmt(value), "color": color, "pos": pos})
    out.update(inset={"frame": frame, "shapes": inset_shapes, "islands": inset_islands, "labels": inset_labels,
                      "mark": mark, "background": colors["background"]},
               panel=panel, ranksShown=ranks_shown)
    return out


# ------------------------------------------------------------------------- cuộc đua
def race_props(p: dict, colors: dict, flag_of) -> dict:
    """Số trên thanh luôn là số THẬT của năm đang hiện (đổi ngay đầu chặng như bản Manim),
    chỉ độ dài và vị trí thanh là trượt mượt giữa hai mốc."""
    dec = int(p.get("decimals", 0) or 0)
    items = []
    for it in p.get("items") or []:
        key = it.get("color") or country_color_key(it.get("label"))
        vals = [float(v) for v in it["values"]]
        items.append({"label": str(it["label"]), "values": vals,
                      "shown": [fmt_num(v, label_decimals(v, dec)) for v in vals],
                      "fill": colors.get(key, colors["accent"]) if key else colors["muted"],
                      "ink": colors.get(key, colors["accent"]) if key else colors["text"],
                      "strong": bool(key), "flag": flag_of(it.get("label"))})
    return {"title": str(p.get("title", "")), "years": [int(y) for y in p.get("years") or []],
            "items": items, "unit": str(p.get("unit") or ""), "overtakes": overtakes(items)}


def overtakes(items: list) -> list:
    """Chặng nào nước "ta" (Việt Nam | Hàn Quốc, không có thì thanh được nhấn đầu tiên) VƯỢT nước khác -> nhãn
    "↑ vượt …" đúng chặng đó (24/11/2026, Du: "chuyển động phải giúp hiểu số liệu"). Tính bằng thứ hạng thật giữa
    hai mốc năm liền nhau. -> [{"leg": k, "item": chỉ số thanh, "passed": [tên…]}]."""
    anchor_name = lang.pick(vi="việt nam", ko="한국")
    strong = [i for i, it in enumerate(items) if it["strong"]]
    a = next((i for i in strong if items[i]["label"].strip().lower() == anchor_name), strong[0] if strong else None)
    if a is None or not items:
        return []
    n = min(len(it["values"]) for it in items)

    def rank(j: int) -> dict:
        order = sorted(range(len(items)), key=lambda i: -items[i]["values"][j])
        return {i: r for r, i in enumerate(order)}
    out = []
    for k in range(n - 1):
        r0, r1 = rank(k), rank(k + 1)
        passed = [items[i]["label"] for i in range(len(items))
                  if i != a and r0[i] < r0[a] and r1[i] > r1[a]]
        if passed:
            out.append({"leg": k, "item": a, "passed": passed[:2]})
    return out
