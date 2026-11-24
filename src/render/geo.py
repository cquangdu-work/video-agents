"""Bản đồ cho mẫu "map": đọc file ranh giới trong assets/geo/ (Natural Earth, phạm vi công cộng)
và chiếu kinh độ/vĩ độ lên toạ độ khung hình Manim.

Hai bản đồ:
- "asia"  (asia.json, tools/build_asia_map.py): Đông Á – Đông Nam Á – Nam Á, chiếu
  equirectangular có hiệu chỉnh cos(vĩ độ giữa) — ở vùng này méo không đáng kể, code đơn giản.
- "world" (world.json, tools/build_world_map.py): cả thế giới (bỏ châu Nam Cực), chiếu
  Equal Earth — phép chiếu giữ đúng diện tích, các nước ở vĩ độ cao không bị phình to.
  Ranh giới theo GÓC NHÌN CỦA VIỆT NAM (cột ADM0_A3_VN của Natural Earth): vùng Việt Nam
  không công nhận được gộp vào nước chủ quyền (Kosovo -> Serbia, Bắc Síp -> Síp...).
"""
import json
import math
from functools import lru_cache
from pathlib import Path

GEO_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "geo"
GEO_PATH = GEO_DIR / "asia.json"            # giữ tên cũ cho code/test đã dùng
MAPS = {"asia": GEO_DIR / "asia.json", "world": GEO_DIR / "world.json",
        "kr": GEO_DIR / "kr_provinces.json",     # 17 시도 của Hàn Quốc (tools/build_kr_provinces.py), kênh Hàn
        "kr_sgg": GEO_DIR / "kr_sgg.json"}       # ~229 시군구 (tools/build_kr_sgg.py, geoBoundaries 2020, CC BY 3.0)
KR_REGIONS = ("kr", "kr_sgg")                    # bản đồ trong nước Hàn Quốc (web_map.province_props)

# Mã tỉnh của KOSIS (2 chữ số; 1224 / 1236 = Gwangju / Jeonnam trong "전남광주통합특별시" mã 12 — danh mục KOSIS 24/11/2026)
# -> mã ISO 3166-2 của kr_provinces.json. Dùng cho bảng KOSIS cấp 시군구 (mã vùng 5 chữ số = tỉnh + 3 chữ số).
KOSIS_PROVINCE = {"11": "KR-11", "21": "KR-26", "22": "KR-27", "23": "KR-28", "1224": "KR-29", "25": "KR-30",
                  "26": "KR-31", "29": "KR-50", "31": "KR-41", "32": "KR-42", "33": "KR-43", "34": "KR-44", "35": "KR-45",
                  "1236": "KR-46", "37": "KR-47", "38": "KR-48", "39": "KR-49"}

# Tên tiếng Việt (như kịch bản và bảng World Bank dùng) -> mã nước. Tên ở đây thắng tên trong
# file bản đồ (Natural Earth ghi "Hoa Kỳ", "Myanma"; kịch bản nói "Mỹ", "Myanmar").
VI_TO_CODE = {
    "việt nam": "VNM", "hàn quốc": "KOR", "nhật bản": "JPN", "trung quốc": "CHN",
    "thái lan": "THA", "malaysia": "MYS", "indonesia": "IDN", "philippines": "PHL",
    "ấn độ": "IND", "singapore": "SGP", "lào": "LAO", "campuchia": "KHM", "myanmar": "MMR",
    "bangladesh": "BGD", "pakistan": "PAK", "mông cổ": "MNG", "triều tiên": "PRK",
    "đài loan": "TWN", "sri lanka": "LKA", "nepal": "NPL", "brunei": "BRN",
    "timor-leste": "TLS", "đông timor": "TLS", "bhutan": "BTN",
    "uzbekistan": "UZB", "kazakhstan": "KAZ", "kyrgyzstan": "KGZ", "tajikistan": "TJK",
    "turkmenistan": "TKM", "afghanistan": "AFG",
    "mỹ": "USA", "hoa kỳ": "USA", "anh": "GBR", "vương quốc anh": "GBR", "nga": "RUS",
    "uae": "ARE", "úc": "AUS", "đức": "DEU", "pháp": "FRA", "canada": "CAN",
}

