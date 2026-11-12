"""Bản đồ châu Á cho mẫu "map": đọc assets/geo/asia.json (Natural Earth, phạm vi công cộng,
cắt bằng tools/build_asia_map.py) và chiếu kinh độ/vĩ độ lên toạ độ khung hình Manim.

Phép chiếu: equirectangular có hiệu chỉnh cos(vĩ độ giữa) — ở vùng này (vĩ độ -11..48)
méo không đáng kể, mà code đơn giản, dễ hiểu.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

GEO_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "geo" / "asia.json"

# Tên tiếng Việt (như kịch bản và bảng World Bank dùng) -> mã nước trong file bản đồ
VI_TO_CODE = {
    "việt nam": "VNM", "hàn quốc": "KOR", "nhật bản": "JPN", "trung quốc": "CHN",
    "thái lan": "THA", "malaysia": "MYS", "indonesia": "IDN", "philippines": "PHL",
    "ấn độ": "IND", "singapore": "SGP", "lào": "LAO", "campuchia": "KHM", "myanmar": "MMR",
    "bangladesh": "BGD", "pakistan": "PAK", "mông cổ": "MNG", "triều tiên": "PRK",
    "đài loan": "TWN", "sri lanka": "LKA", "nepal": "NPL", "brunei": "BRN",
    "timor-leste": "TLS", "đông timor": "TLS", "bhutan": "BTN",
}


# Chỗ đặt nhãn số (kinh độ, vĩ độ) — vùng biển trống, nhãn nối về nước bằng đường dẫn.
# Cả hai nằm thành cột ở Thái Bình Dương: Biển Đông quá hẹp (nhãn chạm bờ Việt Nam hoặc
# Philippines), đặt Hàn Quốc ngay bên phải thì đè Nhật Bản và tràn mép khung.
LABEL_AT = {"VNM": (135.5, 13.5), "KOR": (138.5, 24.5)}


@lru_cache(maxsize=1)
def load_map() -> dict:
    return json.loads(GEO_PATH.read_text(encoding="utf-8"))


def code_of(label) -> str:
    """'Việt Nam' -> 'VNM'; không biết thì None."""
    return VI_TO_CODE.get(str(label or "").strip().lower())


def projector(width: float, height: float, center=(0.0, 0.0)):
    """-> hàm (kinh độ, vĩ độ) -> [x, y, 0] sao cho cả khung bản đồ vừa width x height."""
    lon0, lat0, lon1, lat1 = load_map()["bbox"]
    k = math.cos(math.radians((lat0 + lat1) / 2))
    w, h = (lon1 - lon0) * k, (lat1 - lat0)
    s = min(width / w, height / h)
    cx, cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2

    def to_xy(lon: float, lat: float) -> list:
        return [center[0] + (lon - cx) * k * s, center[1] + (lat - cy) * s, 0.0]
    return to_xy


def country_box(code: str):
    """(kinh độ nhỏ nhất, vĩ độ nhỏ nhất, lớn nhất, lớn nhất) của một nước, hoặc None."""
    c = load_map()["countries"].get(code)
    if not c:
        return None
    pts = [p for ring in c["rings"] for p in ring]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))
