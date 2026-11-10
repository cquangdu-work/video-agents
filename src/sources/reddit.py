"""Lấy câu hỏi thật của người thật từ Reddit (JSON công khai, không cần key).

Câu hỏi nhiều upvote trên r/askscience, r/explainlikeimfive = thứ người ta
thật sự tò mò -> nguyên liệu tốt cho video giải thích.
"""
import logging

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "video-agents-pipeline/0.1"}


def fetch_reddit(cfg: dict) -> list:
    items = []
    for sub in cfg.get("subreddits", []):
        url = (f"https://www.reddit.com/r/{sub}/{cfg.get('listing', 'top')}.json"
               f"?t={cfg.get('time', 'day')}&limit={cfg.get('limit', 20)}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]
        except Exception as exc:
            log.warning("Bỏ qua r/%s: %s", sub, exc)
            continue
        for p in posts:
            d = p["data"]
            if d.get("stickied"):
                continue
            items.append({
                "title": d.get("title", "").strip(),
                "summary": (d.get("selftext", "") or "")[:500],
                "url": "https://www.reddit.com" + d.get("permalink", ""),
                "source": f"r/{sub}",
                "lang": "en",
            })
        log.info("r/%s: %d bài", sub, len(posts))
    return items
