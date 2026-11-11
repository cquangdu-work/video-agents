"""Kho chất liệu (giai đoạn 2) — nằm chung file SQLite với kho ý tưởng.

Mỗi chất liệu (template đồ họa, nhạc, minh họa...) có: thẻ, giấy phép, nhật ký
sử dụng. Luật chống lặp theo CLAUDE.md: một chất liệu không được dùng quá
max_uses_per_week lần/tuần.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import connect  # dùng chung connection/schema với kho ý tưởng

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,          -- template | music | illustration | font
    name       TEXT UNIQUE NOT NULL,
    tags       TEXT,                   -- phân cách bằng dấu phẩy
    license    TEXT NOT NULL,          -- bắt buộc rõ giấy phép (luật chính sách)
    note       TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS asset_uses (
    id         INTEGER PRIMARY KEY,
    asset_name TEXT NOT NULL,
    video_ref  TEXT,                   -- id video / tên file dùng chất liệu này
    used_at    TEXT
);
"""

# Template code của chính dự án -> giấy phép tự có. Nhạc/hình ngoài PHẢI ghi nguồn.
BUILTIN_TEMPLATES = [
    ("template", "intro",      "nhận diện,intro",            "own-code", "Intro 1 giây mở đầu mọi video"),
    ("template", "big_number", "số lớn,đếm,ấn tượng",        "own-code", "Một con số khổng lồ đếm từ 0"),
    ("template", "bar_chart",  "so sánh,xếp hạng,biểu đồ",   "own-code", "Thanh ngang mọc dần theo giá trị"),
    ("template", "versus",     "việt-hàn,đối đầu,so sánh",   "own-code", "Hai cột số đối đầu (VN đỏ - KR xanh)"),
    ("template", "line_chart", "xu hướng,thời gian,biểu đồ", "own-code", "Đường xu hướng tự vẽ dần"),
    ("template", "statement",  "câu dẫn,chuyển tiếp,chữ",    "own-code", "Câu chữ lớn cho cảnh không có số liệu (3 kiểu bố cục xoay vòng)"),
    ("template", "percent",    "tỷ lệ,phần trăm,vòng tròn",  "own-code", "Vòng tròn tô dần tới X%"),
]


def init_assets(con: sqlite3.Connection = None):
    con = con or connect()
    con.executescript(_SCHEMA)
    for kind, name, tags, lic, note in BUILTIN_TEMPLATES:
        con.execute(
            "INSERT OR IGNORE INTO assets (kind, name, tags, license, note, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (kind, name, tags, lic, note, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    con.commit()
    return con


def record_use(con, asset_name: str, video_ref: str):
    con.execute(
        "INSERT INTO asset_uses (asset_name, video_ref, used_at) VALUES (?,?,?)",
        (asset_name, video_ref, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    con.commit()


def uses_last_week(con, asset_name: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    row = con.execute(
        "SELECT COUNT(*) FROM asset_uses WHERE asset_name=? AND used_at>=?",
        (asset_name, since),
    ).fetchone()
    return row[0]


def check_rotation(con, asset_names: list, max_uses_per_week: int = 4) -> list:
    """Trả về danh sách cảnh báo nếu video sắp dựng lạm dụng chất liệu cũ.

    (intro là nhận diện kênh, được miễn.)
    """
    warnings = []
    for name in set(asset_names) - {"intro"}:
        n = uses_last_week(con, name)
        if n >= max_uses_per_week:
            warnings.append(f"'{name}' đã dùng {n} lần trong 7 ngày (trần {max_uses_per_week})")
    return warnings
