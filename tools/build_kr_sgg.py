"""Bản đồ Hàn Quốc theo ~229 시군구 (quận/huyện/thành phố tự trị) cho kênh tiếng Hàn — 24/11/2026.

    # ranh giới: geoBoundaries gbOpen KOR ADM2 (năm 2020, CC BY 3.0 — PHẢI ghi công "geoBoundaries")
    curl -L -o kor_adm2.geojson https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/KOR/ADM2/geoBoundaries-KOR-ADM2.geojson
    python tools/build_kr_sgg.py kor_adm2.geojson assets/geo/kr_sgg.json        # cần KOSIS_API_KEY trong .env

geoBoundaries chỉ có tên La-tinh ("Buk-gu", "Goseong-gun" — trùng giữa nhiều thành phố), không có tỉnh cha. Cách ghép:
1. Tỉnh của mỗi vùng = tỉnh NHỎ NHẤT (assets/geo/kr_provinces.json) chứa một điểm nằm trong vùng — hình tỉnh chỉ giữ viền
   ngoài nên Gyeonggi "bao" luôn Seoul, Gyeongbuk bao Daegu.
2. Tên tiếng Hàn lấy từ danh mục vùng của KOSIS (bảng 101/DT_1YL20631 — mã 5 chữ số, 2 số đầu là tỉnh; Gwangju/Jeonnam
   mang mã mới 1224/1236 sau sáp nhập), bỏ đơn vị đã giải thể (tên có tiền tố tỉnh "충북 청주시"), đơn vị không tự trị
   (구 của 수원시...) và đơn vị lập SAU 2020 (ranh giới 2020 chưa có).
3. Trong cùng tỉnh, so tên KOSIS phiên âm La-tinh (Revised Romanization giản lược, bỏ đuôi 시/군/구) với tên geoBoundaries,
   ghép tham lam theo độ giống. Lượt 2: vùng sát ranh giới tỉnh (điểm rơi sang tỉnh bên cạnh) ghép theo TÊN giữa mọi
   tỉnh; tên giống hệt (Gangseo-gu ở cả Seoul lẫn Busan) thì chọn tỉnh gần nhất.
Đã biết: geoBoundaries 2020 THIẾU 영광군 (228 vùng) -> trên bản đồ là vùng không có số (nền tỉnh).
Mã vùng: "SGG:<tỉnh ngắn> <tên>" (vd "SGG:서울 중구") — tên hiển thị cũng là chuỗi đó, không trùng giữa các thành phố.
"""
import difflib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_asia_map import polygons, simplify  # noqa: E402

TOLERANCE = 0.004
MIN_EXTENT = 0.03
MIN_SCORE = 0.7                 # trong tỉnh (0,56 đã ghép nhầm 영광군 với Gwangsan-gu)
MIN_SCORE_CROSS = 0.85          # lượt 2, giữa các tỉnh
# mã tỉnh của KOSIS (2 chữ số; 1224/1236 = Gwangju/Jeonnam trong 전남광주통합특별시) -> mã ISO của kr_provinces.json
KOSIS_PROV = {"11": "KR-11", "21": "KR-26", "22": "KR-27", "23": "KR-28", "1224": "KR-29", "25": "KR-30", "26": "KR-31",
              "29": "KR-50", "31": "KR-41", "32": "KR-42", "33": "KR-43", "34": "KR-44", "35": "KR-45", "1236": "KR-46",
              "37": "KR-47", "38": "KR-48", "39": "KR-49"}
AFTER_2020 = {"제물포구", "영종구", "서해구", "검단구"}         # Incheon 2026 — ranh giới 2020 chưa có

INITIAL = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
VOWEL = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu",
         "ui", "i"]
FINAL = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng",
         "t", "t", "k", "t", "p", "t"]


