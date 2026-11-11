"""Kho ý tưởng + kịch bản trên SQLite (file data/pipeline.db, tự tạo khi chạy lần đầu).

Vòng đời một ý tưởng (cột status):
    raw -> candidate -> selected -> scripted -> verified -> sent
    (bị loại ở bước nào thì thành 'rejected', kèm lý do)

Vòng đời một video (bảng videos, giai đoạn 4):
    pending_review -> approved -> published
                   -> rejected
    Chỉ Du bấm nút trên Telegram mới chuyển được pending_review -> approved.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .utils import norm_title, similarity

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pipeline.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    title_norm  TEXT NOT NULL,
    summary     TEXT,
    angle       TEXT,
    source_name TEXT,
    source_url  TEXT UNIQUE,
    lang        TEXT,
    status      TEXT DEFAULT 'raw',
    reject_reason TEXT,
    scores      TEXT,            -- JSON: {"curiosity": 4, ...}
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS scripts (
    id          INTEGER PRIMARY KEY,
    idea_id     INTEGER REFERENCES ideas(id),
    hooks       TEXT,            -- JSON: 3 phương án câu mở đầu
    body        TEXT,
    factcheck   TEXT,            -- JSON: [{"claim":..., "sources":[...], "ok":true}]
    status      TEXT DEFAULT 'draft',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id            INTEGER PRIMARY KEY,
    script_id     INTEGER UNIQUE REFERENCES scripts(id),
    file          TEXT NOT NULL,   -- đường dẫn tương đối tới bản phát hành
    title         TEXT,
    description   TEXT,
    tags          TEXT,            -- JSON: ["dữ liệu", ...]
    qc            TEXT,            -- JSON: kết quả agent Kiểm định lúc gửi duyệt
    status        TEXT DEFAULT 'pending_review',
    review_note   TEXT,            -- Du trả lời tin nhắn video -> ghi chú/lý do loại
    tg_message_id INTEGER,         -- tin nhắn Telegram chứa video (để khớp câu trả lời)
    youtube_id    TEXT,
    youtube_url   TEXT,
    youtube_privacy TEXT,          -- chế độ hiển thị YouTube THỰC TẾ trả về
    created_at    TEXT,
    decided_at    TEXT,
    published_at  TEXT
);
CREATE TABLE IF NOT EXISTS video_stats (   -- mỗi lần agent Phân tích đo là một dòng
    id           INTEGER PRIMARY KEY,
    video_id     INTEGER REFERENCES videos(id),
    fetched_at   TEXT,
    source       TEXT,            -- analytics (OAuth, đủ chỉ số) | public (chỉ xem/thích/bình luận)
    views        INTEGER,
    likes        INTEGER,
    comments     INTEGER,
    shares       INTEGER,
    subs_gained  INTEGER,
    avg_view_sec REAL,
    avg_view_pct REAL,            -- % video được xem trung bình ("tỷ lệ xem hết")
    retention    TEXT             -- JSON: [[vị trí 0..1, tỷ lệ còn xem], ...]
);
CREATE TABLE IF NOT EXISTS state (   -- ô nhớ nhỏ: vị trí đọc Telegram, v.v.
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_raw_ideas(con, items, sim_threshold: float = 0.55) -> int:
    """Nạp ý tưởng thô, bỏ qua cái đã có (trùng URL hoặc tiêu đề quá giống).

    Trả về số ý tưởng mới thực sự được thêm.
    """
    existing = [r["title"] for r in con.execute("SELECT title FROM ideas")]
    added = 0
    for it in items:
        if any(similarity(it["title"], old) >= sim_threshold for old in existing):
            continue
        try:
            con.execute(
                "INSERT INTO ideas (title, title_norm, summary, source_name, source_url, lang, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (it["title"], norm_title(it["title"]), it.get("summary", ""),
                 it.get("source", ""), it.get("url", ""), it.get("lang", ""), _now()),
            )
            existing.append(it["title"])
            added += 1
        except sqlite3.IntegrityError:   # trùng source_url
            continue
    con.commit()
    return added


def todays_raw(con, limit: int = 60):
    rows = con.execute(
        "SELECT * FROM ideas WHERE status='raw' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def set_status(con, idea_id: int, status: str, reason: str = None, scores: dict = None,
               angle: str = None):
    con.execute(
        "UPDATE ideas SET status=?, reject_reason=COALESCE(?, reject_reason),"
        " scores=COALESCE(?, scores), angle=COALESCE(?, angle) WHERE id=?",
        (status, reason, json.dumps(scores, ensure_ascii=False) if scores else None,
         angle, idea_id),
    )
    con.commit()


def save_script(con, idea_id: int, hooks, body: str, factcheck=None, status: str = "draft") -> int:
    cur = con.execute(
        "INSERT INTO scripts (idea_id, hooks, body, factcheck, status, created_at) VALUES (?,?,?,?,?,?)",
        (idea_id, json.dumps(hooks, ensure_ascii=False), body,
         json.dumps(factcheck, ensure_ascii=False) if factcheck else None, status, _now()),
    )
    con.commit()
    return cur.lastrowid


# ------------------------------------------------------------ Giai đoạn 4
def get_script_with_idea(con, script_id: int):
    """Kịch bản + ý tưởng gốc của nó (tiêu đề, góc, nguồn) — agent Đăng bài cần cả hai."""
    row = con.execute(
        "SELECT s.id, s.idea_id, s.body, s.hooks, s.status AS script_status,"
        " i.title, i.angle, i.summary, i.source_url, i.source_name"
        " FROM scripts s JOIN ideas i ON i.id = s.idea_id WHERE s.id = ?", (script_id,)
    ).fetchone()
    return dict(row) if row else None


_VIDEO_FIELDS = {
    "file", "title", "description", "tags", "qc", "status", "review_note",
    "tg_message_id", "youtube_id", "youtube_url", "youtube_privacy",
    "decided_at", "published_at",
}


def upsert_video(con, script_id: int, file: str, title: str, description: str,
                 tags: list, qc: list) -> int:
    """Tạo (hoặc làm mới) bản ghi video ở trạng thái chờ duyệt.

    Dựng lại cùng một kịch bản thì ghi đè bản cũ và đưa về pending_review —
    TRỪ KHI bản cũ đã đăng: lúc đó từ chối, tránh đăng trùng.
    """
    old = con.execute("SELECT id, status FROM videos WHERE script_id=?", (script_id,)).fetchone()
    payload = (file, title, description, json.dumps(tags, ensure_ascii=False),
               json.dumps(qc, ensure_ascii=False))
    if old:
        if old["status"] == "published":
            raise ValueError(f"Kịch bản #{script_id} đã đăng rồi — không gửi duyệt lại.")
        con.execute(
            "UPDATE videos SET file=?, title=?, description=?, tags=?, qc=?,"
            " status='pending_review', review_note=NULL, tg_message_id=NULL,"
            " decided_at=NULL, created_at=? WHERE id=?", payload + (_now(), old["id"]))
        con.commit()
        return old["id"]
    cur = con.execute(
        "INSERT INTO videos (script_id, file, title, description, tags, qc, created_at)"
        " VALUES (?,?,?,?,?,?,?)", (script_id,) + payload + (_now(),))
    con.commit()
    return cur.lastrowid


def get_video(con, video_id: int):
    row = con.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        return None
    v = dict(row)
    v["tags"] = json.loads(v["tags"] or "[]")
    v["qc"] = json.loads(v["qc"] or "[]")
    return v


def update_video(con, video_id: int, **fields):
    bad = set(fields) - _VIDEO_FIELDS
    if bad:
        raise ValueError(f"Cột không hợp lệ: {bad}")
    sets = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE videos SET {sets} WHERE id=?", (*fields.values(), video_id))
    con.commit()


def transition_video(con, video_id: int, from_status: str, to_status: str) -> bool:
    """Đổi trạng thái CHỈ KHI video đang ở đúng from_status. Trả về True nếu đổi được.

    Đây là cái chốt chống đăng trùng: bấm nút Duyệt hai lần (hoặc Telegram gửi
    lặp một sự kiện) thì lần thứ hai thấy trạng thái đã khác -> không làm gì.
    """
    stamp = {"approved": "decided_at", "rejected": "decided_at",
             "published": "published_at"}.get(to_status)
    sql = "UPDATE videos SET status=?" + (f", {stamp}=?" if stamp else "") + " WHERE id=? AND status=?"
    args = (to_status,) + ((_now(),) if stamp else ()) + (video_id, from_status)
    cur = con.execute(sql, args)
    con.commit()
    return cur.rowcount == 1


def get_state(con, key: str, default: str = None):
    row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(con, key: str, value) -> None:
    con.execute("INSERT INTO state (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    con.commit()


def save_video_stats(con, video_id: int, source: str, stats: dict, retention: list = None) -> None:
    con.execute(
        "INSERT INTO video_stats (video_id, fetched_at, source, views, likes, comments, shares,"
        " subs_gained, avg_view_sec, avg_view_pct, retention) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (video_id, _now(), source, stats.get("views"), stats.get("likes"), stats.get("comments"),
         stats.get("shares"), stats.get("subs_gained"), stats.get("avg_view_sec"),
         stats.get("avg_view_pct"), json.dumps(retention) if retention else None))
    con.commit()
