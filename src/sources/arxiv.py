"""Lấy bài mới từ arXiv qua API công khai (không cần key)."""
import logging

import feedparser

log = logging.getLogger(__name__)

API = "http://export.arxiv.org/api/query?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results={n}"


def fetch_arxiv(cfg: dict) -> list:
    cats = cfg.get("categories", [])
    if not cats:
        return []
    query = "+OR+".join(f"cat:{c}" for c in cats)
    url = API.format(query=query, n=cfg.get("max_results", 15))
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        log.warning("arXiv lỗi: %s", exc)
        return []
    items = []
    for e in feed.entries:
        items.append({
            "title": e.get("title", "").replace("\n", " ").strip(),
            "summary": (e.get("summary", "") or "")[:500],
            "url": e.get("link", ""),
            "source": "arXiv",
            "lang": "en",
        })
    log.info("arXiv: %d bài", len(items))
    return items
