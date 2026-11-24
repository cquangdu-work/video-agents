"""Agent HỌC KÊNH LỚN (20/11/2026) — mỗi Chủ nhật học từ các kênh LỚN cùng ngách (so sánh số liệu các nước;
tiếng Việt / Hàn / Anh): họ đăng gì, video nào đột biến, đột biến nhờ đâu. Học CẤU TRÚC, KHÔNG chép.

1. TÌM kênh lớn: tự tìm bằng YouTube Data API (Shorts nhiều lượt xem nhất 6 tháng theo từ khoá ngách, giữ
   kênh ≥ big_channels.min_subs người đăng ký) + kênh Du thêm (/kenhlon them @tên). Danh sách giữ
   `rediscover_days` ngày rồi mới tìm lại (mỗi lần tìm tốn 100 đơn vị quota).
2. QUÉT mỗi kênh: ~50 video gần nhất -> Shorts -> trung vị lượt xem, video ĐỘT BIẾN (≥ outlier_ratio ×
   trung vị), nhịp đăng mỗi tuần, độ dài, đặc điểm tiêu đề (có số? câu hỏi? so sánh?).
3. XEM video đột biến (Gemini đọc video YouTube công khai — tính năng chính thức của Gemini API, vài video
   mỗi tuần): câu mở đầu, kiểu mở đầu, giây đầu có gì, số lần đổi cảnh, chữ trên màn hình, cách kết. Model
   chỉ MÔ TẢ theo khuôn cố định; CODE tổng hợp thành "sổ tay" — model không tự kết luận.
4. DÙNG: Biên kịch đọc sổ tay (kiểu mở đầu, nhịp, độ dài của video đột biến); agent Đăng bài đọc đặc điểm
   tiêu đề; chủ đề đột biến khớp danh mục chỉ số -> hàng đợi chủ đề (src/topics.py); nhịp đổi cảnh của kênh
   lớn so với khung đang thử -> báo cáo tuần (Du chỉnh bằng /nhip nếu muốn).
5. CHỐNG CHÉP: tiêu đề của kênh mình quá giống tiêu đề một video kênh lớn -> agent Đăng bài phải viết lại
   (YouTube không trả tiền cho nội dung sao chép / lặp lại).

    python -m src.analysis.big_channels            # một lượt (agent Phân tích gọi mỗi Chủ nhật)
    python -m src.analysis.big_channels --show     # in sổ tay hiện có
"""
import argparse
import json
import logging
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

import requests

from .. import lang
from . import learned as store

log = logging.getLogger("big_channels")

API = "https://www.googleapis.com/youtube/v3"
HOOK_TYPES = {"so_sanh": "đối lập / so sánh con số", "cau_hoi": "câu hỏi", "thu_hang": "thứ hạng / kỷ lục",
              "su_that": "sự thật bất ngờ", "moc_thoi_gian": "mốc thời gian", "khac": "khác"}
ENDINGS = {"quay_lai_dau": "quay lại câu mở đầu", "cau_hoi": "hỏi người xem", "keu_goi": "kêu gọi theo dõi",
           "khac": "khác"}
COPY_LIMIT = 0.5          # độ giống từ khoá (Jaccard) của tiêu đề với tiêu đề kênh lớn từ mức này là chép
# Kênh ĐÚNG NGÁCH: phần lớn tiêu đề Shorts gần đây nói chuyện SỐ LIỆU / QUỐC GIA / XẾP HẠNG. Chỉ dùng từ đặc
# trưng — thử thật 20/11: chữ "vs" cho lọt kênh nấu ăn ("$1 vs $100,000 Knife") và tài chính cá nhân ("Cost vs
# Price"); tên kênh trong tiêu đề ("| The Economist") khớp "econom" -> bỏ tên kênh trước khi xét.
NICHE = re.compile(r"population|\bgdp\b|econom|per capita|\brank(ing|ed|s)?\b|richest|poorest|statistic|\bdata\b|"
                   r"\bmaps?\b|countr|\bnations?\b|dân số|kinh tế|xếp hạng|giàu nhất|nghèo nhất|quốc gia|các nước|"
                   r"bản đồ|số liệu|인구|경제|순위|국가|나라|지도|통계", re.I)
