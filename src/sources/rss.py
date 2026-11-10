"""Đọc các nguồn RSS/Atom (OWID, EurekAlert, ScienceDaily, Yonhap...)."""
import logging

import feedparser

log = logging.getLogger(__name__)


def fetch_rss_sources(rss_list: list) -> list:
    items = []
    for src in rss_list:
        try:
            feed = feedparser.parse(src["url"], agent="video-agents-rss-reader/0.1")
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
