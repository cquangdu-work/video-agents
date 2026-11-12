"""Cắt bản đồ châu Á từ Natural Earth (phạm vi công cộng) thành file gọn cho mẫu "map".

    # tải bản gốc (một lần): https://www.naturalearthdata.com — admin 0 countries 1:50m
    curl -L -o ne_50m.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
    python tools/build_asia_map.py ne_50m.geojson assets/geo/asia.json

Việc script làm:
1. Giữ các nước có phần đất nằm trong khung Đông Á – Đông Nam Á – Nam Á (BBOX).
2. CẮT mọi đường biên theo khung (thuật toán Sutherland–Hodgman): Nga, Úc, Kazakhstan...
   chỉ còn phần lọt vào khung, bản đồ ra hình chữ nhật gọn.
3. Giảm điểm (Ramer–Douglas–Peucker, sai số ~TOLERANCE độ), làm tròn 2 chữ số thập phân.
Kết quả ~ vài trăm KB, được commit vào repo (VM không cần tải gì).
"""
import json
import sys

BBOX = (66.0, -11.0, 146.0, 48.0)       # kinh độ trái, vĩ độ dưới, kinh độ phải, vĩ độ trên
                                         # (đủ 10 nước của "cuộc đua", bớt Nga/Trung Á trống)
TOLERANCE = 0.04                         # độ — nhỏ hơn thì nét đẹp hơn nhưng file nặng hơn
MIN_RING_POINTS = 4


def clip_ring(ring: list, bbox: tuple) -> list:
    """Cắt một vòng đa giác theo hình chữ nhật (Sutherland–Hodgman)."""
    x0, y0, x1, y1 = bbox
    edges = [(lambda p: p[0] >= x0, lambda a, b: _cross_x(a, b, x0)),
             (lambda p: p[0] <= x1, lambda a, b: _cross_x(a, b, x1)),
             (lambda p: p[1] >= y0, lambda a, b: _cross_y(a, b, y0)),
             (lambda p: p[1] <= y1, lambda a, b: _cross_y(a, b, y1))]
    out = ring
    for inside, cross in edges:
        if not out:
            break
        src, out = out, []
        prev = src[-1]
        for cur in src:
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
            prev = cur
    return out


def _cross_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return [x, a[1] + t * (b[1] - a[1])]


def _cross_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return [a[0] + t * (b[0] - a[0]), y]


def simplify(points: list, tol: float) -> list:
    """Ramer–Douglas–Peucker: bỏ những điểm lệch khỏi đường thẳng ít hơn `tol`."""
    if len(points) < 3:
        return points
    (ax, ay), (bx, by) = points[0], points[-1]
    dx, dy = bx - ax, by - ay
    norm = (dx * dx + dy * dy) ** 0.5
    far, far_d = 0, -1.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm < 1e-12:
            # Vòng khép kín: hai đầu trùng nhau, "đường thẳng" dài 0 -> đo tới điểm đầu.
            # (Không có nhánh này thì mọi điểm đều "nằm trên đường" và cả vòng bị bỏ.)
            d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
        if d > far_d:
            far, far_d = i, d
    if far_d <= tol:
        return [points[0], points[-1]]
    return simplify(points[:far + 1], tol)[:-1] + simplify(points[far:], tol)


def polygons(geometry: dict) -> list:
    """-> danh sách vòng ngoài (bỏ lỗ — ở tỷ lệ này hồ/lỗ không thấy được)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def main(src: str, dst: str):
    data = json.load(open(src, encoding="utf-8"))
    countries = {}
    for feat in data["features"]:
        props = feat["properties"]
        code = props.get("ADM0_A3") or props.get("ISO_A3")
        rings = []
        for ring in polygons(feat["geometry"]):
            clipped = clip_ring([list(p[:2]) for p in ring], BBOX)
            if len(clipped) < MIN_RING_POINTS:
                continue
            small = simplify(clipped + [clipped[0]], TOLERANCE)
            small = [[round(x, 2), round(y, 2)] for x, y in small]
            small = [p for i, p in enumerate(small) if i == 0 or p != small[i - 1]]
            if len(small) >= MIN_RING_POINTS:
                rings.append(small)
        if rings:
            countries[code] = {"name": props.get("NAME", code), "rings": rings}
    out = {"source": "Made with Natural Earth — 1:50m admin 0 countries (public domain)",
           "bbox": list(BBOX), "countries": countries}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    points = sum(len(r) for c in countries.values() for r in c["rings"])
    print(f"{len(countries)} nước, {points} điểm -> {dst}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):      # console Windows (cp949) không in được tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1], sys.argv[2])
