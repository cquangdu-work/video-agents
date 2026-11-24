"""Agent TĂNG TRƯỞNG (19/11/2026) — mỗi Chủ nhật nhìn CẢ KÊNH chứ không chỉ từng video:

1. ĐO KÊNH: người đăng ký, lượt xem + giờ xem 28 ngày tách Shorts / video dài, tiến độ YPP (ngưỡng ở
   config growth.ypp) và dự báo bao lâu nữa đủ người đăng ký theo nhịp hiện tại.
2. HỌC NỘI DUNG NÀO KÉO NGƯỜI ĐĂNG KÝ: số người đăng ký mới trên 1.000 lượt xem của từng video được gộp
   với độ giữ chân thành điểm tổng hợp trong sở thích người xem (learning.update_preferences) -> daily
   và máy chọn hook ưu tiên thứ vừa giữ chân vừa kéo người đăng ký.
3. VIDEO ĐỘT BIẾN của chính kênh (lượt xem mỗi ngày ≥ 2,5 lần trung vị, ≥ 300 lượt): ưu tiên mảng + dạng
   video của nó BOOST_DAYS ngày (Biên tập chọn ý tưởng, daily chọn kịch bản), xếp hàng làm tiếp chính chỉ
   số đó ở dạng khác (src/topics.py), báo Du việc nên làm tay (trả lời bình luận, ghim bình luận...).

Không tự đăng gì công khai. Số liệu kênh lưu ở data/learned.yaml ("growth").

    python -m src.growth      # in tình trạng kênh lần đo gần nhất + các ưu tiên đang chạy
"""
import logging
import sys
from datetime import datetime, timedelta, timezone

from .analysis import learned as store

log = logging.getLogger("growth")

YPP_DEFAULT = {"subs": 1000, "watch_hours": 8000, "shorts_views_90d": 20_000_000}
BREAKOUT_RATIO = 2.5        # lượt xem mỗi ngày gấp chừng này lần trung vị của kênh
BREAKOUT_MIN_VIEWS = 300    # và ít nhất chừng này lượt (kênh nhỏ: trung vị thấp, dao động thường đã gấp đôi)
BREAKOUT_MAX_AGE = 21       # chỉ xét video đăng trong chừng này ngày (đột biến cũ thì làm tiếp đã muộn)
BOOST_DAYS = 10
IDEA_BOOST_POINTS = 3.0     # Biên tập: ý tưởng cùng mảng + dạng với video đột biến được cộng chừng này điểm


def _data() -> dict:
    try:
        d = store.load_learned()
    except Exception as exc:
        log.warning("Tăng trưởng: không đọc được learned.yaml (%s)", exc)
        return {}
    g = d.get("growth") if isinstance(d, dict) else None
    return g if isinstance(g, dict) else {}


def _save(growth: dict) -> None:
    d = store.load_learned()            # file hỏng thì báo lỗi, không ghi đè mất những thứ đã học
    d["growth"] = growth
    store.save_learned(d)


def _vn(n) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


# ------------------------------------------------------------------ 3. video đột biến
def views_per_day(row: dict) -> float:
    """Lượt xem chia cho số ngày đã đăng (tính tối đa 14 ngày: Shorts nhận phần lớn lượt xem tuần đầu)."""
    return float(row.get("views") or 0) / max(1, min(int(row.get("age_days") or 1), 14))


def find_breakouts(rows: list, ratio: float = BREAKOUT_RATIO) -> list:
    """[(dòng video, số lần so với trung vị)] — rows là weekly.build_rows (chỉ Shorts có kịch bản)."""
    shorts = [r for r in rows if r.get("script_id") and r.get("views") is not None]
    if len(shorts) < 4:                     # chưa đủ video để biết "bình thường" là bao nhiêu
        return []
    rates = sorted(views_per_day(r) for r in shorts)
    mid = len(rates) // 2
    median = rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2
    if median <= 0:
        return []
    out = []
    for r in shorts:
        x = views_per_day(r) / median
        if x >= ratio and r["views"] >= BREAKOUT_MIN_VIEWS and int(r.get("age_days") or 0) <= BREAKOUT_MAX_AGE:
            out.append((r, round(x, 1)))
    return sorted(out, key=lambda rx: -rx[1])