MIN_NICHE = 0.3
# Kênh Hàn chỉ học từ kênh lớn đăng tiêu đề TIẾNG HÀN (24/11/2026: lượt đầu giữ HistoryBalls, King Animations — kênh
# hoạt hình tiếng Anh lọt bộ lọc ngách nhờ chữ "countries", "maps"; sổ tay còn câu rác tiếng Anh, Biên kịch đọc vào)
HANGUL = re.compile(r"[가-힣]")
MIN_KOREAN = 0.5
DEFAULTS = {"min_subs": 300_000, "max_channels": 12, "rediscover_days": 28, "outlier_ratio": 3.0,
            "watch_per_week": 4, "months_back": 6, "queries": [], "seed_channels": []}


def _cfg(cfg: dict) -> dict:
    return {**DEFAULTS, **((cfg or {}).get("big_channels") or {})}


def _get(endpoint: str, **params) -> dict:
    params["key"] = os.getenv("YOUTUBE_API_KEY")
    if endpoint == "search":            # 100 đơn vị/lần, hạn mức dùng chung hai kênh (src/publish/yt_quota.py)
        from ..publish import yt_quota
        yt_quota.spend("search")
    r = requests.get(f"{API}/{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _data() -> dict:
    try:
        d = store.load_learned()
    except Exception as exc:
        log.warning("Học kênh lớn: không đọc được learned.yaml (%s)", exc)
        return {}
    b = d.get("big_channels") if isinstance(d, dict) else None
    return b if isinstance(b, dict) else {}


def _save(data: dict) -> None:
    d = store.load_learned()            # file hỏng thì báo lỗi, không ghi đè mất những thứ đã học
    d["big_channels"] = data
    store.save_learned(d)


def _seconds(iso: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return 0 if not m else sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1)))


# ------------------------------------------------------------- 1. tìm kênh lớn
def channel_info(ids: list, get=None) -> list:
    get = get or _get
    out = []
    for i in range(0, len(ids), 50):
        res = get("channels", id=",".join(ids[i:i + 50]), part="statistics,contentDetails,snippet")
        for ch in res.get("items", []):
            out.append({"id": ch["id"], "title": ch["snippet"]["title"],
                        "subs": int(ch["statistics"].get("subscriberCount", 0)),
                        "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"],
                        "country": ch["snippet"].get("country", "")})
    return out


def discover(cfg: dict, now: datetime = None, get=None) -> list:
    """Kênh lớn cùng ngách: từ khoá -> Shorts nhiều lượt xem nhất -> kênh của chúng ≥ min_subs."""
    get = get or _get
    c = _cfg(cfg)
    after = ((now or datetime.now(timezone.utc)) - timedelta(days=30 * c["months_back"])).isoformat(timespec="seconds")
    hits, langs = {}, {}
    for q in c["queries"]:
        try:
            res = get("search", q=q["q"], part="snippet", type="video", videoDuration="short", order="viewCount",
                      publishedAfter=after, maxResults=25, relevanceLanguage=q.get("lang", "en"))
        except Exception as exc:
            log.warning("Tìm '%s' lỗi: %s", q["q"], exc)
            continue
        for it in res.get("items", []):
            cid = it["snippet"]["channelId"]
            hits[cid] = hits.get(cid, 0) + 1
            langs.setdefault(cid, q.get("lang", "en"))
    seeds = [s for s in c["seed_channels"] if isinstance(s, str)]
    found = [ch for ch in channel_info(list(dict.fromkeys(list(hits) + seeds)), get)
             if ch["subs"] >= c["min_subs"] or ch["id"] in seeds]
    for ch in found:
        ch["lang"] = langs.get(ch["id"], "")
        ch["seed"] = ch["id"] in seeds          # kênh chọn sẵn trong cấu hình: không qua bộ lọc ngách / tiếng Hàn
    return sorted(found, key=lambda ch: -ch["subs"])[: c["max_channels"]]


# ------------------------------------------------------------- 2. quét kênh
def title_features(title: str) -> dict:
    t = str(title or "").lower()
    return {"number": bool(re.search(r"\d", t)), "question": "?" in t,
            "compare": bool(re.search(r"\bvs\.?\b|versus|so với|so sánh|compar|비교|대\b", t))}


