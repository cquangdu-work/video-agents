"""Các module lấy ý tưởng thô. Mỗi module trả về list[dict] cùng một dạng:
    {"title": ..., "summary": ..., "url": ..., "source": ..., "lang": ...}
"""
from .rss import fetch_rss_sources
from .arxiv import fetch_arxiv
from .reddit import fetch_reddit
from .worldbank import fetch_worldbank
from .kosis import fetch_kosis
from .owid import fetch_owid


def fetch_all(cfg: dict) -> list:
    """Gom ý tưởng thô từ mọi nguồn trong config. Nguồn nào lỗi thì bỏ qua, không sập."""
    items = []
    items += fetch_rss_sources(cfg["sources"].get("rss", []))
    items += fetch_arxiv(cfg["sources"].get("arxiv", {}))
    items += fetch_reddit(cfg["sources"].get("reddit", {}))
    # World Bank để CUỐI: main lấy 60 ý tưởng thô mới nhất, nguồn này ít bài nên phải nằm
    # trong nhóm mới nhất kẻo bị 150 bài tin tức đẩy ra ngoài.
    items += fetch_worldbank(cfg["sources"].get("worldbank", {}))
    items += fetch_kosis(cfg["sources"].get("kosis", {}))     # cần KOSIS_API_KEY, không có thì bỏ qua
    items += fetch_owid(cfg["sources"].get("owid", {}))       # chủ đề thế giới, ngoài Việt–Hàn
    return items