def apply_breakouts(con, found: list, now: datetime = None) -> list:
    """Ưu tiên mảng + dạng của video đột biến, xếp hàng làm tiếp chỉ số của nó (World Bank: dạng khác của
    cùng chỉ số không trùng URL). Mỗi video chỉ xử lý MỘT lần. Trả về các dòng cho báo cáo."""
    from . import db, learning, topics
    now = now or datetime.now(timezone.utc)
    data = _data()
    today = now.date().isoformat()
    before = list(data.get("boosts") or [])
    boosts = [b for b in before if str(b.get("until", "")) >= today]      # bỏ ưu tiên đã hết hạn
    notes = []
    for r, x in found:
        if db.get_state(con, f"breakout_{r['id']}"):
            continue
        meta = con.execute("SELECT i.title, i.source_name, i.source_url, s.body FROM scripts s"
                           " JOIN ideas i ON i.id = s.idea_id WHERE s.id = ?", (r["script_id"],)).fetchone()
        if not meta:
            continue
        f = learning.features(learning._hook_of(meta["body"]), meta["title"], meta["source_name"])
        until = (now + timedelta(days=BOOST_DAYS)).date().isoformat()
        boosts.append({"family": f["family"], "kind": f["kind"], "until": until, "video_id": r["id"], "ratio": x})
        key = topics.key_of_url(meta["source_url"])
        queued = (key and key.startswith("wb:")
                  and topics.request(con, key, meta["title"], "breakout", f"video #{r['id']} đột biến {x}×") == "pending")
        db.set_state(con, f"breakout_{r['id']}", now.isoformat(timespec="seconds"))
        notes.append(f"🚀 Đột biến: #{r['id']} “{str(r.get('title') or '')[:50]}” {_vn(r['views'])} lượt xem"
                     f" ({x}× trung vị mỗi ngày) → ưu tiên mảng {f['family']} / dạng {f['kind']} tới {until}"
                     + ("; đã xếp hàng làm tiếp chỉ số này ở dạng video khác" if queued else "")
                     + ". Việc nên làm tay: trả lời bình luận của video này, ghim một bình luận gợi ý xem video dài.")
    if boosts[-10:] != before:
        data["boosts"] = boosts[-10:]
        _save(data)
    return notes


def boost_for(family: str, kind: str, data: dict = None, today: str = None) -> float:
    """Điểm ưu tiên (0-1,5) cho một ý tưởng / kịch bản cùng mảng (+0,5) và cùng dạng (+0,5 nữa) với video
    đột biến còn hiệu lực."""
    data = _data() if data is None else data
    today = today or datetime.now(timezone.utc).date().isoformat()
    score = 0.0
    for b in data.get("boosts") or []:
        if str(b.get("until", "")) < today or b.get("family") != family:
            continue
        score += 1.0 if b.get("kind") == kind else 0.5
    return min(score, 1.5)


# ------------------------------------------------------------------ 1. đo kênh
def snapshot(token: str, now: datetime = None) -> dict:
    """Số liệu cả kênh (YouTube Analytics trễ 2-3 ngày)."""
    from .publish import youtube
    today = (now or datetime.now(timezone.utc)).date()
    span = lambda days: youtube.channel_report(token, (today - timedelta(days=days)).isoformat(), today.isoformat())
    d28, d90, d365 = span(28), span(90), span(365)
    stats = youtube.channel_stats(token)
    long_hours = (round(d365["long"]["minutes"] / 60, 1) if "long" in d365
                  else (0.0 if "shorts" in d365 else None))
    return {"date": today.isoformat(), "subscribers": stats["subscribers"],
            "views_28d": d28["all"]["views"], "shorts_views_28d": (d28.get("shorts") or {}).get("views"),
            "long_hours_28d": round((d28.get("long") or {}).get("minutes", 0) / 60, 1),
            "net_subs_28d": d28["all"]["subs_gained"] - d28["all"]["subs_lost"],
            "shorts_views_90d": (d90.get("shorts") or {}).get("views"), "long_hours_365d": long_hours}


