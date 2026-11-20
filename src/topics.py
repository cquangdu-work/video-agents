"""Hàng đợi CHỦ ĐỀ ĐƯỢC YÊU CẦU (19/11/2026). Người xem hỏi (agent Cộng đồng), Du gửi /chude, hoặc một
video đột biến (agent Tăng trưởng) -> chỉ số / biểu đồ đó được lấy TRƯỚC ở lượt Săn ý tưởng kế tiếp,
thay vì chờ tới lượt xoay vòng (có khi 25 ngày). Chủ đề kênh chưa có nguồn số liệu -> "danh sách mong
muốn" trong báo cáo tuần: gợi ý thêm chỉ số mới vào config/channel.yaml.

Ý tưởng sinh ra vẫn đi qua MỌI bước như thường (Săn ý tưởng, Biên tập, Biên kịch, Kiểm chứng...).
Khoá chủ đề: "wb:<mã chỉ số World Bank>" hoặc "owid:<slug biểu đồ Our World in Data>".
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

QUEUE_PER_RUN = 2          # mỗi lượt săn ý tưởng lấy tối đa chừng này yêu cầu (không lấn hết suất xoay vòng)
REPEAT_DAYS = 30           # cùng một khoá đã xếp hàng trong chừng này ngày thì không xếp lại
# từ quá chung để khớp tên chỉ số (đã bỏ dấu)
STOP = {"cua", "cho", "voi", "nhung", "nhat", "nhieu", "lam", "video", "kenh", "mot", "cac", "nhu", "the",
        "nao", "khong", "duoc", "hay", "ban", "minh", "toi", "xin", "muon", "xem", "gium", "giup", "tren",
        "trong", "nay", "kia", "nuoc", "viet", "nam", "han", "quoc", "the gioi"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt, gộp khoảng trắng: "Thất  nghiệp" -> "that nghiep"."""
    s = unicodedata.normalize("NFD", str(text or "").lower().replace("đ", "d"))
    return " ".join("".join(ch for ch in s if unicodedata.category(ch) != "Mn").split())


def catalog(cfg: dict) -> dict:
    """{khoá: tên} mọi chỉ số / biểu đồ kênh đang có nguồn (đọc từ config)."""
    src = cfg.get("sources") or {}
    wb = src.get("worldbank") or {}
    out = {}
    for ind in (wb.get("indicators") or []) + ((wb.get("races") or {}).get("indicators") or []):
        if isinstance(ind, dict) and ind.get("code"):
            out.setdefault(f"wb:{ind['code']}", str(ind.get("name") or ind["code"]))
    for c in (src.get("owid") or {}).get("charts") or []:
        if isinstance(c, dict) and c.get("slug"):
            out.setdefault(f"owid:{c['slug']}", str(c.get("name") or c["slug"]))
    return out


def _tokens(text: str, keep_marks: bool) -> list:
    t = unicodedata.normalize("NFC", str(text or "").lower()) if keep_marks else fold(text)
    return re.findall(r"\w+", t)


def match(cfg: dict, query: str, limit: int = 3) -> list:
    """Khoá các chỉ số có tên khớp nhiều từ nhất với `query` (bỏ từ chung). [] nếu không khớp.
    Gõ CÓ DẤU thì so cả dấu ("lương" khác "lượng" — bỏ dấu thì tiền lương khớp nhầm sản lượng cà phê);
    gõ không dấu thì so không dấu."""
    keep = fold(query) != " ".join(unicodedata.normalize("NFC", str(query or "").lower()).split())
    words = {w for w in _tokens(query, keep) if len(fold(w)) >= 3 and fold(w) not in STOP}
    if not words:
        return []
    scored = []
    for key, name in catalog(cfg).items():
        score = len(words & set(_tokens(name, keep)))
        if score:
            scored.append((score, key))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    if len(words) >= 2 and best < 2:               # hỏi nhiều từ mà chỉ khớp một từ: chưa đủ chắc
        return []
    return [k for s, k in sorted(scored, key=lambda x: (-x[0], x[1])) if s == best][:limit]


def key_of_url(url: str):
    """Khoá chủ đề từ link nguồn của một ý tưởng (World Bank / Our World in Data), không có thì None."""
    url = str(url or "")
    m = re.search(r"data\.worldbank\.org/indicator/([A-Za-z0-9_.]+)", url)
    if m:
        return f"wb:{m.group(1)}"
    m = re.search(r"ourworldindata\.org/grapher/([a-z0-9-]+)", url)
    return f"owid:{m.group(1)}" if m else None