def romanize(text: str) -> str:
    """Revised Romanization giản lược (không đồng hoá âm) — chỉ để SO tên, không để hiển thị."""
    out = []
    for ch in text:
        k = ord(ch) - 0xAC00
        out.append(INITIAL[k // 588] + VOWEL[(k % 588) // 28] + FINAL[k % 28] if 0 <= k < 11172 else ch)
    return "".join(out)


def base_ko(name: str) -> str:
    return name[:-1] if name[-1:] in "시군구" and len(name) > 2 else name


def base_en(name: str) -> str:
    n = name.split("[")[0].lower().replace("-", "").replace(" ", "")     # "Buk-gu [North Distrikt]" -> "bukgu"
    for suf in ("si", "gun", "gu"):
        if n.endswith(suf) and len(n) > len(suf) + 2:
            return n[: -len(suf)]
    return n


def similar(ko: str, en: str) -> float:
    """Độ giống tên: so cả phần gốc (bỏ đuôi) lẫn tên đủ ("동구" ~ "Dong-gu": gốc 2 âm tiết thì không bỏ đuôi)."""
    full = en.split("[")[0].lower().replace("-", "").replace(" ", "")
    return max(difflib.SequenceMatcher(None, romanize(base_ko(ko)), base_en(en)).ratio(),
               difflib.SequenceMatcher(None, romanize(ko), full).ratio())


def area(ring) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def point_in(pt, ring) -> bool:
    x, y, inside = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def inner_point(rings) -> tuple:
    """Một điểm NẰM TRONG vùng (đa giác lớn nhất): trung điểm của đoạn cắt ngang dài nhất qua giữa."""
    ring = max(rings, key=area)
    ys = sorted(p[1] for p in ring)
    y = (ys[0] + ys[-1]) / 2
    xs = sorted(x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]) if (y1 > y) != (y2 > y))
    if len(xs) >= 2:
        a, b = max(zip(xs[::2], xs[1::2]), key=lambda ab: ab[1] - ab[0])
        return ((a + b) / 2, y)
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def kosis_units() -> dict:
    """{mã ISO tỉnh: [tên Hàn]} các đơn vị tự trị trong danh mục KOSIS."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from src.sources import kosis
    out = {}
    for code, name in kosis.table_meta("101", "DT_1YL20631")["SGG"]:
        prov = next((KOSIS_PROV[p] for p in sorted(KOSIS_PROV, key=len, reverse=True)
                     if code.startswith(p) and len(code) == len(p) + 3), None)
        if not prov or not code.endswith("0") or " " in name or name in AFTER_2020:
            continue
        if prov == "KR-28" and name == "남구":            # Incheon 남구 -> 미추홀구 (2018), cùng một hình
            continue
        if prov == "KR-47" and name == "군위군":          # 군위군 chuyển 경북 -> 대구 (2023): giữ tên hiện tại 대구 군위군
            continue
        if name not in out.setdefault(prov, []):
            out[prov].append(name)
    out.setdefault("KR-50", ["세종시"])                 # 세종: một đơn vị, KOSIS ghi ở cấp tỉnh
    return out


def make_unit(short: dict, prov: str, ko: str, en: str, rings: list) -> tuple:
    label = "세종시" if prov == "KR-50" else f"{short[prov]} {ko}"     # "세종" = mã tỉnh KR-50
    kept = []
    for r in sorted(rings, key=area, reverse=True):
        xs, ys = [p[0] for p in r], [p[1] for p in r]
        if kept and max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_EXTENT:
            continue                                     # đảo nhỏ (giữ ít nhất hình lớn nhất)
        s = simplify(r + [r[0]], TOLERANCE)
        s = [[round(x, 3), round(y, 3)] for x, y in s]
        s = [p for j, p in enumerate(s) if j == 0 or p != s[j - 1]]
        if len(s) >= 4:
            kept.append(s)
    return f"SGG:{label}", {"name": label, "province": prov, "ko": ko, "en": en,
                            "aliases": sorted({f"{short[prov]}{ko}", f"{short[prov]} {base_ko(ko)}"}), "rings": kept}


def main(src: str, dst: str):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(__file__).resolve().parent.parent
    provinces = json.loads((root / "assets/geo/kr_provinces.json").read_text(encoding="utf-8"))["countries"]
    short = {c: p["name"] for c, p in provinces.items()}
    geo = []                                                     # [(tỉnh, tên en, rings)]
    for f in json.load(open(src, encoding="utf-8"))["features"]:
        rings = [[list(p[:2]) for p in r] for r in polygons(f["geometry"])]
        if not rings:
            continue
        pt = inner_point(rings)
        inside = [(area(r), c) for c, p in provinces.items() for r in p["rings"] if point_in(pt, r)]
        prov = min(inside)[1] if inside else min(provinces, key=lambda c: min(
            (pt[0] - q[0]) ** 2 + (pt[1] - q[1]) ** 2 for r in provinces[c]["rings"] for q in r))
        geo.append((prov, f["properties"]["shapeName"], rings))
    units = kosis_units()
    out, report, used_g, used_k = {}, [], set(), set()

    def take(prov, ko, g, score, note=""):
        key, unit = make_unit(short, prov, ko, geo[g][1], geo[g][2])
        out[key] = unit
        used_g.add(g); used_k.add((prov, ko))
        report.append(f"{prov} {ko:8s} <- {geo[g][1]:28s} {score:.2f}{note}")

    # lượt 1: trong cùng tỉnh
    pairs = [(similar(ko, geo[g][1]), prov, ko, g) for prov, names in units.items() for ko in names
             for g in range(len(geo)) if geo[g][0] == prov]
    for score, prov, ko, g in sorted(pairs, reverse=True):
        if score >= MIN_SCORE and g not in used_g and (prov, ko) not in used_k:
            take(prov, ko, g, score)
    # lượt 2: giữa các tỉnh, tên phải rất giống; trùng tên thì tỉnh gần nhất
    pairs = []
    for g, (gp, en, rings) in enumerate(geo):
        if g in used_g:
            continue
        pt = inner_point(rings)
        for prov, names in units.items():
            for ko in names:
                if (prov, ko) in used_k:
                    continue
                score = similar(ko, en)
                if score >= MIN_SCORE_CROSS:
                    dist = min((pt[0] - q[0]) ** 2 + (pt[1] - q[1]) ** 2 for r in provinces[prov]["rings"] for q in r)
                    pairs.append((-score, dist, prov, ko, g))
    for neg, dist, prov, ko, g in sorted(pairs):
        if g not in used_g and (prov, ko) not in used_k:
            take(prov, ko, g, -neg, f"  (lượt 2, hình nằm ở {geo[g][0]})")
    report += [f"!! {p} KOSIS không có hình: {k}" for p, names in units.items() for k in names if (p, k) not in used_k]
    report += [f"!! {geo[g][0]} geoBoundaries thừa: {geo[g][1]}" for g in range(len(geo)) if g not in used_g]
    print("\n".join(report))
    data = {"source": "geoBoundaries (gbOpen KOR ADM2, 2020) — CC BY 3.0, www.geoboundaries.org",
            "bbox": [124.5, 33.0, 132.2, 38.75], "countries": out}
    Path(dst).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pts = sum(len(r) for u in out.values() for r in u["rings"])
    print(f"{len(out)} vùng, {pts} điểm -> {dst} ({os.path.getsize(dst) // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