def forecast_weeks(snap: dict, target: int):
    """Số tuần nữa đủ `target` người đăng ký theo nhịp 28 ngày qua (None nếu nhịp ≤ 0 hoặc đã đủ)."""
    have, net = snap.get("subscribers") or 0, snap.get("net_subs_28d") or 0
    if have >= target or net <= 0:
        return None
    return max(1, round((target - have) / (net / 4)))


def sub_rates(rows: list) -> list:
    """[(dòng video, người đăng ký mới / 1.000 lượt xem)] giảm dần — video nào kéo người đăng ký."""
    out = [(r, 1000 * r["subs_gained"] / r["views"]) for r in rows
           if r.get("subs_gained") is not None and (r.get("views") or 0) >= 100]
    return sorted(out, key=lambda rx: -rx[1])


def report_lines(snap: dict, rows: list, notes: list, cfg: dict) -> list:
    ypp = {**YPP_DEFAULT, **((cfg.get("growth") or {}).get("ypp") or {})}
    lines = ["", "📈 Tăng trưởng kênh (agent Tăng trưởng):"]
    if snap:
        lines.append(f"  Người đăng ký: {_vn(snap['subscribers'])} ({snap['net_subs_28d']:+d} trong 28 ngày)")
        part = f"  28 ngày: {_vn(snap['views_28d'])} lượt xem"
        if snap.get("shorts_views_28d") is not None:
            part += f" (Shorts {_vn(snap['shorts_views_28d'])})"
        lines.append(part + f" · video dài {snap['long_hours_28d']:g} giờ xem".replace(".", ","))
        bits = [f"sub {_vn(snap['subscribers'])}/{_vn(ypp['subs'])}"]
        if snap.get("long_hours_365d") is not None:
            bits.append(f"giờ xem video dài 365 ngày {_vn(snap['long_hours_365d'])}/{_vn(ypp['watch_hours'])}")
        if snap.get("shorts_views_90d") is not None:
            bits.append(f"lượt xem Shorts 90 ngày {_vn(snap['shorts_views_90d'])}/{_vn(ypp['shorts_views_90d'])}")
        lines.append("  Tiến độ YPP: " + " · ".join(bits))
        weeks = forecast_weeks(snap, ypp["subs"])
        if weeks and weeks <= 104:
            lines.append(f"  Dự báo: đủ {_vn(ypp['subs'])} người đăng ký sau khoảng {weeks} tuần nếu giữ nhịp 28 ngày qua")
        elif snap["subscribers"] < ypp["subs"]:
            # kênh mới: nhịp hiện tại cho ra con số hàng nghìn tuần — vô ích; nói mục tiêu mỗi tuần thì hơn
            need = (ypp["subs"] - snap["subscribers"]) / 52
            pace = (snap.get("net_subs_28d") or 0) / 4
            pace_text = f"{pace:+.1f}".replace(".", ",")
            lines.append(f"  Mục tiêu: muốn đủ {_vn(ypp['subs'])} người đăng ký trong 12 tháng cần ~{need:.0f} người"
                         f" mới mỗi tuần (28 ngày qua: {pace_text}/tuần)")
    else:
        lines.append("  (chưa đo được cả kênh — cần token YouTube có quyền Analytics)")
    top = [(r, x) for r, x in sub_rates(rows)[:3] if x > 0]
    if top:
        lines.append("  Kéo người đăng ký tốt nhất: " + ", ".join(
            f"#{r['id']} ({f'{x:.1f}'.replace('.', ',')} sub / 1.000 lượt xem)" for r, x in top)
            + " — đã tính vào điểm sở thích người xem")
    lines += [f"  {n}" for n in notes]
    active = [b for b in _data().get("boosts") or []
              if str(b.get("until", "")) >= datetime.now(timezone.utc).date().isoformat()]
    if active and not notes:
        lines.append("  Đang ưu tiên: " + "; ".join(f"mảng {b['family']} / dạng {b['kind']} tới {b['until']}"
                                                   f" (video #{b['video_id']})" for b in active))
    return lines


def _median(xs: list) -> float:
    xs = sorted(xs)
    mid = len(xs) // 2
    return 0.0 if not xs else (xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2)


CADENCE_MIN_DAYS = 14
CADENCE_DROP = 0.6


