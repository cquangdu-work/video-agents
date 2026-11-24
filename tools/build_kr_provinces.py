"""Bản đồ Hàn Quốc theo 17 tỉnh/thành (시도) cho kênh tiếng Hàn — từ Natural Earth 1:10m admin 1 (phạm vi công cộng).

    # tải bản gốc (một lần, ~40 MB):
    curl -L -o admin1_10m.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
    python tools/build_kr_provinces.py admin1_10m.geojson assets/geo/kr_provinces.json

Việc script làm:
1. Giữ 17 시도 của Hàn Quốc (mã ISO 3166-2 KR-11 … KR-50), đặt tên ngắn kiểu báo chí Hàn ("서울", "전남") và mọi cách
   gọi KOSIS dùng (tên đầy đủ cũ và mới: 강원도 / 강원특별자치도, 전라북도 / 전북특별자치도...) làm `aliases`.
2. Phần Triều Tiên lọt vào khung chỉ để làm nền (bán đảo không bị cắt cụt), không tô số: lưu ở `context`.
   Không vẽ Nhật Bản: khung bị cắt thẳng làm Kyushu thành một khối vuông lạ mắt (dựng thử 24/11).
3. Bỏ đảo nhỏ hơn MIN_EXTENT độ (Jeonnam có hàng nghìn đảo — ở cỡ khung dọc không thấy được), giảm điểm
   (Ramer–Douglas–Peucker, TOLERANCE độ), làm tròn 3 chữ số thập phân.
Dokdo (독도) không có trong Natural Earth -> src/render/geo.py tự vẽ (cùng màu 경북, có tên), như bản đồ thế giới.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_asia_map import clip_ring, polygons, simplify  # noqa: E402

BBOX = (124.5, 33.0, 132.2, 38.75)       # kinh độ trái, vĩ độ dưới, phải, trên — đủ Baengnyeongdo, Jeju, Ulleungdo, Dokdo
TOLERANCE = 0.006
MIN_EXTENT = 0.06
MIN_EXTENT_CONTEXT = 0.15

# mã ISO -> (tên ngắn, [cách gọi khác]) — tên ngắn là cách báo chí/KOSIS bản rút gọn hay viết
PROVINCES = {
    "KR-11": ("서울", ["서울특별시", "서울시"]),
    "KR-26": ("부산", ["부산광역시", "부산시"]),
    "KR-27": ("대구", ["대구광역시", "대구시"]),
    "KR-28": ("인천", ["인천광역시", "인천시"]),
    "KR-29": ("광주", ["광주광역시", "광주시"]),
    "KR-30": ("대전", ["대전광역시", "대전시"]),
    "KR-31": ("울산", ["울산광역시", "울산시"]),
    "KR-50": ("세종", ["세종특별자치시", "세종시"]),
    "KR-41": ("경기", ["경기도"]),
    "KR-42": ("강원", ["강원도", "강원특별자치도"]),
    "KR-43": ("충북", ["충청북도"]),
    "KR-44": ("충남", ["충청남도"]),
    "KR-45": ("전북", ["전라북도", "전북특별자치도"]),
    "KR-46": ("전남", ["전라남도"]),
    "KR-47": ("경북", ["경상북도"]),
    "KR-48": ("경남", ["경상남도"]),
    "KR-49": ("제주", ["제주도", "제주특별자치도"]),
}
CONTEXT = ("PRK",)


def _extent(ring) -> float:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _rings(geometry: dict, min_extent: float) -> list:
    out = []
    for ring in polygons(geometry):
        clipped = clip_ring([list(p[:2]) for p in ring], BBOX)
        if len(clipped) < 4 or _extent(clipped) < min_extent:
            continue
        small = simplify(clipped + [clipped[0]], TOLERANCE)
        small = [[round(x, 3), round(y, 3)] for x, y in small]
        small = [p for i, p in enumerate(small) if i == 0 or p != small[i - 1]]
        if len(small) >= 4:
            out.append(small)
    return out


def main(src: str, dst: str):
    data = json.load(open(src, encoding="utf-8"))
    provinces, context = {}, []
    for feat in data["features"]:
        p = feat["properties"]
        if p.get("adm0_a3") == "KOR" and p.get("iso_3166_2") in PROVINCES:
            code = p["iso_3166_2"]
            name, aliases = PROVINCES[code]
            rings = _rings(feat["geometry"], MIN_EXTENT)
            if not rings:      # tỉnh nào cũng phải có hình — Seoul, Sejong nhỏ nhưng vẫn > MIN_EXTENT
                raise SystemExit(f"{code} không còn hình nào sau khi lọc")
            provinces[code] = {"name": name, "aliases": aliases, "name_en": p.get("name"), "rings": rings}
        elif p.get("adm0_a3") in CONTEXT:
            context += _rings(feat["geometry"], MIN_EXTENT_CONTEXT)
    missing = set(PROVINCES) - set(provinces)
    if missing:
        raise SystemExit(f"thiếu {sorted(missing)}")
    out = {"source": "Made with Natural Earth — 1:10m admin 1 states/provinces (public domain)",
           "bbox": list(BBOX), "countries": provinces, "context": context}
    Path(dst).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    points = sum(len(r) for c in provinces.values() for r in c["rings"]) + sum(len(r) for r in context)
    print(f"{len(provinces)} 시도, {len(context)} vòng nền, {points} điểm -> {dst}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1], sys.argv[2])