# Tên hiển thị ưu tiên cho bản đồ thế giới (code -> tên), thay tên dài/kiểu cũ của Natural
# Earth bằng cách báo chí Việt Nam hay viết. tools/build_world_map.py ghi tên này vào world.json.
PREFERRED_NAMES = {
    "USA": "Mỹ", "GBR": "Anh", "ARE": "UAE", "PRK": "Triều Tiên", "MMR": "Myanmar",
    "TUN": "Tunisia", "ZAF": "Nam Phi", "IRL": "Ireland", "CZE": "Séc", "CYP": "Síp",
    "TLS": "Timor-Leste", "MEX": "Mexico", "BRA": "Brazil", "COD": "CHDC Congo",
    "COG": "Congo", "CAF": "Trung Phi", "BIH": "Bosnia và Herzegovina", "GIN": "Guinea",
    "GNB": "Guinea-Bissau", "SEN": "Senegal", "BEN": "Benin", "MRT": "Mauritania",
    "DZA": "Algeria", "TCD": "Chad", "VAT": "Vatican",
    # Theo cách gọi chính thức của Việt Nam (một Trung Quốc)
    "HKG": "Hồng Kông (Trung Quốc)", "MAC": "Ma Cao (Trung Quốc)", "TWN": "Đài Loan (Trung Quốc)",
}


# Chỗ đặt nhãn số trên bản đồ châu Á (kinh độ, vĩ độ) — vùng biển trống, nhãn nối về nước
# bằng đường dẫn. Cả hai nằm thành cột ở Thái Bình Dương: Biển Đông quá hẹp (nhãn chạm bờ Việt
# Nam hoặc Philippines), đặt Hàn Quốc ngay bên phải thì đè Nhật Bản và tràn mép khung.
LABEL_AT = {"VNM": (135.5, 13.5), "KOR": (138.5, 24.5)}


# Hai quần đảo của Việt Nam. Natural Earth (1:50m) KHÔNG vẽ chúng (đã kiểm: không có đa giác
# nào trong vùng), nên bản đồ phải tự vẽ — bản đồ có Việt Nam mà thiếu Hoàng Sa, Trường Sa là
# sai luật Đo đạc và Bản đồ của Việt Nam và khán giả Việt sẽ phản ứng ngay.
# Mỗi quần đảo: tên, vị trí vài cụm đảo chính (kinh độ, vĩ độ), chỗ đặt chữ, cách canh chữ.
# Biển Đông ở tỷ lệ này rất chật: chữ đặt ở khe trống đã thử (không chạm bờ Việt Nam,
# Philippines, Borneo), nhỏ, không có tiền tố "QĐ." cho đỡ dài.
VN_ISLANDS = [
    ("Hoàng Sa", [(111.6, 16.5), (112.3, 16.8), (112.0, 16.1), (112.6, 16.4), (111.3, 15.8)],
     (113.1, 16.4), "left"),
    ("Trường Sa", [(112.9, 8.7), (114.3, 10.4), (115.6, 10.1), (114.0, 9.0), (113.4, 10.0),
                   (115.0, 9.3), (116.1, 11.0)],
     (111.3, 7.7), "center"),
]
# Đường dẫn của nhãn số nối vào điểm này thay vì tâm nước: với Việt Nam, nối vào miền
# Trung–Nam để đường đi lọt giữa Hoàng Sa và Trường Sa, không cắt ngang chữ.
LEAD_TO = {"VNM": (107.2, 12.6)}

# Bản đồ thế giới quá nhỏ để đọc được tên hai quần đảo -> có ô phóng to Việt Nam + Biển Đông
# (kinh độ trái, vĩ độ dưới, kinh độ phải, vĩ độ trên), vẽ từ dữ liệu chi tiết của asia.json.
INSET_BBOX = (101.0, 6.0, 120.0, 24.0)       # đông tới 120 cho chữ "Hoàng Sa" đủ chỗ


