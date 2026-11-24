"""Agent FACEBOOK (20/11/2026) — mỗi Chủ nhật đo và học để xây Trang Facebook của kênh. Chỉ ĐỌC.

1. Số liệu từng Reel (Graph API video_insights): lượt phát, người tiếp cận, thời gian xem trung bình, người
   theo dõi mới nhờ Reel, cảm xúc, bình luận + chia sẻ, đường giữ chân -> bảng fb_stats.
2. Số liệu cả Trang: người theo dõi (+ chênh lệch theo tuần), 28 ngày: lượt xem, theo dõi mới / bỏ theo dõi.
3. Tiến độ Kiếm tiền từ nội dung (chương trình theo lời mời): ~15 Reels / 30 ngày trên ≥ 10 ngày khác nhau
   (tra 20/11/2026 từ nguồn thứ cấp — điều kiện thật xem trong Professional Dashboard của Trang).
4. TỰ HỌC:
   - sở thích người xem Facebook (kiểu mở đầu / mảng / dạng video) bằng đúng thuật toán của YouTube
     (`learning.update_preferences`, key "fb_preferences") -> daily cộng thêm, nặng bằng nửa YouTube;
   - Reel ĐỘT BIẾN (lượt phát/ngày ≥ 2,5× trung vị) -> ưu tiên mảng + dạng đó như agent Tăng trưởng;
   - GIỜ ĐĂNG: mỗi Reel hẹn vào một khung trong `publish.facebook.slots`, chọn kiểu Thompson sampling theo
     lượt phát/ngày đã đo (khung nào tốt được dùng nhiều hơn, khung ít dữ liệu vẫn được thử).
5. So với YouTube: cùng một video, Facebook được bao nhiêu lượt so với YouTube.

Không đổi luật nào; chưa kết nối Trang (src/publish/facebook.py) thì không làm gì.

    python -m src.fb_insights            # in tình trạng đã lưu
"""
import logging
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import learned as store

log = logging.getLogger("fb_insights")

ROOT = Path(__file__).resolve().parent.parent
STORE_KEY = "facebook"
MIN_AGE_DAYS = 2          # Reel đăng chưa tới chừng này ngày: chưa đủ lượt để học
MAX_AGE_DAYS = 60         # quá chừng này ngày thì thôi đo lại (số đã ổn định, đỡ gọi API)
SLOT_SHRINK = 3.0         # mỗi khung giờ như có thêm 3 Reel "trung bình" — ít dữ liệu thì không kết luận mạnh
CM_REELS, CM_DAYS = 15, 10
VN = timezone(timedelta(hours=7))


def _data() -> dict:
    try:
        d = store.load_learned().get(STORE_KEY)
        return d if isinstance(d, dict) else {}
    except Exception as exc:
        log.warning("Agent Facebook: không đọc được learned.yaml (%s)", exc)
        return {}


def _save(fb: dict) -> None:
    d = store.load_learned()            # file hỏng thì báo lỗi, không ghi đè mất những thứ đã học
    d[STORE_KEY] = fb
    store.save_learned(d)


