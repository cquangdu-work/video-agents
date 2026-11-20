"""Lớp chống trùng số 2: tìm trên YouTube xem ý tưởng đã có nhiều video tiếng Việt chưa.

Cần YOUTUBE_API_KEY trong .env; không có key thì trả về None (bỏ qua bước này).

Một video chỉ được tính là "đã có người làm" khi hội đủ hai điều:
1. view cao (>= high_view_threshold), và
2. tiêu đề của nó nói về CÙNG ĐỀ TÀI: phần lớn từ khóa đặc trưng của ý tưởng có mặt
   trong tiêu đề video.
Trước đây chỉ xét (1): tìm "Điện tiêu thụ bình quân đầu người Việt Nam và Hàn Quốc" thì
YouTube trả về toàn video bóng đá Việt–Hàn triệu view, và ý tưởng bị loại oan.
"""
import logging
import os
import re
import unicodedata

import requests

from .. import lang

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# Từ không nói lên ĐỀ TÀI: tên hai nước kênh hay đem so (có trong gần như mọi ý tưởng
# Việt–Hàn), từ so sánh, từ hỏi, hư từ. Tiêu đề video có những từ này không có nghĩa
# là cùng đề tài.
GENERIC = {
    "việt", "nam", "hàn", "quốc", "vn", "kr", "korea", "vietnam",
    "so", "sánh", "vs", "và", "với", "của", "là", "có", "các", "những", "một", "từ", "đến",
    "năm", "về", "trong", "khi", "thì", "mà", "này", "đó", "vì", "sao", "tại", "thế", "nào",
    "bao", "nhiêu", "gì", "ai", "đâu", "hay", "nhất", "hơn", "rất", "đã", "đang", "sẽ",
}
MIN_OVERLAP = 0.6       # cần ít nhất 60% từ khóa đặc trưng có mặt trong tiêu đề video


def topic_tokens(text: str) -> set:
    """Từ khóa đặc trưng của một câu: chữ thường, bỏ dấu câu, bỏ số và từ chung chung."""
    words = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFC", str(text).lower())).split()
    return {w for w in words if w not in GENERIC and not w.isdigit() and len(w) > 1}


def same_topic(keyword: str, video_title: str) -> bool:
    want = topic_tokens(keyword)
    if not want:                 # từ khóa toàn từ chung chung: không đủ căn cứ để nói là trùng
        return False
    return len(want & topic_tokens(video_title)) / len(want) >= MIN_OVERLAP


def count_popular_vietnamese_videos(query: str, cfg: dict):
    """Số video tiếng Việt view cao CÙNG ĐỀ TÀI với `query` (từ khóa tìm kiếm tiếng Việt),
    hoặc None nếu không có key / API lỗi."""
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(SEARCH_URL, params={
            "key": key, "q": query, "part": "id", "type": "video",
            # kênh đang chạy (src/lang.py): kênh Việt tìm video tiếng Việt ở VN, kênh Hàn tìm video tiếng Hàn ở KR
            "relevanceLanguage": lang.code(), "regionCode": {"vi": "VN", "ko": "KR"}[lang.code()],
            "maxResults": cfg.get("max_results", 10),
        }, timeout=15)
        r.raise_for_status()
        ids = [i["id"]["videoId"] for i in r.json().get("items", [])]
        if not ids:
            return 0
        r = requests.get(VIDEOS_URL, params={
            "key": key, "id": ",".join(ids), "part": "snippet,statistics",
        }, timeout=15)
        r.raise_for_status()
        threshold = cfg.get("high_view_threshold", 100_000)
        hits = []
        for v in r.json().get("items", []):
            title = v.get("snippet", {}).get("title", "")
            views = int(v.get("statistics", {}).get("viewCount", 0))
            if views >= threshold and same_topic(query, title):
                hits.append(f"{title} ({views:,} view)")
        if hits:
            log.info("YouTube đã có video cùng đề tài “%s”: %s", query, "; ".join(hits[:3]))
        return len(hits)
    except Exception as exc:
        # Chỉ ghi tên lỗi: nội dung lỗi của requests chứa cả URL kèm khoá API
        log.warning("YouTube check lỗi (%s) — bỏ qua", type(exc).__name__)
        return None
