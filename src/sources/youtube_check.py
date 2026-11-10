"""Lớp chống trùng số 2: tìm trên YouTube xem ý tưởng đã có nhiều video tiếng Việt chưa.

Cần YOUTUBE_API_KEY trong .env; không có key thì trả về None (bỏ qua bước này).
"""
import logging
import os

import requests

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def count_popular_vietnamese_videos(query: str, cfg: dict):
    """Trả về số video tiếng Việt vượt ngưỡng view cho từ khóa này, hoặc None nếu không có key."""
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(SEARCH_URL, params={
            "key": key, "q": query, "part": "id", "type": "video",
            "relevanceLanguage": "vi", "regionCode": "VN",
            "maxResults": cfg.get("max_results", 10),
        }, timeout=15)
        r.raise_for_status()
        ids = [i["id"]["videoId"] for i in r.json().get("items", [])]
        if not ids:
            return 0
        r = requests.get(VIDEOS_URL, params={
            "key": key, "id": ",".join(ids), "part": "statistics",
        }, timeout=15)
        r.raise_for_status()
        threshold = cfg.get("high_view_threshold", 100_000)
        return sum(
            1 for v in r.json().get("items", [])
            if int(v["statistics"].get("viewCount", 0)) >= threshold
        )
    except Exception as exc:
        log.warning("YouTube check lỗi (%s) — bỏ qua", exc)
        return None
