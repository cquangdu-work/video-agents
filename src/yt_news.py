"""Agent TIN YOUTUBE (20/11/2026) — mỗi Chủ nhật đọc kênh tin CHÍNH THỨC của YouTube (YouTube Official
Blog, Creator Insider, YouTube Creators — RSS, không tốn quota) để biết YouTube vừa đổi gì: luật kiếm tiền,
chính sách nội dung AI / nội dung lặp lại, Shorts, API, Analytics...

Model nhỏ chỉ LỌC và TÓM TẮT (ép khuôn JSON, code soát lại); nó không được đổi luật nào của hệ thống —
luật chính sách trong CLAUDE.md / config do Du quyết (dạy hệ thống bằng /hoc nếu cần). Tin ảnh hưởng LỚN
(model chấm "cao") được báo Du ngay qua Telegram; còn lại vào báo cáo tuần.

    python -m src.yt_news --dry-run    # đọc + lọc + in ra, không ghi, không gửi
"""
import argparse
import logging
import re
import sys
from datetime import datetime, timedelta, timezone

from . import db
from . import telegram_bot as tg

log = logging.getLogger("yt_news")

FEEDS = [("YouTube Official Blog", "https://blog.youtube/rss/"),
         ("Creator Insider", "https://www.youtube.com/feeds/videos.xml?channel_id=UCGg-UqjRgzhYDPJMr-9HXCg"),
         ("YouTube Creators", "https://www.youtube.com/feeds/videos.xml?channel_id=UCkRfArvrzheW2E7b6SVT7vQ")]
FRESH_DAYS = 30          # tin cũ hơn chừng này (lần chạy đầu có cả trăm tin) chỉ đánh dấu đã đọc
MAX_PER_RUN = 25
IMPACTS = ("cao", "vua", "thap")
# Mức "cao" (báo Du ngay) chỉ giữ khi CHÍNH bài gốc nói về những chuyện này — model nhỏ hay báo động nhầm
# (thử thật 20/11: chấm "cao" cho tin YouTube tính thêm lượt xem chung trên TV vào số lượt xem công khai)
HIGH_IMPACT = re.compile(r"monetiz|partner program|\bypp\b|polic|guideline|revenue|strike|copyright|synthetic|"
                         r"altered|\bai\b|artificial intelligence|disclos|inauthentic|reused|repetitive|"
                         r"mass[- ]produced|\bapi\b|quota|terms of service|community guidelines", re.I)
PROFILE = ("kênh YouTube Shorts tiếng Việt giải thích SỐ LIỆU bằng biểu đồ / bản đồ dựng bằng code, giọng đọc"
           " AI, phụ đề tự động, đăng qua YouTube Data API theo lịch, kèm video dài tổng hợp hằng tuần; CHƯA bật"
           " kiếm tiền, đang nhắm điều kiện YouTube Partner Program; chủ kênh duyệt từng video")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", str(html or "")).split())