def covered(con, key: str) -> list:
    """Video ĐÃ ĐĂNG về chủ đề này: [(videos.id, youtube_id, tiêu đề)] — trả lời người xem bằng link."""
    out = []
    rows = con.execute("SELECT v.id, v.youtube_id, v.title, i.source_url FROM videos v"
                       " JOIN scripts s ON s.id = v.script_id JOIN ideas i ON i.id = s.idea_id"
                       " WHERE v.status = 'published' AND v.youtube_id IS NOT NULL ORDER BY v.id DESC").fetchall()
    for r in rows:
        if key_of_url(r["source_url"]) == key:
            out.append((r["id"], r["youtube_id"], r["title"]))
    return out


def request(con, key, topic: str, origin: str, detail: str = "") -> str:
    """Ghi một yêu cầu. Trả về "pending" (đã xếp hàng), "duplicate" (đã có trong REPEAT_DAYS ngày) hoặc
    "wish" (chưa có nguồn số liệu — vào danh sách mong muốn)."""
    since = (datetime.now(timezone.utc) - timedelta(days=REPEAT_DAYS)).isoformat(timespec="seconds")
    if key and con.execute("SELECT 1 FROM topic_requests WHERE key = ? AND created_at >= ?",
                           (key, since)).fetchone():
        return "duplicate"
    status = "pending" if key else "wish"
    con.execute("INSERT INTO topic_requests (key, topic, origin, detail, status, created_at) VALUES (?,?,?,?,?,?)",
                (key, str(topic or "")[:200], origin, str(detail or "")[:400], status, _now()))
    con.commit()
    return status


def with_requests(cfg: dict, con) -> dict:
    """Bản sao cấu hình có `priority` cho các nguồn: mã World Bank (hai nước, cuộc đua, bản đồ) và slug
    OWID được yêu cầu lấy TRƯỚC xoay vòng (worldbank.todays_indicators). Yêu cầu đã dùng -> "queued"."""
    rows = con.execute("SELECT id, key FROM topic_requests WHERE status = 'pending' AND key IS NOT NULL"
                       " ORDER BY id LIMIT ?", (QUEUE_PER_RUN,)).fetchall()
    if not rows:
        return cfg
    wb_codes = [r["key"][3:] for r in rows if r["key"].startswith("wb:")]
    slugs = [r["key"][5:] for r in rows if r["key"].startswith("owid:")]
    src = dict(cfg.get("sources") or {})
    wb = dict(src.get("worldbank") or {})
    if wb_codes:
        wb["priority"] = wb_codes
        for sub in ("races", "world"):
            if isinstance(wb.get(sub), dict):
                wb[sub] = {**wb[sub], "priority": wb_codes}
    src["worldbank"] = wb
    if slugs:
        src["owid"] = {**(src.get("owid") or {}), "priority": slugs}
    now = _now()
    con.executemany("UPDATE topic_requests SET status = 'queued', queued_at = ? WHERE id = ?",
                    [(now, r["id"]) for r in rows])
    con.commit()
    return {**cfg, "sources": src}


def weekly_lines(con, now: datetime = None) -> list:
    """Mục "🗳 Chủ đề được yêu cầu" của báo cáo tuần."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat(timespec="seconds")
    rows = con.execute("SELECT key, topic, origin, status FROM topic_requests WHERE created_at >= ? ORDER BY id",
                       (since,)).fetchall()
    if not rows:
        return []
    origin = {"viewer": "người xem", "du": "Du", "breakout": "video đột biến", "big_channel": "kênh lớn đột biến"}
    lines = ["", "🗳 Chủ đề được yêu cầu tuần này:"]
    for r in rows:
        where = {"wish": "CHƯA CÓ NGUỒN số liệu — thêm chỉ số mới vào config nếu đáng làm",
                 "queued": "đã đưa vào lượt săn ý tưởng", "pending": "chờ lượt săn ý tưởng kế tiếp"}.get(r["status"], "")
        lines.append(f"  • {r['topic'] or r['key']} ({origin.get(r['origin'], r['origin'])}) — {where}")
    return lines
