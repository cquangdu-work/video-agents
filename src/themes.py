"""CHỦ ĐỀ CỦA TUẦN cho video dài (Du đồng ý 24/11/2026 sau bản phân tích xu hướng).

Vì sao: video dài kiểu "tổng hợp tuần" chỉ có 1-2 lượt xem (kênh Việt #9, #14) — 98% lượt xem của kênh đến từ luồng
Shorts, còn video dài sống nhờ TÌM KIẾM, và không ai gõ "câu chuyện qua con số tuần 15/11". Quét YouTube 24/11: chủ đề có
nhu cầu tìm rõ (kênh Hàn: 출산율 반등 — tin tức 0,9 triệu lượt; 지방소멸 dạng bản đồ — 34.000 lượt, gần như không ai làm;
kênh Việt: "Việt Nam đứng thứ mấy thế giới" — trung vị 158.000 lượt).

Cách làm: cấu hình kênh `longform.themes` là danh sách chủ đề xoay vòng mỗi tuần (tuần tính từ `longform.themes_start`,
một ngày Chủ nhật). Trong tuần:
  - nguồn bảng số lấy TRƯỚC xoay vòng các bảng của chủ đề (`with_theme` -> `priority` của World Bank / OWID / KOSIS);
  - Biên tập (main) và daily ưu tiên ý tưởng / kịch bản KHỚP chủ đề cho tới khi đủ `longform.theme_shorts` Shorts;
  - thứ Bảy video dài ghép các Short của chủ đề, tiêu đề là `title` của chủ đề (từ khoá người ta tìm).
Không đủ 3 Short khớp chủ đề -> video dài như cũ (các Short xem nhiều nhất tuần).
Khớp chủ đề = tiêu đề / phần đầu tóm tắt của ý tưởng chứa một trong `words` (so chữ thường, giữ dấu).
"""
from datetime import date, datetime, timedelta, timezone


def _cfg(cfg: dict) -> dict:
    return (cfg or {}).get("longform") or {}


def current(cfg: dict, today: date = None):
    """Chủ đề của tuần chứa `today` (giờ của kênh) — hoặc None nếu kênh không cấu hình chủ đề."""
    lf = _cfg(cfg)
    themes = [t for t in lf.get("themes") or [] if isinstance(t, dict) and t.get("key")]
    start = lf.get("themes_start")
    if not themes or not start:
        return None
    if today is None:
        tz = timezone(timedelta(hours=float(((cfg.get("daily") or {}).get("utc_offset_hours", 9)))))
        today = datetime.now(timezone.utc).astimezone(tz).date()
    days = (today - date.fromisoformat(str(start))).days
    if days < 0:
        return None
    return themes[(days // 7) % len(themes)]


def week_start(cfg: dict, today: date = None) -> date:
    """Ngày đầu (Chủ nhật) của tuần chủ đề chứa `today`."""
    start = date.fromisoformat(str(_cfg(cfg).get("themes_start")))
    if today is None:
        tz = timezone(timedelta(hours=float(((cfg.get("daily") or {}).get("utc_offset_hours", 9)))))
        today = datetime.now(timezone.utc).astimezone(tz).date()
    return start + timedelta(days=((today - start).days // 7) * 7)


def matches(theme: dict, title, summary="") -> bool:
    """Ý tưởng thuộc chủ đề: tiêu đề hoặc 400 ký tự đầu tóm tắt (phần "Chỉ số: …", trước bảng số) chứa một từ khoá."""
    if not theme:
        return False
    text = f"{title or ''} {str(summary or '')[:400]}".lower()
    return any(str(w).lower() in text for w in theme.get("words") or [])


def with_theme(cfg: dict, today: date = None) -> dict:
    """Bản sao cấu hình: bảng số của chủ đề tuần này lấy TRƯỚC xoay vòng (cùng cơ chế `priority` với topics.py)."""
    theme = current(cfg, today)
    if not theme:
        return cfg
    src = dict(cfg.get("sources") or {})
    wb_codes = list(theme.get("wb") or [])
    if wb_codes and src.get("worldbank"):
        wb = dict(src["worldbank"])
        wb["priority"] = list(dict.fromkeys(list(wb.get("priority") or []) + wb_codes))
        for sub in ("races", "world"):
            if isinstance(wb.get(sub), dict):
                wb[sub] = {**wb[sub], "priority": list(dict.fromkeys(list(wb[sub].get("priority") or []) + wb_codes))}
        src["worldbank"] = wb
    if theme.get("owid") and src.get("owid"):
        ow = src["owid"]
        src["owid"] = {**ow, "priority": list(dict.fromkeys(list(ow.get("priority") or []) + list(theme["owid"])))}
    if theme.get("kosis") and src.get("kosis"):
        ko = src["kosis"]
        src["kosis"] = {**ko, "priority": list(dict.fromkeys(list(ko.get("priority") or []) + list(theme["kosis"])))}
    return {**cfg, "sources": src}


def shorts_this_week(con, cfg: dict, theme: dict, today: date = None) -> int:
    """Số Shorts ĐÃ GỬI DUYỆT trong tuần chủ đề này mà khớp chủ đề."""
    since = datetime.combine(week_start(cfg, today), datetime.min.time(),
                             timezone(timedelta(hours=float(((cfg.get("daily") or {}).get("utc_offset_hours", 9))))))
    rows = con.execute("SELECT i.title, i.summary FROM videos v JOIN scripts s ON s.id = v.script_id"
                       " JOIN ideas i ON i.id = s.idea_id WHERE v.script_id IS NOT NULL AND v.tg_message_id IS NOT NULL"
                       " AND v.created_at >= ?", (since.astimezone(timezone.utc).isoformat(timespec="seconds"),))
    return sum(1 for r in rows if matches(theme, r["title"], r["summary"]))


def wanted(con, cfg: dict, today: date = None):
    """Chủ đề tuần này nếu CÒN thiếu Short (chưa đủ `longform.theme_shorts`), không thì None."""
    theme = current(cfg, today)
    if not theme:
        return None
    need = int(_cfg(cfg).get("theme_shorts", 3))
    return theme if shorts_this_week(con, cfg, theme, today) < need else None
