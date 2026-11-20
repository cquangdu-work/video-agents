"""Agent HIỂU YOUTUBE (20/11/2026) — mỗi Chủ nhật đọc YouTube Analytics để biết YouTube đang PHÂN PHỐI
video của kênh thế nào, rồi đưa điều học được vào chỗ dùng được. Chỉ ĐỌC số liệu, không đổi gì trên kênh.

1. NGUỒN LƯỢT XEM: luồng Shorts / tìm kiếm / video đề xuất / trang chủ / bên ngoài... Đo thật 19/11/2026:
   98% lượt xem đến từ luồng Shorts -> YouTube phân phối kênh gần như chỉ bằng cách thử video với người
   lạ trên luồng Shorts: 1-2 giây đầu và tỷ lệ xem hết quyết định video có được đẩy tiếp hay không.
2. TỪ KHOÁ TÌM KIẾM người xem thật sự gõ để ra video của kênh -> chỉ giữ từ ĐÚNG CHỦ ĐỀ (khớp danh mục chỉ
   số của kênh, src/topics.py — đo thật: "gdp việt nam" giữ, "xsmb" bỏ) -> agent Đăng bài dùng trong
   tiêu đề / thẻ (metadata_block).
3. VÒNG ĐỜI VIDEO: bao nhiêu % lượt xem rơi vào 2 ngày đầu, mấy ngày thì đạt 90% -> YouTube "thử" mỗi
   video bao lâu rồi thôi.
4. KÊNH HÀNG XÓM: kênh có video mà YouTube đặt video của mình ngay cạnh (nguồn "video đề xuất") -> thêm
   vào danh sách kênh mà phân tích đối thủ học (src/analysis/competitors.py).
5. NGƯỜI XEM: nước nào; người đăng ký hay người lạ.

    python -m src.yt_insights        # in lần đo gần nhất
"""
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from .analysis import learned as store

log = logging.getLogger("yt_insights")

TRAFFIC = {"SHORTS": "luồng Shorts", "YT_SEARCH": "tìm kiếm YouTube", "RELATED_VIDEO": "video đề xuất",
           "BROWSE": "trang chủ / duyệt", "SUBSCRIBER": "trang người đăng ký", "YT_CHANNEL": "trang kênh",
           "EXT_URL": "ngoài YouTube", "NO_LINK_OTHER": "trực tiếp / khác", "PLAYLIST": "danh sách phát",
           "NOTIFICATION": "thông báo", "HASHTAGS": "trang hashtag", "END_SCREEN": "màn hình kết thúc",
           "YT_OTHER_PAGE": "trang khác của YouTube", "SHORTS_CONTENT_LINKS": "liên kết trong Shorts"}
MAX_LIFECYCLE_VIDEOS = 10


def _data() -> dict:
    try:
        d = store.load_learned()
    except Exception as exc:
        log.warning("Hiểu YouTube: không đọc được learned.yaml (%s)", exc)
        return {}
    p = d.get("platform") if isinstance(d, dict) else None
    return p if isinstance(p, dict) else {}


def _save(platform: dict) -> None:
    d = store.load_learned()            # file hỏng thì báo lỗi, không ghi đè mất những thứ đã học
    d["platform"] = platform
    store.save_learned(d)


def _f(x) -> str:
    """98.6 -> "98,6" (số thập phân kiểu Việt trong câu chữ)."""
    return f"{x:g}".replace(".", ",")


def _pct(part, whole) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _rows(report, token, start, end, metrics, dimensions=None, **extra) -> list:
    """Một báo cáo; lỗi thì [] (đo thật 19/11: chiều subscribedStatus bị Analytics trả lỗi 500)."""
    try:
        return report(token, start, end, metrics, dimensions, **extra)
    except Exception as exc:
        log.info("Analytics %s/%s lỗi (bỏ qua phần này): %s", dimensions, extra.get("filters", ""), str(exc)[:120])
        return []


def relevant_terms(cfg: dict, terms: list) -> list:
    """Từ khoá tìm kiếm ĐÚNG CHỦ ĐỀ kênh: khớp ít nhất một chỉ số trong danh mục (src/topics.py)."""
    from . import topics
    return [t for t in terms if topics.match(cfg, t["term"])]


def lifecycle(daily: list) -> dict:
    """daily: lượt xem từng ngày kể từ ngày đăng (ngày 0 trước) -> % trong 2 ngày đầu, số ngày đạt 90%."""
    total = sum(daily)
    if total <= 0:
        return {}
    acc, day90 = 0, len(daily)
    for k, v in enumerate(daily):
        acc += v
        if acc >= 0.9 * total:
            day90 = k + 1
            break
    return {"views": total, "first2_pct": _pct(sum(daily[:2]), total), "days_to_90": day90}


