"""Các module lấy ý tưởng thô. Mỗi module trả về list[dict] cùng một dạng:
    {"title": ..., "summary": ..., "url": ..., "source": ..., "lang": ...}
"""
from .rss import fetch_rss_sources
from .arxiv import fetch_arxiv
from .reddit import fetch_reddit


def fetch_all(cfg: dict) -> list:
    """Gom ý tưởng thô từ mọi nguồn trong config. Nguồn nào lỗi thì bỏ qua, không sập."""
    items = []
    items += fetch_rss_sources(cfg["sources"].get("rss", []))
    items += fetch_arxiv(cfg["sources"].get("arxiv", {}))
    items += fetch_reddit(cfg["sources"].get("reddit", {}))
    return items
