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
    retention    TEXT,            -- JSON: [[vị trí 0..1, tỷ lệ còn xem], ...]
    engaged_views INTEGER         -- lượt xem QUA ĐƯỢC vài giây đầu (Shorts: phần còn lại là lướt đi)
);
CREATE TABLE IF NOT EXISTS learning_events (  -- bộ nhớ tự học (src/learning.py)
    id        INTEGER PRIMARY KEY,
    at        TEXT,
    source    TEXT,       -- gate (cổng code bắt lỗi) | du (Du duyệt/loại/ghi chú) | outcome (kết quả kịch bản)
    kind      TEXT,       -- loại: lỗi đọc bảng, hook "Vì sao", ... / approve, reject, note / verified, draft
    stage     TEXT,       -- writer | final | spec | review
    detail    TEXT,       -- câu ví dụ / ghi chú
    idea_id   INTEGER,
    script_id INTEGER
);
CREATE TABLE IF NOT EXISTS video_styles (   -- phong cách dựng từng video (src/style.py: thử nghiệm tự học)
    script_id INTEGER PRIMARY KEY,
    assigned  TEXT,       -- JSON: mức được gán cho từng núm (tốc độ đọc, nhạc, nhịp cảnh, cỡ phụ đề)
    applied   TEXT,       -- JSON: giá trị THẬT đã dùng (khác mức gán thì video không tính cho núm đó)
    at        TEXT
);
CREATE TABLE IF NOT EXISTS topic_requests (   -- chủ đề được yêu cầu làm sớm (src/topics.py)
    id         INTEGER PRIMARY KEY,
    key        TEXT,      -- "wb:<mã chỉ số>" | "owid:<slug>"; NULL = kênh chưa có nguồn (danh sách mong muốn)
    topic      TEXT,      -- chủ đề theo lời người yêu cầu
    origin     TEXT,      -- viewer (bình luận) | du (/chude) | breakout (video đột biến)
    detail     TEXT,
    status     TEXT,      -- pending | queued | wish
    created_at TEXT,
    queued_at  TEXT
);
CREATE TABLE IF NOT EXISTS comments (   -- bình luận người xem (agent Cộng đồng, src/community.py)
    id           TEXT PRIMARY KEY,   -- id luồng bình luận YouTube
    youtube_id   TEXT,
    video_id     INTEGER,            -- videos.id của mình
    author       TEXT,
    text         TEXT,
    published_at TEXT,
    likes        INTEGER,
    kind         TEXT,               -- cau_hoi | de_xuat | bao_loi | khen | che | khac
    topic        TEXT,
    matched      TEXT,               -- khoá chủ đề khớp (đề xuất)
    reply        TEXT,               -- nháp trả lời cho Du
    fetched_at   TEXT,
    status       TEXT,               -- new (chờ Du) | posting | posted | skipped | done (khen/khác)
    tg_message_id INTEGER,           -- tin Telegram có nút ✅ Đăng / ❌ Bỏ của bình luận này
    posted_id    TEXT,               -- id câu trả lời đã đăng
    posted_at    TEXT
);
CREATE TABLE IF NOT EXISTS fb_stats (   -- số liệu Reels trên Trang Facebook (agent Facebook, src/fb_insights.py)
    video_id     INTEGER PRIMARY KEY,   -- videos.id của mình (mỗi video một dòng, lần đo mới nhất)
    facebook_id  TEXT,
    fetched_at   TEXT,
    age_days     REAL,
    duration_s   REAL,
    plays        INTEGER,   -- blue_reels_play_count (không tính xem lại)
    reach        INTEGER,   -- post_impressions_unique
    avg_watch_s  REAL,      -- post_video_avg_time_watched (gồm cả xem lại, có thể dài hơn video)
    view_time_s  REAL,
    followers    INTEGER,   -- người theo dõi Trang nhờ Reel này
    reactions    INTEGER,
    social       INTEGER,   -- bình luận + chia sẻ
    hold_quarter REAL       -- % lượt phát còn xem ở 1/4 video (đường giữ chân)
);
CREATE TABLE IF NOT EXISTS yt_news (   -- tin chính thức của YouTube đã đọc (agent Tin YouTube, src/yt_news.py)
    id        TEXT PRIMARY KEY,   -- link bài / video
    source    TEXT,
    title     TEXT,
    link      TEXT,
    published TEXT,
    relevant  INTEGER,            -- 1 = ảnh hưởng tới kênh (model lọc)
    impact    TEXT,               -- cao | vua | thap
    summary   TEXT,
    action    TEXT,
    seen_at   TEXT
);
CREATE TABLE IF NOT EXISTS state (   -- ô nhớ nhỏ: vị trí đọc Telegram, v.v.
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# Cột thêm SAU khi DB đã có dữ liệu: CREATE TABLE IF NOT EXISTS không thêm cột vào bảng cũ
_ADDED_COLUMNS = [("video_stats", "engaged_views", "INTEGER"),       # 19/11/2026
                  # bảng comments tạo sáng 19/11 chưa có các cột duyệt-đăng trả lời (chiều 19/11)
                  ("comments", "status", "TEXT"), ("comments", "tg_message_id", "INTEGER"),
                  ("comments", "posted_id", "TEXT"), ("comments", "posted_at", "TEXT"),
                  # Facebook Reels (20/11/2026): id Reel + giờ đăng + khung giờ đang thử; bình luận Facebook
                  ("videos", "facebook_id", "TEXT"), ("videos", "facebook_at", "TEXT"),
                  ("videos", "facebook_slot", "TEXT"),
                  ("comments", "platform", "TEXT"), ("comments", "link", "TEXT"),
                  # bài viết Facebook kèm video (src/fb_post.py, 20/11/2026): chữ, ảnh, tin Telegram xem trước, id bài
                  ("videos", "fb_post", "TEXT"), ("videos", "fb_post_image", "TEXT"),
                  ("videos", "fb_post_msg", "INTEGER"), ("videos", "fb_post_id", "TEXT"),
                  # Instagram Reels (kênh Hàn): id bài + giờ hẹn đăng
                  ("videos", "instagram_id", "TEXT"), ("videos", "instagram_due", "TEXT")]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    for table, col, kind in _ADDED_COLUMNS:
        if col not in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
            con.commit()
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_raw_ideas(con, items, sim_threshold: float = 0.55) -> int:
    """Nạp ý tưởng thô, bỏ qua cái đã có (trùng URL hoặc tiêu đề quá giống).

    Trả về số ý tưởng mới thực sự được thêm.

    Ý tưởng từ BẢNG SỐ (World Bank, KOSIS, OWID) chỉ chống trùng bằng URL (mỗi bảng × năm số liệu
    một URL): tiêu đề của chúng cùng một khuôn ("Bản đồ thế giới: … năm 2024 — Việt Nam thứ …"),
    so độ giống tiêu đề thì "lượng thịt" và "lượng cá" bị coi là trùng (0,8) và bị loại oan.
    """
    from .sources.datatable import is_data_source
    existing = [r["title"] for r in con.execute("SELECT title FROM ideas")]
    added = 0
    for it in items:
        if not is_data_source(it.get("source")) and any(
                similarity(it["title"], old) >= sim_threshold for old in existing):
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
def recent_hooks(con, n: int = 8) -> list:
    """Câu mở đầu (lời cảnh 1) của n kịch bản mới nhất — Biên kịch phải mở khác đi."""
    import yaml
    out = []
    for r in con.execute("SELECT body FROM scripts ORDER BY id DESC LIMIT ?", (n,)):
        try:
            scenes = yaml.safe_load(r["body"] or "") or []
            if scenes and isinstance(scenes[0], dict) and scenes[0].get("voice"):
                out.append(str(scenes[0]["voice"]))
        except yaml.YAMLError:
            continue
    return out


def get_script_with_idea(con, script_id: int):
    """Kịch bản + ý tưởng gốc của nó (tiêu đề, góc, nguồn) — agent Đăng bài cần cả hai."""
    row = con.execute(
        "SELECT s.id, s.idea_id, s.body, s.hooks, s.status AS script_status, s.factcheck,"
        " i.title, i.angle, i.summary, i.source_url, i.source_name"
        " FROM scripts s JOIN ideas i ON i.id = s.idea_id WHERE s.id = ?", (script_id,)
    ).fetchone()
    return dict(row) if row else None


_VIDEO_FIELDS = {
    "file", "title", "description", "tags", "qc", "status", "review_note",
    "tg_message_id", "youtube_id", "youtube_url", "youtube_privacy",
    "decided_at", "published_at", "facebook_id", "facebook_at", "facebook_slot",
    "fb_post", "fb_post_image", "fb_post_msg", "fb_post_id", "instagram_id", "instagram_due",
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
        " subs_gained, avg_view_sec, avg_view_pct, retention, engaged_views)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (video_id, _now(), source, stats.get("views"), stats.get("likes"), stats.get("comments"),
         stats.get("shares"), stats.get("subs_gained"), stats.get("avg_view_sec"),
         stats.get("avg_view_pct"), json.dumps(retention) if retention else None,
         stats.get("engaged_views")))
    con.commit()