def _median(xs: list) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def measure(con, cfg: dict, token: str, now: datetime = None, report=None, channels=None, own_channel=None) -> dict:
    """Đo một lượt (28 ngày gần nhất). report/channels: thay được trong test."""
    from .publish import youtube
    report = report or youtube.report_rows
    channels = channels or (lambda ids: youtube.video_channels(ids, token=token))
    today = (now or datetime.now(timezone.utc)).date()
    start, end = (today - timedelta(days=28)).isoformat(), today.isoformat()
    snap = {"date": end}
    traffic = _rows(report, token, start, end, "views", "insightTrafficSourceType", sort="-views")
    total = sum(int(r["views"]) for r in traffic)
    snap["traffic"] = [{"source": r["insightTrafficSourceType"], "views": int(r["views"]),
                        "pct": _pct(int(r["views"]), total)} for r in traffic if int(r["views"]) > 0]
    terms = _rows(report, token, start, end, "views", "insightTrafficSourceDetail",
                  filters="insightTrafficSourceType==YT_SEARCH", sort="-views", maxResults=25)
    snap["search_terms"] = [{"term": str(r["insightTrafficSourceDetail"]), "views": int(r["views"])} for r in terms]
    snap["keywords"] = relevant_terms(cfg, snap["search_terms"])
    countries = _rows(report, token, start, end, "views", "country", sort="-views", maxResults=5)
    ctotal = sum(int(r["views"]) for r in countries) or 1
    snap["countries"] = [{"country": r["country"], "pct": _pct(int(r["views"]), ctotal)} for r in countries]
    subs = _rows(report, token, start, end, "views", "subscribedStatus")
    if subs:
        stotal = sum(int(r["views"]) for r in subs)
        snap["subscribed_pct"] = _pct(sum(int(r["views"]) for r in subs if r["subscribedStatus"] == "SUBSCRIBED"),
                                      stotal)
    # vòng đời: Shorts đăng 7-60 ngày trước, lượt xem từng ngày trong 14 ngày đầu
    rows = con.execute("SELECT youtube_id, published_at FROM videos WHERE status='published' AND youtube_id IS NOT NULL"
                       " AND script_id IS NOT NULL AND published_at <= ? AND published_at >= ? ORDER BY id DESC LIMIT ?",
                       ((today - timedelta(days=7)).isoformat(), (today - timedelta(days=60)).isoformat(),
                        MAX_LIFECYCLE_VIDEOS)).fetchall()
    lives = []
    for r in rows:
        day0 = date.fromisoformat(str(r["published_at"])[:10])
        daily_rows = _rows(report, token, day0.isoformat(), min(today, day0 + timedelta(days=13)).isoformat(),
                           "views", "day", filters=f"video=={r['youtube_id']}", sort="day")
        by_day = {str(x["day"]): int(x["views"]) for x in daily_rows}
        life = lifecycle([by_day.get((day0 + timedelta(days=k)).isoformat(), 0) for k in range(14)])
        if life and life["views"] >= 50:            # quá ít lượt xem thì đường đời không nói gì
            lives.append(life)
    if lives:
        snap["lifecycle"] = {"videos": len(lives), "first2_pct": round(_median([x["first2_pct"] for x in lives]), 1),
                             "days_to_90": _median([x["days_to_90"] for x in lives])}
    # kênh hàng xóm: video mà YouTube đặt video của mình bên cạnh
    related = _rows(report, token, start, end, "views", "insightTrafficSourceDetail",
                    filters="insightTrafficSourceType==RELATED_VIDEO", sort="-views", maxResults=25)
    if related:
        try:
            meta = channels([str(r["insightTrafficSourceDetail"]) for r in related])
        except Exception as exc:
            log.info("Không tra được kênh của video đề xuất: %s", exc)
            meta = {}
        near = {}
        for r in related:
            m = meta.get(str(r["insightTrafficSourceDetail"]))
            if m and m["channel_id"] and m["channel_id"] != own_channel:
                n = near.setdefault(m["channel_id"], {"channel": m["channel"], "views": 0})
                n["views"] += int(r["views"])
        snap["neighbors"] = dict(sorted(near.items(), key=lambda kv: -kv[1]["views"])[:10])
    return snap