def _vn(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", ".")


def _age(at: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(str(at).replace("Z", "+00:00"))).total_seconds() / 86400


# ------------------------------------------------------------------ 1. đo từng Reel
def reels(con, now: datetime) -> list:
    """Reel đã công khai (giờ hẹn đã qua) trong MAX_AGE_DAYS ngày."""
    rows = con.execute("SELECT id, script_id, title, file, facebook_id, facebook_at, facebook_slot FROM videos"
                       " WHERE facebook_id IS NOT NULL AND facebook_at IS NOT NULL").fetchall()
    return [dict(r) for r in rows if 0 <= _age(r["facebook_at"], now) <= MAX_AGE_DAYS]


def _duration(file: str):
    try:
        from .assemble import ffprobe_duration
        return ffprobe_duration(ROOT / file) or None
    except Exception:
        return None


def parse(metrics: dict) -> dict:
    """Chỉ số thô của Graph API -> các cột của fb_stats (ms -> giây; dict cảm xúc -> tổng)."""
    def num(name):
        v = metrics.get(name)
        if isinstance(v, dict):
            return sum(v.values())
        return v
    out = {"plays": num("blue_reels_play_count"), "reach": num("fb_reels_total_plays"),
           "followers": num("post_video_followers"), "reactions": num("post_video_likes_by_reaction_type"),
           "social": num("post_video_social_actions")}
    for col, name in (("avg_watch_s", "post_video_avg_time_watched"), ("view_time_s", "post_video_view_time")):
        v = num(name)
        out[col] = round(v / 1000, 2) if v is not None else None
    hold = None
    graph = metrics.get("post_video_retention_graph")
    if isinstance(graph, dict) and graph:
        # 40 mốc (0..39) từ 100% đi xuống; tài liệu không nói là 0-1 hay 0-100 -> tự nhận ra thang
        scale = 100.0 if max(graph.values()) <= 1.5 else 1.0
        v = graph.get("10")                                 # mốc 10/40 = 1/4 video
        hold = round(v * scale, 1) if v is not None else None
    out["hold_quarter"] = hold
    return out


def collect(con, now: datetime, get=None) -> list:
    """Đo mọi Reel còn trong cửa sổ, ghi đè dòng cũ của mỗi video. Reel nào lỗi thì bỏ qua Reel đó."""
    from .publish import facebook
    done = []
    for r in reels(con, now):
        try:
            m = facebook.reel_insights(r["facebook_id"], get)
        except Exception as exc:
            log.info("Không đọc được số liệu Reel của video #%s: %s", r["id"], str(exc)[:150])
            continue
        row = {**parse(m), "video_id": r["id"], "facebook_id": r["facebook_id"],
               "fetched_at": now.isoformat(timespec="seconds"), "age_days": round(_age(r["facebook_at"], now), 2),
               "duration_s": _duration(r["file"])}
        cols = list(row)
        con.execute(f"INSERT OR REPLACE INTO fb_stats ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [row[c] for c in cols])
        done.append(row)
    con.commit()
    return done


def learning_rows(con) -> list:
    """Dòng theo khuôn weekly.build_rows để dùng chung bộ học của YouTube (sở thích, đột biến)."""
    rows = con.execute("SELECT f.*, v.script_id, v.title, v.facebook_slot FROM fb_stats f"
                       " JOIN videos v ON v.id = f.video_id WHERE v.script_id IS NOT NULL").fetchall()
    out = []
    for r in rows:
        if (r["age_days"] or 0) < MIN_AGE_DAYS or r["plays"] is None:
            continue
        pct = (min(200.0, 100 * r["avg_watch_s"] / r["duration_s"])
               if r["avg_watch_s"] is not None and r["duration_s"] else None)
        out.append({"id": r["video_id"], "script_id": r["script_id"], "title": r["title"],
                    "views": int(r["plays"]), "avg_view_pct": pct, "subs_gained": r["followers"],
                    "age_days": r["age_days"], "slot": r["facebook_slot"], "hold_quarter": r["hold_quarter"],
                    "reach": r["reach"]})
    return out


def plays_per_day(r: dict) -> float:
    from .growth import views_per_day
    return views_per_day(r)


# ------------------------------------------------------------------ 2. giờ đăng
def slot_stats(rows: list) -> dict:
    """{khung giờ: [log10(1 + lượt phát/ngày), ...]} — chỉ Reel đã đủ MIN_AGE_DAYS."""
    out = {}
    for r in rows:
        if r.get("slot"):
            out.setdefault(r["slot"], []).append(math.log10(1 + plays_per_day(r)))
    return out


def choose_slot(con, fcfg: dict, seed) -> str:
    """Khung giờ đăng cho một Reel. Thompson sampling: mỗi khung lấy một mẫu quanh trung bình đã co về trung
    bình chung (SLOT_SHRINK), khung có mẫu cao nhất thắng. Lỗi gì cũng lùi về giờ cố định trong cấu hình."""
    fixed = str(fcfg.get("publish_time_local") or "19:00")
    slots = [str(s) for s in (fcfg.get("slots") or []) if s] or [fixed]
    if len(slots) == 1:
        return slots[0]
    try:
        stats = slot_stats(learning_rows(con))
        allv = [v for s in slots for v in stats.get(s, [])]
        rng = random.Random(f"fbslot-{seed}")       # cùng video -> cùng khung (bấm thử lại không đổi giờ)
        if len(allv) < 2:
            return rng.choice(slots)
        mean = sum(allv) / len(allv)
        sd = (sum((v - mean) ** 2 for v in allv) / len(allv)) ** 0.5 or 0.3
        best, best_draw = slots[0], -1e9
        for s in slots:
            vs = stats.get(s, [])
            mu = (sum(vs) + SLOT_SHRINK * mean) / (len(vs) + SLOT_SHRINK)
            draw = rng.gauss(mu, sd / math.sqrt(len(vs) + 1))
            if draw > best_draw:
                best, best_draw = s, draw
        return best
    except Exception as exc:
        log.warning("Chọn giờ đăng Facebook lỗi (%s) — dùng %s", exc, fixed)
        return fixed


# ------------------------------------------------------------------ 3. Trang + kiếm tiền
def cm_progress(con, now: datetime) -> tuple:
    """(số Reel, số NGÀY khác nhau theo giờ Việt Nam) đã công khai trong 30 ngày qua."""
    since = now - timedelta(days=30)
    days, n = set(), 0
    for (at,) in con.execute("SELECT facebook_at FROM videos WHERE facebook_id IS NOT NULL AND facebook_at IS NOT NULL"):
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        if since <= t <= now:
            n += 1
            days.add(t.astimezone(VN).date())
    return n, len(days)


def vs_youtube(con, rows: list):
    """Trung vị (lượt phát Facebook / lượt xem YouTube) của các video có cả hai, None nếu < 3 video."""
    ratios = []
    for r in rows:
        yt = con.execute("SELECT views FROM video_stats WHERE video_id = ? ORDER BY fetched_at DESC LIMIT 1",
                         (r["id"],)).fetchone()
        if yt and yt["views"]:
            ratios.append(r["views"] / yt["views"])
    if len(ratios) < 3:
        return None
    ratios.sort()
    mid = len(ratios) // 2
    return round(ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2, 2), len(ratios)


# ------------------------------------------------------------------ bài viết (src/fb_post.py)
def post_stats(con, now: datetime, get=None) -> dict:
    """Tương tác của các bài viết ảnh + chữ đã đăng trong 60 ngày (cảm xúc, bình luận, chia sẻ). Bài còn hẹn giờ
    (chưa lên) hoặc lỗi đọc thì bỏ qua bài đó."""
    from .publish import facebook
    since = (now - timedelta(days=60)).isoformat(timespec="seconds")
    rows = con.execute("SELECT id, title, fb_post_id FROM videos WHERE fb_post_id IS NOT NULL"
                       " AND COALESCE(decided_at, facebook_at, published_at, created_at) >= ?", (since,)).fetchall()
    stats = []
    for r in rows:
        try:
            e = facebook.post_engagement(r["fb_post_id"], get)
        except Exception as exc:
            log.info("Không đọc được tương tác bài viết của video #%s: %s", r["id"], str(exc)[:120])
            continue
        stats.append({"id": r["id"], "title": str(r["title"] or "")[:60], **e,
                      "total": e["reactions"] + e["comments"] + e["shares"]})
    if not stats:
        return {}
    top = max(stats, key=lambda s: s["total"])
    return {"n": len(stats), "reactions": sum(s["reactions"] for s in stats),
            "comments": sum(s["comments"] for s in stats), "shares": sum(s["shares"] for s in stats),
            "top": {k: top[k] for k in ("id", "title", "total")}}


# ------------------------------------------------------------------ 4. tổng hợp
def update(con, cfg: dict, now: datetime = None, get=None) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật. Lưu learned.yaml["facebook"], trả về các dòng báo cáo."""
    from . import growth, learning
    from .publish import facebook
    now = now or datetime.now(timezone.utc)
    if not facebook.connected():
        return []
    prev = _data()
    latest = {"at": now.isoformat(timespec="seconds"), "notes": []}
    try:
        latest["page"] = facebook.page_insights(get)
    except Exception as exc:
        latest["notes"].append(f"Không đọc được số liệu Trang: {str(exc)[:120]}")
    if facebook.can("read_insights"):
        collect(con, now, get)
    else:
        latest["notes"].append("Chưa có quyền read_insights — gửi /facebook để cấp thêm, agent mới đo được từng Reel.")
    rows = learning_rows(con)
    latest["reels_measured"] = len(rows)
    if len(rows) >= 3:
        prefs = learning.update_preferences(con, rows, now, key="fb_preferences")
        latest["prefs_metric"] = prefs.get("metric") if prefs else None
    found = growth.find_breakouts(rows)
    latest["breakouts"] = ["Facebook — " + n for n in growth.apply_breakouts(con, found, now)]
    latest["cm"] = list(cm_progress(con, now))
    stats = slot_stats(rows)
    latest["slots"] = {s: {"n": len(vs), "plays_per_day": round(sum(10 ** v - 1 for v in vs) / len(vs), 1)}
                       for s, vs in stats.items()}
    latest["vs_youtube"] = vs_youtube(con, rows)
    top = sorted(rows, key=lambda r: -plays_per_day(r))[:3]
    latest["top"] = [{"id": r["id"], "title": str(r["title"] or "")[:60], "plays": r["views"],
                      "followers": r["subs_gained"], "pct": round(r["avg_view_pct"]) if r["avg_view_pct"] else None}
                     for r in top]
    try:
        latest["posts"] = post_stats(con, now, get)
    except Exception as exc:                       # bài viết là phần thêm: lỗi không làm hỏng báo cáo Reels
        log.warning("Đo bài viết Facebook lỗi: %s", exc)
    holds = [r["hold_quarter"] for r in rows if r.get("hold_quarter") is not None]
    latest["hold_quarter"] = round(sum(holds) / len(holds), 1) if holds else None
    history = [h for h in (prev.get("history") or []) if isinstance(h, dict)]
    followers = (latest.get("page") or {}).get("followers")
    if followers is not None:
        history.append({"date": now.date().isoformat(), "followers": followers})
    _save({"latest": latest, "history": history[-26:]})
    return report_lines(latest, history)


def report_lines(latest: dict, history: list = None) -> list:
    """Mục "📘 Facebook" của báo cáo tuần."""
    if not latest:
        return []
    history = history if history is not None else (_data().get("history") or [])
    lines = ["", "📘 Facebook (agent Facebook):"]
    page = latest.get("page") or {}
    if page.get("followers") is not None:
        delta = ""
        if len(history) >= 2 and history[-2].get("followers") is not None:
            delta = f" ({int(history[-1]['followers']) - int(history[-2]['followers']):+d} so với tuần trước)"
        extra = []
        if page.get("page_media_view") is not None:
            extra.append(f"{_vn(page['page_media_view'])} lượt xem nội dung")
        if page.get("page_daily_follows_unique") is not None:
            extra.append(f"+{_vn(page['page_daily_follows_unique'])} theo dõi mới")
        if page.get("page_daily_unfollows_unique") is not None:
            extra.append(f"-{_vn(page['page_daily_unfollows_unique'])} bỏ theo dõi")
        lines.append(f"  Trang: {_vn(page['followers'])} người theo dõi{delta}"
                     + (" · 28 ngày: " + ", ".join(extra) if extra else ""))
    n, d = latest.get("cm") or (0, 0)
    ok = n >= CM_REELS and d >= CM_DAYS
    lines.append(f"  Kiếm tiền từ nội dung (theo lời mời): 30 ngày qua đăng {n}/{CM_REELS} Reels trên {d}/{CM_DAYS}"
                 f" ngày — {'đủ nhịp đăng; xem lời mời trong Professional Dashboard của Trang' if ok else 'chưa đủ nhịp đăng'}.")
    for t in latest.get("top") or []:
        lines.append(f"  • #{t['id']} “{t['title']}”: {_vn(t['plays'])} lượt phát"
                     + (f", {t['pct']}% thời lượng" if t.get("pct") is not None else "")
                     + (f", +{_vn(t['followers'])} theo dõi" if t.get("followers") else ""))
    if latest.get("hold_quarter") is not None:
        lines.append(f"  Giữ chân: trung bình còn {latest['hold_quarter']}% lượt phát ở 1/4 video.")
    slots = latest.get("slots") or {}
    if slots:
        lines.append("  Giờ đăng đang thử (giờ VN): " + " · ".join(
            f"{s}: {v['n']} Reel, ~{_vn(v['plays_per_day'])} lượt phát/ngày" for s, v in sorted(slots.items())))
    posts = latest.get("posts") or {}
    if posts:
        top = posts.get("top") or {}
        lines.append(f"  Bài viết ({posts['n']} bài, 60 ngày): {_vn(posts['reactions'])} cảm xúc, {_vn(posts['comments'])}"
                     f" bình luận, {_vn(posts['shares'])} chia sẻ"
                     + (f"; nhiều tương tác nhất: #{top['id']} “{top['title']}” ({_vn(top['total'])})" if top else "") + ".")
    vs = latest.get("vs_youtube")
    if vs:
        lines.append(f"  So với YouTube ({vs[1]} video có cả hai): Facebook được {str(vs[0]).replace('.', ',')}×"
                     " lượt xem YouTube (trung vị).")
    if latest.get("prefs_metric"):
        lines.append(f"  Đã học sở thích người xem Facebook ({latest.get('reels_measured')} Reel) — daily cộng"
                     " vào khi chọn kịch bản (nặng bằng nửa YouTube).")
    lines += ["  " + b for b in latest.get("breakouts") or []]
    lines += ["  ℹ️ " + x for x in latest.get("notes") or []]
    return lines


def status_text(con=None) -> str:
    """Tóm tắt ngắn cho lệnh /facebook."""
    d = _data()
    latest = d.get("latest") or {}
    parts = []
    if con is not None:
        n, days = cm_progress(con, datetime.now(timezone.utc))
        parts.append(f"30 ngày qua: {n}/{CM_REELS} Reels trên {days}/{CM_DAYS} ngày (nhịp đăng cho Kiếm tiền từ"
                     " nội dung).")
    if latest:
        body = [x.strip() for x in report_lines(latest, d.get("history") or [])[2:]]
        parts += [x for x in body if not x.startswith("Kiếm tiền")][:4]
        parts.append(f"(agent Facebook đo lần cuối {str(latest.get('at', ''))[:10]})")
    else:
        parts.append("Agent Facebook chưa đo lần nào — chạy trong lượt Phân tích Chủ nhật.")
    return "\n".join(parts)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from . import db
    con = db.connect()
    try:
        print(status_text(con))
    finally:
        con.close()


if __name__ == "__main__":
    main()