def fetch_feeds(feeds=None, get=None) -> list:
    """[{id, source, title, summary, link, published}] từ các feed (lỗi feed nào thì bỏ feed đó)."""
    import feedparser
    import requests
    get = get or (lambda url: requests.get(url, timeout=30, headers={"User-Agent": "video-agents/1.0"}).content)
    out = []
    for name, url in feeds or FEEDS:
        try:
            parsed = feedparser.parse(get(url))
        except Exception as exc:
            log.warning("Không đọc được %s: %s", name, exc)
            continue
        for e in parsed.entries:
            link = e.get("link") or e.get("id")
            if not link:
                continue
            when = e.get("published_parsed") or e.get("updated_parsed")
            out.append({"id": link, "source": name, "title": str(e.get("title") or "").strip(),
                        "summary": _text(e.get("summary") or e.get("media_description") or "")[:600],
                        "link": link,
                        "published": (datetime(*when[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
                                      if when else "")})
    return out


def classify(items: list, run=None) -> list:
    """[{relevant, impact, summary, action}] cùng thứ tự `items`. Model chỉ lọc + tóm tắt."""
    from .utils import extract_json
    if not items:
        return []
    if run is None:
        from .crew import _run_single_task as run
    listing = "\n".join(f"{k + 1}. [{it['source']}] {it['title']} — {it['summary'][:400]}" for k, it in enumerate(items))
    answer = run(
        role="Người theo dõi thay đổi của YouTube cho một kênh nhỏ",
        goal="Chỉ báo những thay đổi thật sự ảnh hưởng tới kênh, tóm tắt đúng, không suy diễn",
        description=f"""Kênh: {PROFILE}.

Dưới đây là các bài / video mới từ kênh tin CHÍNH THỨC của YouTube. Với TỪNG mục, cho biết:
- "relevant": true nếu nó ảnh hưởng tới kênh trên (Shorts: phân phối, thời lượng, kiếm tiền; điều kiện YPP;
  chính sách nội dung AI, nội dung lặp lại / theo mẫu; nhạc, bản quyền; API tải lên, Analytics; tiêu đề, mô
  tả, phụ đề, bình luận). Tính năng livestream, game, quảng cáo cho nhà quảng cáo... -> false.
- "impact": "cao" (phải đổi cách làm hoặc ảnh hưởng kiếm tiền / bị phạt), "vua" (nên biết, có thể tận
  dụng), "thap".
- "summary": 1-2 câu TIẾNG VIỆT nói đúng điều bài viết nói, không thêm thắt.
- "action": việc kênh nên làm (ngắn), không có thì "".

{listing}""",
        expected_output='JSON array: [{"i": 1, "relevant": true, "impact": "cao|vua|thap", "summary": "...", "action": "..."}]')
    try:
        data = extract_json(answer)
    except ValueError:
        data = []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    out = [{"relevant": False, "impact": "thap", "summary": "", "action": ""} for _ in items]
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            k = int(d.get("i")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= k < len(items) and str(d.get("summary") or "").strip():
            impact = d.get("impact") if d.get("impact") in IMPACTS else "thap"
            if impact == "cao" and not HIGH_IMPACT.search(f"{items[k]['title']} {items[k]['summary']}"):
                impact = "vua"                     # code soát lại: bài gốc không nói chuyện ảnh hưởng lớn
            out[k] = {"relevant": d.get("relevant") is True or str(d.get("relevant")).lower() == "true",
                      "impact": impact,
                      "summary": str(d["summary"]).strip()[:400], "action": str(d.get("action") or "").strip()[:200]}
    return out


def run(con, now: datetime = None, dry_run: bool = False, feeds=None, get=None, llm=None, send=None) -> list:
    """Một lượt: tin mới -> lọc -> lưu -> báo Du tin ảnh hưởng lớn. Trả về các tin LIÊN QUAN mới."""
    now = now or datetime.now(timezone.utc)
    fresh_since = (now - timedelta(days=FRESH_DAYS)).isoformat(timespec="seconds")
    new = [it for it in fetch_feeds(feeds, get)
           if not con.execute("SELECT 1 FROM yt_news WHERE id = ?", (it["id"],)).fetchone()]
    fresh = [it for it in new if it["published"] >= fresh_since][:MAX_PER_RUN]
    stale = [it for it in new if it not in fresh]
    for it, v in zip(fresh, classify(fresh, llm)):
        it.update(v)
    relevant = [it for it in fresh if it.get("relevant")]
    if dry_run:
        for it in relevant:
            print(f"[{it['impact']}] {it['source']}: {it['title']}\n  {it['summary']}\n  → {it['action']}\n  {it['link']}")
        print(f"({len(fresh)} tin mới trong {FRESH_DAYS} ngày, {len(relevant)} liên quan; {len(stale)} tin cũ bỏ qua)")
        return relevant
    for it in fresh + stale:
        con.execute("INSERT OR IGNORE INTO yt_news (id, source, title, link, published, relevant, impact, summary,"
                    " action, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (it["id"], it["source"], it["title"], it["link"], it["published"], int(bool(it.get("relevant"))),
                     it.get("impact", "thap"), it.get("summary", ""), it.get("action", ""), _now()))
    con.commit()
    urgent = [it for it in relevant if it["impact"] == "cao"]
    if urgent:
        (send or tg.send_message)("📰 YouTube vừa thay đổi điều có thể ảnh hưởng tới kênh (agent Tin YouTube):\n\n"
                                  + "\n\n".join(f"• {it['title']}\n  {it['summary']}"
                                                + (f"\n  → Nên làm: {it['action']}" if it["action"] else "")
                                                + f"\n  {it['link']}" for it in urgent)
                                  + "\n\nLuật của hệ thống KHÔNG tự đổi — Du quyết (dạy bằng /hoc nếu cần).")
    return relevant


def report_lines(con, now: datetime = None) -> list:
    """Mục "📰 YouTube có gì mới" của báo cáo tuần: tin liên quan đọc trong 7 ngày qua."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat(timespec="seconds")
    rows = con.execute("SELECT * FROM yt_news WHERE relevant = 1 AND seen_at >= ? ORDER BY"
                       " CASE impact WHEN 'cao' THEN 0 WHEN 'vua' THEN 1 ELSE 2 END, published DESC LIMIT 6",
                       (since,)).fetchall()
    if not rows:
        return []
    mark = {"cao": "❗", "vua": "•", "thap": "·"}
    return ["", "📰 YouTube có gì mới liên quan tới kênh (agent Tin YouTube):"] + [
        f"  {mark.get(r['impact'], '•')} {r['title']}: {r['summary']}" + (f" → {r['action']}" if r["action"] else "")
        + f" {r['link']}" for r in rows]


def latest_lines(con, n: int = 3) -> list:
    rows = con.execute("SELECT * FROM yt_news WHERE relevant = 1 ORDER BY published DESC LIMIT ?", (n,)).fetchall()
    return [f"• [{r['impact']}] {r['title']}: {r['summary']} {r['link']}" for r in rows]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Agent Tin YouTube")
    ap.add_argument("--dry-run", action="store_true", help="Không ghi DB, không gửi Telegram")
    args = ap.parse_args()
    con = db.connect()
    try:
        run(con, dry_run=args.dry_run)
    finally:
        con.close()


if __name__ == "__main__":
    main()