def scan_channel(ch: dict, ratio: float, get=None, now: datetime = None) -> dict:
    """Shorts gần đây của một kênh: trung vị, video đột biến, nhịp đăng, độ dài."""
    get = get or _get
    res = get("playlistItems", playlistId=ch["uploads"], part="contentDetails", maxResults=50)
    vids = [v["contentDetails"]["videoId"] for v in res.get("items", [])]
    if not vids:
        return {}
    res = get("videos", id=",".join(vids), part="statistics,contentDetails,snippet")
    shorts = []
    for v in res.get("items", []):
        secs = _seconds(v["contentDetails"].get("duration"))
        if 0 < secs <= 180:
            shorts.append({"id": v["id"], "title": v["snippet"]["title"], "seconds": secs,
                           "views": int(v["statistics"].get("viewCount", 0)),
                           "published": v["snippet"]["publishedAt"], "channel": ch["title"]})
    if len(shorts) < 6:                          # quá ít Shorts: trung vị không tin được
        return {}
    med = statistics.median(s["views"] for s in shorts)
    now = now or datetime.now(timezone.utc)
    recent = [s for s in shorts if s["published"] >= (now - timedelta(days=28)).isoformat()]
    outliers = [dict(s, ratio=round(s["views"] / med, 1), **title_features(s["title"])) for s in shorts
                if med > 0 and s["views"] >= ratio * med]
    return {"channel": ch["title"], "id": ch["id"], "subs": ch["subs"], "shorts": len(shorts),
            "median_views": int(med), "median_seconds": statistics.median(s["seconds"] for s in shorts),
            "per_week": round(len(recent) / 4, 1),
            "niche": round(sum(1 for s in shorts
                               if NICHE.search(s["title"].replace(ch["title"], " "))) / len(shorts), 2),
            "korean": round(sum(1 for s in shorts if HANGUL.search(s["title"])) / len(shorts), 2),
            "outliers": sorted(outliers, key=lambda o: -o["ratio"])}


# ------------------------------------------------------------- 3. xem video đột biến
WATCH_PROMPT = """Đây là một video ngắn rất nhiều lượt xem của một kênh lớn về so sánh số liệu. MÔ TẢ đúng những gì
có trong video, không đánh giá. Trả JSON:
{"first_line": "<câu nói / chữ đầu tiên, NGUYÊN VĂN, giữ ngôn ngữ gốc>",
 "hook_type": "so_sanh|cau_hoi|thu_hang|su_that|moc_thoi_gian|khac",
 "first_second": "<giây đầu tiên trên hình có gì, ngắn>",
 "cuts": <số lần đổi cảnh / đổi hình cả video, số nguyên>,
 "on_screen_text": true|false,
 "ending": "quay_lai_dau|cau_hoi|keu_goi|khac",
 "topic": "<chủ đề, vài từ tiếng Việt>"}"""


