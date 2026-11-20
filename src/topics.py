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
        "trong", "nay", "kia", "nuoc", "viet", "nam", "han", "quoc", "nguoi", "moi", "ty", "le"}


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


LATIN = {"internet", "smartphone", "kwh", "co2"}     # từ nước ngoài hay gặp trong tên chỉ số


def _acronyms(cfg: dict) -> set:
    """Từ viết tắt trong tên chỉ số (GDP, FDI, PM2...) — được so lẻ từng từ."""
    return {w.lower() for name in catalog(cfg).values() for w in re.findall(r"\b[A-Z][A-Z0-9]+\b", name)} | LATIN


def _units(text: str, keep: bool, single: set) -> set:
    """Đơn vị để so: CỤM HAI ÂM TIẾT liền nhau ("thất nghiệp", "cà phê") + từ viết tắt / nước ngoài (`single`:
    "gdp", "fdi", "internet"). Tiếng Việt ghép từ bằng âm tiết: so từng âm tiết thì "gia" của "quốc gia" khớp
    nhầm "tham gia lực lượng lao động" (thử thật 20/11) — và "gia" không dấu nên cũng không được coi là từ Latin."""
    toks = _tokens(text, keep)
    content = lambda w: fold(w) not in STOP and not w.isdigit()
    units = {f"{a} {b}" for a, b in zip(toks, toks[1:]) if content(a) and content(b)}
    return units | {w for w in toks if fold(w) in single}


def match(cfg: dict, query: str, limit: int = 3, min_cover: float = 0.0) -> list:
    """Như _match; thêm cho KÊNH TIẾNG HÀN (20/11/2026): danh mục toàn tên tiếng Hàn mà Du gõ /chude bằng tiếng Việt
    -> khớp theo tên tiếng Việt của CÙNG mã chỉ số (wb:<mã>, owid:<slug>) trong cấu hình kênh Việt, rồi chỉ giữ
    khoá kênh Hàn đang có."""
    if re.search(r"[가-힣]", str(query or "")):
        return _match_ko(cfg, query, limit, min_cover)
    keys = _match(cfg, query, limit, min_cover)
    from . import lang
    if keys or lang.code() != "ko":
        return keys
    try:
        import yaml
        vi_cfg = yaml.safe_load((lang.ROOT / lang.DEFAULT_CONFIG).read_text(encoding="utf-8")) or {}
    except Exception:
        return keys
    have = catalog(cfg)
    with lang.using("vi"):
        found = _match(vi_cfg, query, limit * 4, min_cover)
    return [k for k in found if k in have][:limit]


_KO_GENERIC = {"영상", "채널", "만들어", "주세요", "해주세요", "대해", "관련", "비교", "한국", "세계", "나라"}


def _match_ko(cfg: dict, query: str, limit: int = 3, min_cover: float = 0.0) -> list:
    """Từ khoá tiếng Hàn: tiếng Hàn viết liền từ ghép ("합계출산율") và dính trợ từ ("출산율을") -> so CHUỖI CON: mỗi
    từ của query (bỏ trợ từ cuối, ≥ 2 chữ) nằm trong tên chỉ số thì được một điểm."""
    words = []
    for w in re.findall(r"[가-힣A-Za-z0-9]+", str(query or "")):
        w = re.sub(r"(을|를|이|가|은|는|의|에|도|로|으로|에서|와|과)$", "", w)
        if len(w) >= 2 and w not in _KO_GENERIC:
            words.append(w.lower())
    if not words:
        return []
    scored = []
    for key, name in catalog(cfg).items():
        # "GDP 대비 연구개발비" nói về chi R&D (GDP chỉ là mẫu số) — như luật "… so với GDP" của bản Việt
        low = re.sub(r"^gdp\s*대비\s*", "", name.lower())
        score = sum(1 for w in words if w in low)
        if score:
            scored.append((score, score / max(1, len(low)), key))
    if not scored:
        return []
    best = max(s for s, _, _ in scored)
    if best < min_cover * len(words):
        return []
    return [k for s, _, k in sorted(scored, key=lambda x: (-x[0], -x[1], x[2])) if s == best][:limit]


def _match(cfg: dict, query: str, limit: int = 3, min_cover: float = 0.0) -> list:
    """Khoá các chỉ số có tên khớp nhiều cụm từ nhất với `query` (bỏ từ chung). [] nếu không khớp.
    Gõ CÓ DẤU thì so cả dấu ("lương" khác "lượng" — bỏ dấu thì tiền lương khớp nhầm sản lượng cà phê);
    gõ không dấu thì so không dấu. min_cover: phần cụm từ của query phải khớp (chủ đề do model viết ra thì
    đòi cao hơn chủ đề Du gõ)."""
    keep = fold(query) != " ".join(unicodedata.normalize("NFC", str(query or "").lower()).split())
    single = _acronyms(cfg)
    want = _units(query, keep, single)
    if not want:
        return []
    scored = []
    for key, name in catalog(cfg).items():
        # "Xuất khẩu so với GDP" nói về XUẤT KHẨU (GDP chỉ là mẫu số) -> phần sau "so với" không đem ra so
        units = _units(re.split(r"\s+so với\s+", name)[0], keep, single)
        score = len(want & units)
        if score:
            # ngang điểm thì chỉ số mà phần khớp chiếm nhiều tên hơn đứng trước ("GDP" -> "Quy mô GDP" trước
            # "Vốn FDI vào so với GDP")
            scored.append((score, score / len(units), key))
    if not scored:
        return []
    best = max(s for s, _, _ in scored)
    if best < min_cover * len(want):
        return []
    return [k for s, _, k in sorted(scored, key=lambda x: (-x[0], -x[1], x[2])) if s == best][:limit]


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
