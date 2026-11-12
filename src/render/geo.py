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
MAPS = {"asia": GEO_DIR / "asia.json", "world": GEO_DIR / "world.json"}

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


@lru_cache(maxsize=4)
def load_map(name: str = "asia") -> dict:
    return json.loads(MAPS[name].read_text(encoding="utf-8"))


def has_map(name: str) -> bool:
    return MAPS.get(name) is not None and MAPS[name].exists()


@lru_cache(maxsize=1)
def name_index() -> dict:
    """tên thường (mọi cách gọi có trong file bản đồ) -> mã nước. VI_TO_CODE thắng cuối cùng."""
    idx = {}
    for name in ("world", "asia"):
        if not has_map(name):
            continue
        for code, c in load_map(name)["countries"].items():
            for n in [c.get("name"), *c.get("aliases", [])]:
                if n:
                    idx.setdefault(str(n).strip().lower(), code)
    idx.update(VI_TO_CODE)
    return idx


def code_of(label) -> str:
    """'Việt Nam' -> 'VNM', 'Na Uy' -> 'NOR'; không biết thì None."""
    return name_index().get(str(label or "").strip().lower())


def display_name(code: str) -> str:
    """Tên tiếng Việt để hiện trên hình."""
    for name in ("world", "asia"):
        if has_map(name) and code in load_map(name)["countries"]:
            return load_map(name)["countries"][code]["name"]
    return code


def region_for(codes) -> str:
    """Bản đồ nào vẽ đủ các nước này: châu Á nếu mọi nước đều có trên bản đồ châu Á,
    ngược lại là thế giới (khi có file world.json)."""
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