def watch(video_id: str, seconds: int, post=None) -> dict:
    """Gemini xem một video YouTube CÔNG KHAI (tính năng chính thức của Gemini API). Kết quả bị ép khuôn và
    code kiểm lại; lỗi / sai khuôn -> {} (bỏ video đó)."""
    model = os.getenv("MODEL", "gemini/gemini-3.5-flash-lite").split("/")[-1]
    post = post or (lambda url, **kw: requests.post(url, **kw))
    body = {"contents": [{"parts": [{"file_data": {"file_uri": f"https://www.youtube.com/watch?v={video_id}"}},
                                    {"text": WATCH_PROMPT}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    try:
        r = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 params={"key": os.getenv("GEMINI_API_KEY")}, json=body, timeout=240)
        r.raise_for_status()
        d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as exc:
        log.info("Không xem được video %s: %s", video_id, str(exc)[:150])
        return {}
    if isinstance(d, list):
        d = d[0] if d and isinstance(d[0], dict) else {}
    try:
        cuts = int(d.get("cuts"))
    except (TypeError, ValueError):
        cuts = None
    if cuts is not None and not 0 < cuts <= max(4, seconds * 2):     # quá vô lý thì không tin con số này
        cuts = None
    return {"first_line": str(d.get("first_line") or "")[:200],
            "hook_type": d.get("hook_type") if d.get("hook_type") in HOOK_TYPES else "khac",
            "first_second": str(d.get("first_second") or "")[:160], "cuts": cuts,
            "on_screen_text": d.get("on_screen_text") is True,
            "ending": d.get("ending") if d.get("ending") in ENDINGS else "khac",
            "topic": str(d.get("topic") or "")[:80]}


# ------------------------------------------------------------- 4. sổ tay (CODE tổng hợp)
def playbook(scans: list, watched: dict) -> dict:
    """Tổng hợp bằng code: kiểu mở đầu / cách kết của video đột biến đã xem, nhịp đổi cảnh, độ dài, đặc
    điểm tiêu đề, nhịp đăng. Không có số liệu thì bỏ trống phần đó."""
    outs = [o for s in scans for o in s.get("outliers", [])]
    seen = [dict(w, seconds=w.get("seconds") or next((o["seconds"] for o in outs if o["id"] == vid), None))
            for vid, w in watched.items()]
    pb = {"channels": len(scans), "outliers": len(outs), "watched": len(seen)}
    if outs:
        pb["outlier_seconds"] = statistics.median(o["seconds"] for o in outs)
        pb["channel_seconds"] = statistics.median(s["median_seconds"] for s in scans)
        pb["titles"] = {k: round(100 * sum(o[k] for o in outs) / len(outs)) for k in ("number", "question", "compare")}
    pb["per_week"] = statistics.median(s["per_week"] for s in scans) if scans else 0
    if seen:
        def count(key, values):
            got = {v: sum(1 for w in seen if w.get(key) == v) for v in values}
            return dict(sorted(((k, n) for k, n in got.items() if n), key=lambda kv: -kv[1]))
        pb["hook_types"] = count("hook_type", HOOK_TYPES)
        pb["endings"] = count("ending", ENDINGS)
        pace = [w["seconds"] / (w["cuts"] + 1) for w in seen if w.get("cuts") and w.get("seconds")]
        if pace:
            pb["seconds_per_shot"] = round(statistics.median(pace), 1)
        pb["on_screen_text_pct"] = round(100 * sum(1 for w in seen if w.get("on_screen_text")) / len(seen))
        pb["examples"] = [w["first_line"] for w in seen if w.get("first_line")][-3:]
    return pb


def _f(x) -> str:
    return f"{x:g}".replace(".", ",")


def writer_block(data: dict = None) -> str:
    """Cho Biên kịch: video đột biến của kênh lớn cùng ngách được làm thế nào — CẤU TRÚC, không phải chữ."""
    pb = (_data() if data is None else data).get("playbook") or {}
    if not pb.get("watched"):
        return ""
    hooks = ", ".join(f"{HOOK_TYPES[k]} {n}" for k, n in (pb.get("hook_types") or {}).items())
    ends = ", ".join(f"{ENDINGS[k]} {n}" for k, n in (pb.get("endings") or {}).items())
    lines = [f"\nKÊNH LỚN CÙNG NGÁCH ({pb['channels']} kênh, đã xem {pb['watched']} video đột biến):",
             f"- Cách mở đầu: {hooks}." if hooks else "", f"- Cách kết: {ends}." if ends else "",
             (f"- Đổi hình ~{_f(pb['seconds_per_shot'])} giây/lần; video đột biến dài ~{_f(pb['outlier_seconds'])} giây."
              if pb.get("seconds_per_shot") and pb.get("outlier_seconds") else "")]
    if pb.get("examples"):
        lines.append("- Câu mở đầu thật (tiếng gốc) để thấy CẤU TRÚC: " + " | ".join(f"“{e}”" for e in pb["examples"]))
    lines.append("Học CẤU TRÚC và nhịp; KHÔNG dịch / chép câu chữ hay tiêu đề của họ (YouTube không trả tiền cho"
                 " nội dung sao chép), số liệu vẫn chỉ lấy từ nguồn của mình.")
    return "\n".join(x for x in lines if x) + "\n"


def metadata_block(data: dict = None) -> str:
    """Cho agent Đăng bài: tiêu đề video đột biến của kênh lớn có đặc điểm gì."""
    pb = (_data() if data is None else data).get("playbook") or {}
    t = pb.get("titles")
    if not t or pb.get("outliers", 0) < 5:
        return ""
    return (f"\nTiêu đề {pb['outliers']} video đột biến của kênh lớn cùng ngách: {t['number']}% có con số,"
            f" {t['compare']}% có so sánh, {t['question']}% là câu hỏi — tham khảo đặc điểm, KHÔNG chép tiêu đề.")


def too_similar(title: str, data: dict = None) -> str:
    """Tiêu đề kênh lớn mà `title` gần như chép lại (độ giống từ khoá ≥ COPY_LIMIT), không có thì ""."""
    from ..utils import similarity
    for other in (_data() if data is None else data).get("titles") or []:
        if similarity(title, other) >= COPY_LIMIT:
            return other
    return ""


# ------------------------------------------------------------- chạy mỗi tuần
def update(con, cfg: dict, now: datetime = None, get=None, post=None) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật. Trả về các dòng báo cáo."""
    from .. import topics
    c = _cfg(cfg)
    now = now or datetime.now(timezone.utc)
    data = _data()
    stale = (not data.get("channels") or str(data.get("discovered_at", ""))
             < (now - timedelta(days=c["rediscover_days"])).isoformat())
    manual = [ch for ch in data.get("channels") or [] if ch.get("manual")]
    if stale:          # tìm lại: lấy dư ứng viên, quét xong mới lọc đúng ngách
        found = discover({**cfg, "big_channels": {**c, "max_channels": 2 * c["max_channels"]}}, now, get)
        candidates = manual + [ch for ch in found if ch["id"] not in {m["id"] for m in manual}]
    else:
        candidates = data.get("channels") or []
    scans, kept = [], []
    for ch in candidates:
        try:
            s = scan_channel(ch, c["outlier_ratio"], get, now)
        except Exception as exc:
            log.warning("Quét kênh %s lỗi: %s", ch.get("title"), exc)
            continue
        if not s:
            continue
        chosen = ch.get("manual") or ch.get("seed")
        if s["niche"] < MIN_NICHE and not chosen:
            log.info("Bỏ kênh %s: chỉ %d%% tiêu đề đúng ngách", ch.get("title"), 100 * s["niche"])
            continue
        if lang.code() == "ko" and s.get("korean", 1) < MIN_KOREAN and not chosen:
            log.info("Bỏ kênh %s: chỉ %d%% tiêu đề tiếng Hàn", ch.get("title"), 100 * s.get("korean", 0))
            continue
        if len(kept) < c["max_channels"] or chosen:
            scans.append(s)
            kept.append(ch)
    data["channels"] = kept
    if stale:
        data["discovered_at"] = now.isoformat(timespec="seconds")
    # sổ tay chỉ dựa trên video của kênh CÒN được giữ (kênh bị loại vì lạc ngách thì quên video của nó)
    kept_titles = {s["channel"] for s in scans}
    watched = {vid: w for vid, w in (data.get("watched") or {}).items() if w.get("channel") in kept_titles}
    seen_titles = {w.get("title") for w in watched.values()}
    todo = []
    for o in (o for s in scans for o in s["outliers"]):
        if o["id"] not in watched and o["title"] not in seen_titles:     # bản đăng lại cùng tiêu đề: xem 1 lần
            seen_titles.add(o["title"])
            todo.append(o)
    fresh = []
    for o in sorted(todo, key=lambda o: -o["ratio"])[: c["watch_per_week"]]:
        w = watch(o["id"], o["seconds"], post)
        if w:
            watched[o["id"]] = dict(w, channel=o["channel"], title=o["title"], views=o["views"],
                                    ratio=o["ratio"], seconds=o["seconds"])
            fresh.append(watched[o["id"]])
    data["watched"] = dict(list(watched.items())[-60:])           # nhớ 60 video gần nhất
    data["playbook"] = playbook(scans, data["watched"])
    data["titles"] = [o["title"] for s in scans for o in s["outliers"]][:200]
    data["updated_at"] = now.isoformat(timespec="seconds")
    _save(data)
    queued = []
    for w in fresh:                       # chủ đề đột biến khớp nguồn số liệu của kênh -> làm sớm
        # khớp phải phủ phần lớn ý của chủ đề (thử thật 20/11: "quyền lợi người tiêu dùng" khớp nhầm
        # "năng lượng tiêu thụ bình quân mỗi người" chỉ vì trùng vài chữ)
        keys = topics.match(cfg, w.get("topic", ""), min_cover=0.6)
        if keys and topics.request(con, keys[0], w["topic"], "big_channel",
                                   f"{w['channel']}: {w['title']}") == "pending":
            queued.append(w["topic"])
    return report_lines(data, scans, queued)


def report_lines(data: dict, scans: list, queued: list) -> list:
    pb = data.get("playbook") or {}
    if not scans and not pb.get("channels"):
        return ["", "🏆 Học từ kênh lớn: chưa tìm được kênh lớn cùng ngách (xem big_channels trong config)."]
    lines = ["", f"🏆 Học từ kênh lớn ({pb.get('channels', 0)} kênh, {pb.get('outliers', 0)} video đột biến,"
                 f" đã xem {pb.get('watched', 0)}):"]
    if scans:
        lines.append("  Kênh: " + ", ".join(f"{s['channel']} ({s['subs'] // 1000:,}k)".replace(",", ".")
                                            for s in sorted(scans, key=lambda s: -s["subs"])[:6]))
    if pb.get("hook_types"):
        lines.append("  Video đột biến mở bằng: " + ", ".join(f"{HOOK_TYPES[k]} {n}" for k, n in pb["hook_types"].items()))
    if pb.get("seconds_per_shot"):
        lines.append(f"  Nhịp: đổi hình ~{_f(pb['seconds_per_shot'])} giây/lần; video đột biến dài"
                     f" ~{_f(pb.get('outlier_seconds', 0))} giây, kênh đăng ~{_f(pb.get('per_week', 0))} video/tuần"
                     " (so với khung nhịp kênh mình đang thử: /kieu)")
    if pb.get("titles"):
        t = pb["titles"]
        lines.append(f"  Tiêu đề đột biến: {t['number']}% có số, {t['compare']}% so sánh, {t['question']}% câu hỏi")
    if queued:
        lines.append("  Chủ đề đột biến khớp nguồn số liệu của kênh → đã xếp hàng: " + ", ".join(queued))
    lines.append("  (đã đưa vào lời dặn Biên kịch và agent Đăng bài — học cấu trúc; tiêu đề giống kênh lớn bị trả lại)")
    return lines


def add_channel(ref: str, get=None) -> dict:
    """Du thêm một kênh muốn học: @tên, link youtube.com/@tên, link /channel/UC..., hoặc id UC..."""
    get = get or _get
    ref = str(ref or "").strip()
    m = re.search(r"(UC[\w-]{22})", ref)
    handle = re.search(r"@([\w.-]+)", ref)
    if m:
        res = get("channels", id=m.group(1), part="statistics,contentDetails,snippet")
    elif handle:
        res = get("channels", forHandle="@" + handle.group(1), part="statistics,contentDetails,snippet")
    else:
        raise ValueError("gửi @tên kênh hoặc link kênh YouTube")
    items = res.get("items") or []
    if not items:
        raise ValueError("không tìm thấy kênh này")
    ch = items[0]
    info = {"id": ch["id"], "title": ch["snippet"]["title"], "subs": int(ch["statistics"].get("subscriberCount", 0)),
            "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"], "manual": True}
    data = _data()
    data["channels"] = [info] + [c for c in data.get("channels") or [] if c.get("id") != info["id"]]
    _save(data)
    return info


def status_text() -> str:
    data = _data()
    chans = data.get("channels") or []
    if not chans:
        return ("🏆 Chưa có kênh lớn nào — agent tự tìm trong lượt Phân tích Chủ nhật; thêm tay:"
                " /kenhlon them @tên")
    lines = [f"🏆 Đang học từ {len(chans)} kênh: " + ", ".join(c["title"] for c in chans[:10])]
    lines += report_lines(data, [], [])[2:]
    lines.append("Thêm kênh: /kenhlon them @tên (hoặc link kênh)")
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Agent Học kênh lớn")
    ap.add_argument("--show", action="store_true", help="Chỉ in sổ tay hiện có")
    args = ap.parse_args()
    if args.show:
        print(status_text())
        print(writer_block())
        return
    from .. import db
    from ..main import load_config
    con = db.connect()
    try:
        print("\n".join(update(con, load_config())))
    finally:
        con.close()


if __name__ == "__main__":
    main()
