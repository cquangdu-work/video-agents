"""Lấy câu hỏi thật của người thật từ Reddit (không cần key).

Câu hỏi nhiều upvote trên r/askscience, r/explainlikeimfive = thứ người ta
thật sự tò mò -> nguyên liệu tốt cho video giải thích.

Hai đường lấy: JSON công khai (đủ thông tin nhất) và RSS. Reddit chặn đường JSON
với IP của các nhà mạng đám mây (VM Oracle nhận 403), còn RSS thì vẫn cho — nên
JSON hỏng thì tự chuyển sang RSS.
"""
import logging
import time

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "video-agents-pipeline/0.1"}
RSS_PAUSE = 10     # giây nghỉ giữa các subreddit khi đi đường RSS (gọi dồn là bị 429)


def _from_json(sub: str, cfg: dict) -> list:
    url = (f"https://www.reddit.com/r/{sub}/{cfg.get('listing', 'top')}.json"
           f"?t={cfg.get('time', 'day')}&limit={cfg.get('limit', 20)}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    items = []
    for p in resp.json()["data"]["children"]:
        d = p["data"]
        if d.get("stickied"):
            continue
        items.append({
            "title": d.get("title", "").strip(),
            "summary": (d.get("selftext", "") or "")[:500],
            "url": "https://www.reddit.com" + d.get("permalink", ""),
        })
    return items


def _from_rss(sub: str, cfg: dict) -> list:
    import feedparser
    from bs4 import BeautifulSoup

    url = (f"https://www.reddit.com/r/{sub}/{cfg.get('listing', 'top')}/.rss"
           f"?t={cfg.get('time', 'day')}&limit={cfg.get('limit', 20)}")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code == 429:               # gọi hơi dồn: nghỉ rồi thử lại đúng một lần
        time.sleep(RSS_PAUSE * 3)
        resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    items = []
    for e in feedparser.parse(resp.content).entries:
        html = (e.get("content") or [{}])[0].get("value") or e.get("summary", "")
        text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ").split())
        # RSS của Reddit luôn chèn đuôi "submitted by /u/... [link] [comments]"
        text = text.split("submitted by")[0].strip()
        items.append({"title": e.get("title", "").strip(), "summary": text[:500],
                      "url": e.get("link", "")})
    return items


def fetch_reddit(cfg: dict) -> list:
    items, use_rss = [], False
    for sub in cfg.get("subreddits", []):
        posts = None
        if not use_rss:
            try:
                posts = _from_json(sub, cfg)
            except Exception as exc:
                log.info("r/%s: đường JSON bị chặn (%s) — chuyển sang RSS", sub, type(exc).__name__)
                use_rss = True                # đã chặn một sub thì các sub sau cũng thế
        if posts is None:
            try:
                if items or use_rss:
                    time.sleep(RSS_PAUSE)
                posts = _from_rss(sub, cfg)
            except Exception as exc:
                log.warning("Bỏ qua r/%s: %s", sub, exc)
                continue
        for p in posts:
            if p["title"] and p["url"]:
                items.append(dict(p, source=f"r/{sub}", lang="en"))
        log.info("r/%s: %d bài", sub, len(posts))
    return items
