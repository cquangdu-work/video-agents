"""Kho ý tưởng + kịch bản trên SQLite (file data/pipeline.db, tự tạo khi chạy lần đầu).

Vòng đời một ý tưởng (cột status):
    raw -> candidate -> selected -> scripted -> verified -> sent
    (bị loại ở bước nào thì thành 'rejected', kèm lý do)
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