def interpret(snap: dict) -> list:
    """Vài câu "YouTube đang làm gì với kênh" — luật cố định, nói đúng mức số liệu cho phép."""
    out = []
    share = {t["source"]: t["pct"] for t in snap.get("traffic") or []}
    if share.get("SHORTS", 0) >= 80:
        out.append(f"YouTube phân phối kênh gần như chỉ qua luồng Shorts ({_f(share['SHORTS'])}%): video được thử với"
                   " người lạ, 1-2 giây đầu và tỷ lệ xem hết quyết định có được đẩy tiếp không — đúng trọng tâm"
                   " hiện tại của Biên kịch và Sản xuất.")
    if share.get("YT_SEARCH", 0) >= 10:
        out.append(f"Tìm kiếm mang tới {_f(share['YT_SEARCH'])}% lượt xem: tiêu đề/thẻ chứa đúng từ khoá người xem gõ"
                   " (agent Đăng bài đã được đưa danh sách).")
    if share.get("RELATED_VIDEO", 0) >= 10:
        out.append(f"YouTube đặt video của kênh cạnh video khác ({_f(share['RELATED_VIDEO'])}% lượt xem): kênh hàng xóm"
                   " được đưa vào phân tích đối thủ.")
    life = snap.get("lifecycle") or {}
    if life:
        if life["first2_pct"] >= 70:
            out.append(f"Mỗi video được YouTube đẩy chủ yếu trong 2 ngày đầu ({_f(life['first2_pct'])}% lượt xem, trung"
                       f" vị {life['videos']} video) rồi gần như dừng: mỗi video chỉ có một lần cơ hội — giữ nhịp đăng"
                       " đều mỗi ngày quan trọng hơn làm lại video cũ.")
        else:
            out.append(f"Video còn được xem lâu sau khi đăng (2 ngày đầu chỉ {_f(life['first2_pct'])}%, đạt 90% sau"
                       f" ~{_f(life['days_to_90'])} ngày): nội dung 'trường tồn' có giá trị.")
    countries = snap.get("countries") or []
    if countries:
        out.append("Người xem: " + ", ".join(f"{c['country']} {_f(c['pct'])}%" for c in countries[:3])
                   + (" — chưa có người xem Hàn Quốc đáng kể: phụ đề/kênh tiếng Hàn chưa cần gấp."
                      if not any(c["country"] == "KR" and c["pct"] >= 5 for c in countries) else ""))
    if snap.get("subscribed_pct") is not None:
        out.append(f"{_f(snap['subscribed_pct'])}% lượt xem từ người đã đăng ký.")
    return out


def report_lines(snap: dict) -> list:
    if not snap:
        return []
    lines = ["", "📡 YouTube phân phối video của kênh thế nào (agent Hiểu YouTube, 28 ngày):"]
    if snap.get("traffic"):
        lines.append("  Nguồn lượt xem: " + " · ".join(f"{TRAFFIC.get(t['source'], t['source'])} {_f(t['pct'])}%"
                                                     for t in snap["traffic"][:5]))
    if snap.get("search_terms"):
        kept = {k["term"] for k in snap.get("keywords") or []}
        lines.append("  Người xem gõ tìm: " + ", ".join(
            f"“{t['term']}”" + ("" if t["term"] in kept else " (lạc đề — bỏ)") for t in snap["search_terms"][:6]))
    lines += [f"  • {x}" for x in interpret(snap)]
    if snap.get("neighbors"):
        lines.append("  Kênh hàng xóm (YouTube đặt cạnh): " + ", ".join(
            n["channel"] for n in list(snap["neighbors"].values())[:5]) + " — đã đưa vào phân tích đối thủ")
    return lines


def update(con, cfg: dict, token: str, now: datetime = None, **kw) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật. Lưu learned.yaml["platform"], trả về các dòng báo cáo."""
    if not token:
        return []
    own = kw.pop("own_channel", None)
    if own is None:
        try:
            from .publish import youtube
            own = youtube.whoami().get("id")
        except Exception:
            own = None
    snap = measure(con, cfg, token, now, own_channel=own, **kw)
    if snap.get("traffic") or snap.get("search_terms"):
        data = _data()
        data["latest"] = snap
        data["history"] = ([h for h in data.get("history") or [] if h.get("date") != snap["date"]]
                           + [{"date": snap["date"], "traffic": snap.get("traffic")}])[-26:]
        _save(data)
    return report_lines(snap)


# ------------------------------------------------- dùng ở chỗ khác
def metadata_block(data: dict = None) -> str:
    """Cho agent Đăng bài (crew.write_metadata): từ khoá ĐÚNG CHỦ ĐỀ người xem thật sự gõ để ra kênh."""
    snap = (_data() if data is None else data).get("latest") or {}
    kws = [k["term"] for k in snap.get("keywords") or []][:8]
    if not kws:
        return ""
    return ("\nTừ khoá người xem THẬT SỰ gõ để tìm ra kênh (YouTube Analytics, đã lọc đúng chủ đề): "
            + ", ".join(kws) + " — nếu video nói đúng chủ đề đó, dùng nguyên cụm trong tiêu đề hoặc thẻ.")


def neighbor_channels(data: dict = None) -> dict:
    """{id kênh: tên} các kênh YouTube đặt cạnh video của kênh — cho phân tích đối thủ."""
    snap = (_data() if data is None else data).get("latest") or {}
    return {cid: n["channel"] for cid, n in (snap.get("neighbors") or {}).items()}


def status_text() -> str:
    snap = _data().get("latest") or {}
    if not snap:
        return "📡 Chưa có lần đo nào — agent Hiểu YouTube đo trong lượt Phân tích mỗi Chủ nhật."
    return "\n".join([f"📡 Lần đo gần nhất: {snap['date']}"] + report_lines(snap)[2:])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(status_text())


if __name__ == "__main__":
    main()