# ------------------------------------------------ KÊNH TIẾNG HÀN: bản đồ theo GÓC NHÌN HÀN QUỐC (Du chốt 20/11/2026)
# world_ko.json (tools/build_world_map.py --view ko): ranh giới theo cột ADM0_A3_KO, tên tiếng Hàn. Dokdo (독도) quá
# nhỏ, Natural Earth 1:50m không vẽ -> tự vẽ như Hoàng Sa/Trường Sa, cùng màu Hàn Quốc, có tên; vùng biển giữa Hàn
# và Nhật ghi "동해" (cách gọi của Hàn Quốc). Kênh Hàn KHÔNG vẽ Hoàng Sa/Trường Sa (luật bản đồ của Việt Nam là
# cho kênh Việt; bản đồ kênh Hàn trung lập ở Biển Đông).
KO_ISLANDS = [("독도", [(131.87, 37.24)], (132.25, 37.24), "left")]
KO_SEAS = [("동해", (131.0, 40.2))]
KO_INSET_BBOX = (124.0, 32.5, 134.0, 43.0)       # bán đảo Hàn + 동해 (đủ chỗ cho chữ "독도")
LABEL_AT_KO = {"KOR": (138.5, 24.5), "JPN": (141.0, 14.5)}

# Bản đồ 17 시도 (24/11/2026): Dokdo thuộc 경상북도 (KR-47) -> cùng màu 경북, có tên; chữ "동해" ở vùng biển giữa
# bờ Gangwon và Ulleungdo. Toạ độ chữ đặt ở vùng biển trống (đã dựng thử).
KR_DOKDO = ("KR-47", [(131.87, 37.24)], (131.87, 36.98), "center")
KR_SEAS = [("동해", (130.3, 38.1))]
SEOUL_BBOX = (126.76, 37.41, 127.19, 37.72)      # ô phóng to Seoul trên bản đồ 시군구 (25 구 quá nhỏ ở cỡ cả nước)


def _map_path(name: str) -> Path:
    """File bản đồ theo góc nhìn của kênh: kênh Hàn dùng <tên>_ko.json nếu có (hiện chỉ có world_ko.json; bản đồ
    châu Á dựng theo ranh giới gốc của Natural Earth nên dùng chung)."""
    from .. import lang
    if lang.code() == "ko":
        ko = GEO_DIR / f"{name}_ko.json"
        if ko.exists():
            return ko
    return MAPS[name]


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_map(name: str = "asia") -> dict:
    return _load(str(_map_path(name)))


def has_map(name: str) -> bool:
    return MAPS.get(name) is not None and _map_path(name).exists()


def islands() -> list:
    """Đảo bản đồ phải tự vẽ theo góc nhìn của kênh: Hoàng Sa + Trường Sa (Việt) | Dokdo (Hàn)."""
    from .. import lang
    return KO_ISLANDS if lang.code() == "ko" else VN_ISLANDS


def sea_labels() -> list:
    """[(tên, (kinh độ, vĩ độ))] tên biển phải ghi theo góc nhìn của kênh (kênh Hàn: 동해)."""
    from .. import lang
    return KO_SEAS if lang.code() == "ko" else []


def inset_bbox() -> tuple:
    """Ô phóng to trên bản đồ thế giới: Biển Đông (kênh Việt) | bán đảo Hàn + 동해 (kênh Hàn)."""
    from .. import lang
    return KO_INSET_BBOX if lang.code() == "ko" else INSET_BBOX


def focus_countries() -> list:
    """[(mã nước, khoá màu)] hai nước được nhấn trên bản đồ: Việt + Hàn | Hàn + Nhật."""
    from .. import lang
    return [("KOR", "korea"), ("JPN", "japan")] if lang.code() == "ko" else [("VNM", "vietnam"), ("KOR", "korea")]


def label_at() -> dict:
    from .. import lang
    return LABEL_AT_KO if lang.code() == "ko" else LABEL_AT


