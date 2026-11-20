"""Agent INSTAGRAM (kênh tiếng Hàn, 20/11/2026) — mỗi Chủ nhật đo Reels Instagram và học, như agent Facebook.

Số liệu (tài liệu Meta, đọc 20/11/2026): GET /{ig-media-id}/insights, đường Facebook Login, quyền instagram_basic +
instagram_manage_insights + pages_read_engagement, period luôn "lifetime", số trễ tới 48 giờ. Chỉ số cho REELS: views,
reach, likes, comments, shares, saved, total_interactions, ig_reels_avg_watch_time, reels_skip_rate (% lượt xem lướt
qua trong 3 GIÂY ĐẦU — tín hiệu giống "qua được vài giây đầu" của YouTube). Vài chỉ số Meta ghi "đang phát triển"
-> lỗi thì đọc lại bộ chỉ số lõi. Đơn vị thời gian xem trung bình tài liệu không ghi -> đoán: lớn hơn 3 lần độ dài
video thì là mili giây.

Học: sở thích người xem Instagram (learning.update_preferences, key "ig_preferences" — daily cộng như Facebook),
Reel đột biến -> ưu tiên mảng + dạng (growth.apply_breakouts). Chưa kết nối / thiếu quyền -> không làm gì.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import learned as store

log = logging.getLogger("ig_insights")

ROOT = Path(__file__).resolve().parent.parent
STORE_KEY = "instagram"
MIN_AGE_DAYS, MAX_AGE_DAYS = 2, 60
METRICS = "views,reach,likes,comments,shares,saved,total_interactions,ig_reels_avg_watch_time,reels_skip_rate"
CORE = "reach,likes,comments,shares,saved"


def _data() -> dict:
    try:
        d = store.load_learned().get(STORE_KEY)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    data = store.load_learned()
    data[STORE_KEY] = d
    store.save_learned(data)


def _vn(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", ".")


def media_insights(media_id: str, get=None) -> dict:
    """{chỉ số: số} của một Reel; bộ đầy đủ lỗi (chỉ số "đang phát triển") thì đọc bộ lõi."""
    from .publish import facebook
    for metric in (METRICS, CORE):
        try:
            body = facebook.graph_get(f"{media_id}/insights", get, metric=metric)
        except facebook.FacebookAuthError:
            raise
        except Exception as exc:
            log.info("Insights %s (%s) lỗi: %s", media_id, metric[:20], str(exc)[:120])
            continue
        out = {}
        for item in body.get("data") or []:
            vals = item.get("values") or []
            v = (vals[-1].get("value") if vals else None)
            if v is None:
                v = (item.get("total_value") or {}).get("value")
            if isinstance(v, (int, float)):
                out[item.get("name")] = float(v)
        return out
    return {}


def watch_seconds(raw, duration):
    """Thời gian xem trung bình -> giây (tài liệu không ghi đơn vị)."""
    if raw is None:
        return None
    return raw / 1000 if duration and raw > 3 * duration else raw


def collect(con, now: datetime, get=None) -> list:
    from .fb_insights import _duration
    rows = con.execute("SELECT id, script_id, title, file, instagram_id, instagram_due FROM videos"
                       " WHERE instagram_id IS NOT NULL").fetchall()
    out = []
    for r in rows:
        age = (now - datetime.fromisoformat(str(r["instagram_due"]).replace("Z", "+00:00"))).total_seconds() / 86400 \
            if r["instagram_due"] else MIN_AGE_DAYS
        if age > MAX_AGE_DAYS:
            continue
        try:
            m = media_insights(r["instagram_id"], get)
        except Exception as exc:
            log.info("Không đọc được số liệu Instagram của video #%s: %s", r["id"], str(exc)[:120])
            continue
        if not m:
            continue
        dur = _duration(r["file"])
        out.append({"id": r["id"], "script_id": r["script_id"], "title": r["title"], "age_days": round(age, 2),
                    "views": int(m.get("views") or m.get("reach") or 0), "reach": m.get("reach"),
                    "interactions": m.get("total_interactions") or sum(m.get(k) or 0 for k in
                                                                       ("likes", "comments", "shares", "saved")),
                    "skip_rate": m.get("reels_skip_rate"),
                    "avg_view_pct": (min(200.0, 100 * watch_seconds(m.get("ig_reels_avg_watch_time"), dur) / dur)
                                     if dur and m.get("ig_reels_avg_watch_time") is not None else None),
                    # "qua được 3 giây đầu" = 100 - tỷ lệ lướt qua: cùng thước đo engaged_pct của YouTube
                    "engaged_pct": (100 - m["reels_skip_rate"]) if m.get("reels_skip_rate") is not None else None})
    return out


def update(con, cfg: dict, now: datetime = None, get=None) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật khi kênh bật Instagram. Trả về các dòng báo cáo."""
    from . import growth, learning
    from .publish import facebook, instagram
    if not (cfg.get("publish", {}).get("instagram") or {}).get("enabled") or not instagram.ready():
        return []
    now = now or datetime.now(timezone.utc)
    latest = {"at": now.isoformat(timespec="seconds"), "notes": []}
    try:
        acc = instagram.account(get)
        info = facebook.graph_get(acc["id"], get, fields="followers_count,media_count,username")
        latest["account"] = {k: info.get(k) for k in ("username", "followers_count", "media_count")}
    except Exception as exc:
        latest["notes"].append(f"Không đọc được tài khoản Instagram: {str(exc)[:120]}")
    if not facebook.can("instagram_manage_insights"):
        latest["notes"].append("Chưa có quyền instagram_manage_insights — gửi /facebook để cấp thêm, agent mới đo được"
                               " từng Reel.")
        rows = []
    else:
        rows = [r for r in collect(con, now, get) if r["age_days"] >= MIN_AGE_DAYS]
    latest["measured"] = len(rows)
    if len(rows) >= 3:
        prefs = learning.update_preferences(con, rows, now, key="ig_preferences")
        latest["prefs_metric"] = prefs.get("metric") if prefs else None
    latest["breakouts"] = ["Instagram — " + n for n in growth.apply_breakouts(con, growth.find_breakouts(rows), now)]
    latest["top"] = [{"id": r["id"], "title": str(r["title"] or "")[:60], "views": r["views"],
                      "interactions": r["interactions"]} for r in sorted(rows, key=lambda r: -r["views"])[:3]]
    skips = [r["skip_rate"] for r in rows if r.get("skip_rate") is not None]
    latest["skip_rate"] = round(sum(skips) / len(skips), 1) if skips else None
    prev = _data()
    history = [h for h in (prev.get("history") or []) if isinstance(h, dict)]
    followers = (latest.get("account") or {}).get("followers_count")
    if followers is not None:
        history.append({"date": now.date().isoformat(), "followers": followers})
    _save({"latest": latest, "history": history[-26:]})
    return report_lines(latest, history)


