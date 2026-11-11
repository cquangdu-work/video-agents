"""Đọc các nguồn RSS/Atom (OWID, EurekAlert, ScienceDaily, Yonhap...)."""
import logging

import feedparser
import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; video-agents-rss-reader/0.1)"}


def fetch_rss_sources(rss_list: list) -> list:
    items = []
    for src in rss_list:
        try:
            # Tự tải bằng requests (có timeout, báo lỗi HTTP rõ ràng) rồi mới đưa feedparser
            # đọc: để feedparser tự tải thì trên VM nguồn Hankyoreh trả về rỗng không rõ lý do.
            resp = requests.get(src["url"], headers=HEADERS, timeout=20)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                log.warning("RSS lỗi/rỗng: %s (%s)", src["name"], src["url"])
                continue
            for e in feed.entries[: 15 * src.get("weight", 1)]:
                items.append({
                    "title": e.get("title", "").strip(),
                    "summary": (e.get("summary", "") or "")[:500],
                    "url": e.get("link", ""),
                    "source": src["name"],
                    "lang": src.get("lang", "en"),
                })
            log.info("%s: %d bài", src["name"], len(feed.entries))
        except Exception as exc:   # mạng chập chờn không được làm sập cả pipeline
            log.warning("Bỏ qua nguồn %s: %s", src["name"], exc)
    return [i for i in items if i["title"] and i["url"]]