NAMES_KO = GEO_DIR / "names_ko.json"       # tên nước tiếng Hàn (tools/build_names_ko.py, Natural Earth NAME_KO)


@lru_cache(maxsize=1)
def names_ko() -> dict:
    try:
        return json.loads(NAMES_KO.read_text(encoding="utf-8"))["names"]
    except (OSError, ValueError, KeyError):
        return {}


def country_names() -> dict:
    """{mã nước: tên} theo ngôn ngữ của kênh (src/lang.py): kênh Việt = tên trong world.json (góc nhìn Việt
    Nam), kênh Hàn = names_ko.json."""
    from .. import lang
    if lang.code() == "ko":
        return dict(names_ko())
    return {c: w["name"] for c, w in load_map("world")["countries"].items()} if has_map("world") else {}


@lru_cache(maxsize=1)
def name_index() -> dict:
    """tên thường (mọi cách gọi có trong file bản đồ, cả tên tiếng Hàn) -> mã nước. VI_TO_CODE thắng cuối cùng."""
    idx = {}
    for name in ("world", "asia", "kr", "kr_sgg"):
        if not has_map(name):
            continue
        for code, c in load_map(name)["countries"].items():
            for n in [c.get("name"), *c.get("aliases", [])]:
                if n:
                    idx.setdefault(str(n).strip().lower(), code)
    for code, n in names_ko().items():
        idx.setdefault(n.strip().lower(), code)
    idx.update(VI_TO_CODE)
    return idx


def code_of(label) -> str:
    """'Việt Nam' -> 'VNM', 'Na Uy' -> 'NOR', '한국' -> 'KOR'; không biết thì None."""
    return name_index().get(str(label or "").strip().lower())


def sgg_code(label):
    """Tên -> mã trên bản đồ 시군구, ƯU TIÊN bản đồ đó ("세종시" là tên phụ của tỉnh 세종 trong bản đồ tỉnh, nhưng trong bảng
    cấp 시군구 nó là đơn vị "SGG:세종시"). Không có -> None."""
    if not has_map("kr_sgg"):
        return None
    key = str(label or "").strip()
    units = load_map("kr_sgg")["countries"]
    if f"SGG:{key}" in units:
        return f"SGG:{key}"
    return next((c for c, u in units.items() if key in u.get("aliases", [])), None)


def display_name(code: str) -> str:
    """Tên để hiện trên hình, theo ngôn ngữ của kênh."""
    from .. import lang
    if lang.code() == "ko" and code in names_ko():
        return names_ko()[code]
    for name in ("world", "asia", "kr", "kr_sgg"):
        if has_map(name) and code in load_map(name)["countries"]:
            return load_map(name)["countries"][code]["name"]
    return code


def is_sgg(code) -> bool:
    """Mã 시군구 của bản đồ kr_sgg ("SGG:서울 중구")."""
    return str(code or "").startswith("SGG:")


def kosis_sgg_label(code: str, name: str):
    """Mục vùng KOSIS (mã, tên) -> tên vùng trên bản đồ 시군구 ("서울 중구"), hoặc None (cả nước, cấp tỉnh trừ 세종,
    đơn vị không có trên bản đồ). 세종 là một đơn vị, KOSIS ghi ở cấp tỉnh (mã 29)."""
    if code == "29":
        return "세종시"
    prov = next((KOSIS_PROVINCE[p] for p in sorted(KOSIS_PROVINCE, key=len, reverse=True)
                 if code.startswith(p) and len(code) == len(p) + 3), None)
    if not prov or not has_map("kr"):
        return None
    label = f"{load_map('kr')['countries'][prov]['name']} {name}"
    return label if sgg_code(label) else None


def is_province(code) -> bool:
    """Mã 시도 của Hàn Quốc (ISO 3166-2, "KR-11")."""
    return str(code or "").startswith("KR-")