def report_lines(latest: dict, history: list = None) -> list:
    if not latest:
        return []
    history = history if history is not None else (_data().get("history") or [])
    lines = ["", "📸 Instagram (agent Instagram):"]
    acc = latest.get("account") or {}
    if acc.get("followers_count") is not None:
        delta = ""
        if len(history) >= 2:
            delta = f" ({int(history[-1]['followers']) - int(history[-2]['followers']):+d} so với tuần trước)"
        lines.append(f"  @{acc.get('username', '')}: {_vn(acc['followers_count'])} người theo dõi{delta},"
                     f" {_vn(acc.get('media_count'))} bài")
    for t in latest.get("top") or []:
        lines.append(f"  • #{t['id']} “{t['title']}”: {_vn(t['views'])} lượt xem, {_vn(t['interactions'])} tương tác")
    if latest.get("skip_rate") is not None:
        lines.append(f"  Lướt qua trong 3 giây đầu: trung bình {str(latest['skip_rate']).replace('.', ',')}%"
                     " (thấp = câu mở đầu giữ người xem).")
    if latest.get("prefs_metric"):
        lines.append(f"  Đã học sở thích người xem Instagram ({latest.get('measured')} Reel) — daily cộng vào khi chọn"
                     " kịch bản.")
    lines += ["  " + b for b in latest.get("breakouts") or []]
    lines += ["  ℹ️ " + x for x in latest.get("notes") or []]
    return lines
