"""Tải toàn văn bài nguồn để agent Kiểm chứng đối chiếu."""
import logging

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; video-agents/0.1)"}


def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:max_chars]
    except Exception as exc:
        log.warning("Không tải được %s: %s", url, exc)
        return ""