def cadence_lines(rows: list, cfg: dict, now: datetime = None) -> list:
    """So TRƯỚC / SAU khi đổi nhịp đăng (daily.cadence_since — kênh Hàn lên 2 video/ngày từ 25/11/2026, Du chốt
    phương án A): lượt xem trung vị mỗi Short (theo ngày, views_per_day) và lượt xem mỗi ngày của cả nhóm Shorts.
    Luật lùi đã thống nhất: sau ≥ 2 tuần, trung vị mỗi video giảm > 40% mà tổng lượt xem mỗi ngày không tăng ->
    nhắc quay về nhịp cũ (sửa daily.videos_per_day). Chỉ NHẮC, không tự đổi."""
    since = str((cfg.get("daily") or {}).get("cadence_since") or "")
    if not since:
        return []
    now = now or datetime.now(timezone.utc)
    shorts = [r for r in rows if r.get("script_id") and r.get("views") is not None and r.get("published_at")]
    before = [r for r in shorts if str(r["published_at"])[:10] < since]
    after = [r for r in shorts if str(r["published_at"])[:10] >= since]
    if not before or not after:
        return []

    def stats(group):
        days = {str(r["published_at"])[:10] for r in group}
        first = datetime.fromisoformat(min(days)).date()
        last = datetime.fromisoformat(max(days)).date()
        span = (last - first).days + 1
        return _median([views_per_day(r) for r in group]), sum(views_per_day(r) for r in group) / span
    (mb, tb), (ma, ta) = stats(before), stats(after)
    f = lambda x: f"{x:.0f}"
    want = int((cfg.get("daily") or {}).get("videos_per_day", 1))
    lines = [f"  Nhịp đăng ({want} video/ngày từ {since}): trước {len(before)} Shorts — trung vị {f(mb)} lượt xem/ngày"
             f" mỗi video, cả nhóm {f(tb)}/ngày; sau {len(after)} Shorts — trung vị {f(ma)}, cả nhóm {f(ta)}/ngày"]
    elapsed = (now.date() - datetime.fromisoformat(since).date()).days
    if elapsed < CADENCE_MIN_DAYS:
        lines.append(f"  (mới {elapsed} ngày — đủ {CADENCE_MIN_DAYS} ngày mới xét luật lùi)")
    elif mb > 0 and ma < CADENCE_DROP * mb and ta <= tb:
        lines.append(f"  ⚠️ Luật lùi: trung vị mỗi video giảm {100 * (1 - ma / mb):.0f}% mà tổng lượt xem mỗi ngày không"
                     " tăng — nên quay về nhịp cũ (sửa daily.videos_per_day trong file cấu hình kênh).")
    else:
        lines.append("  ✅ Nhịp mới chưa làm giảm hiệu quả quá ngưỡng (giảm > 40% mỗi video mà tổng không tăng)")
    return lines


def update(con, cfg: dict, rows: list, now: datetime = None, token: str = None) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật. Trả về các dòng báo cáo."""
    now = now or datetime.now(timezone.utc)
    snap = {}
    if token:
        try:
            snap = snapshot(token, now) or {}
        except Exception as exc:
            log.warning("Không đo được cả kênh: %s", exc)
    if snap:
        data = _data()
        hist = [h for h in data.get("history") or [] if h.get("date") != snap["date"]]
        data["history"] = (hist + [snap])[-26:]
        data["latest"] = snap
        _save(data)
    notes = apply_breakouts(con, find_breakouts(rows), now)
    return report_lines(snap, rows, notes, cfg) + cadence_lines(rows, cfg, now)


def status_text(cfg: dict = None) -> str:
    """Tình trạng kênh lần đo gần nhất (Telegram /kenh)."""
    data = _data()
    snap = data.get("latest") or {}
    if not snap:
        return ("📈 Chưa có lần đo cả kênh nào — agent Tăng trưởng đo trong lượt Phân tích mỗi Chủ nhật"
                " (21:00 giờ Hàn), kết quả nằm trong báo cáo tuần.")
    lines = report_lines(snap, [], [], cfg or {})[1:]
    lines.insert(0, f"📈 Lần đo gần nhất: {snap['date']} (agent Tăng trưởng đo mỗi Chủ nhật)")
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from .main import load_config
    print(status_text(load_config()))


if __name__ == "__main__":
    main()