def region_for(codes) -> str:
    """Bản đồ nào vẽ đủ các nước này: 17 시도 nếu mọi mã là tỉnh/thành Hàn Quốc; châu Á nếu mọi nước đều có trên
    bản đồ châu Á, ngược lại là thế giới (khi có file world.json)."""
    codes = list(codes)
    if codes and all(is_province(c) for c in codes) and has_map("kr"):
        return "kr"
    if codes and all(is_sgg(c) for c in codes) and has_map("kr_sgg"):
        return "kr_sgg"
    asia = load_map("asia")["countries"]
    if all(c in asia for c in codes) or not has_map("world"):
        return "asia"
    return "world"


# ---- phép chiếu ----
_EE = (1.340264, -0.081106, 0.000893, 0.003796)
_M = math.sqrt(3) / 2


def equal_earth(lon: float, lat: float) -> tuple:
    """Phép chiếu Equal Earth (Šavrič, Patterson, Jenny 2018) -> (x, y) không thứ nguyên."""
    a1, a2, a3, a4 = _EE
    th = math.asin(_M * math.sin(math.radians(lat)))
    t2 = th * th
    t6 = t2 * t2 * t2
    x = math.radians(lon) * math.cos(th) / (_M * (a1 + 3 * a2 * t2 + t6 * (7 * a3 + 9 * a4 * t2)))
    y = th * (a1 + a2 * t2 + t6 * (a3 + a4 * t2))
    return x, y


def projector(width: float, height: float, center=(0.0, 0.0), name: str = "asia", bbox=None):
    """-> hàm (kinh độ, vĩ độ) -> [x, y, 0] sao cho cả khung bản đồ (hoặc `bbox`) vừa
    width x height, tâm ở `center`."""
    m = load_map(name)
    lon0, lat0, lon1, lat1 = bbox or m["bbox"]
    if m.get("projection") == "equal_earth" and bbox is None:
        xs = [equal_earth(lon0, 0)[0], equal_earth(lon1, 0)[0]]      # rộng nhất ở xích đạo
        ys = [equal_earth(0, lat0)[1], equal_earth(0, lat1)[1]]
        s = min(width / (xs[1] - xs[0]), height / (ys[1] - ys[0]))
        cx, cy = (xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2

        def to_xy(lon: float, lat: float) -> list:
            x, y = equal_earth(lon, lat)
            return [center[0] + (x - cx) * s, center[1] + (y - cy) * s, 0.0]
        return to_xy
    k = math.cos(math.radians((lat0 + lat1) / 2))
    w, h = (lon1 - lon0) * k, (lat1 - lat0)
    s = min(width / w, height / h)
    cx, cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2

    def to_xy(lon: float, lat: float) -> list:
        return [center[0] + (lon - cx) * k * s, center[1] + (lat - cy) * s, 0.0]
    return to_xy


def projected_size(width: float, height: float, name: str) -> tuple:
    """Kích thước thật (rộng, cao) của bản đồ sau khi vừa khung width x height."""
    to_xy = projector(width, height, (0.0, 0.0), name)
    lon0, lat0, lon1, lat1 = load_map(name)["bbox"]
    if load_map(name).get("projection") == "equal_earth":
        return (to_xy(lon1, 0)[0] - to_xy(lon0, 0)[0], to_xy(0, lat1)[1] - to_xy(0, lat0)[1])
    return (to_xy(lon1, lat0)[0] - to_xy(lon0, lat0)[0], to_xy(lon0, lat1)[1] - to_xy(lon0, lat0)[1])


def country_box(code: str, name: str = "asia"):
    """(kinh độ nhỏ nhất, vĩ độ nhỏ nhất, lớn nhất, lớn nhất) của một nước, hoặc None."""
    c = load_map(name)["countries"].get(code)
    if not c:
        return None
    pts = [p for ring in c["rings"] for p in ring]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def clip_ring(ring: list, bbox: tuple) -> list:
    """Cắt một vòng đa giác theo hình chữ nhật (Sutherland–Hodgman). Dùng cho công cụ dựng
    bản đồ và cho ô phóng to (đa giác không được tràn ra ngoài khung ô)."""
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
