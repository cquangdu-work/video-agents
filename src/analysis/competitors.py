"""Phân tích đối thủ: tìm video ĐỘT BIẾN trên các kênh giải thích ngắn.

"Đột biến" = video có lượt xem gấp nhiều lần trung vị (median) của CHÍNH kênh đó
— tức đề tài/cách làm đó ăn khách vượt mức bình thường của kênh, không phải vì
kênh to sẵn.

Cách chạy:
    python -m src.analysis.competitors            # quét + lưu data/competitors.json
    python -m src.analysis.competitors --formula  # thêm bước LLM viết config/formula.yaml

Tốn quota YouTube: ~100 units/truy vấn tìm kiếm (xem seed_queries trong
config/channel.yaml), cộng ~3 units/kênh — một lần quét hết khoảng 1.000 units
trong hạn mức 10.000/ngày.
"""
import argparse
import json
import logging
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

log = logging.getLogger("competitors")

API = "https://www.googleapis.com/youtube/v3"
DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "competitors.json"


def _get(endpoint: str, **params):
    params["key"] = os.getenv("YOUTUBE_API_KEY")
    if endpoint == "search":            # 100 đơn vị/lần, hạn mức dùng chung hai kênh (src/publish/yt_quota.py)
        from ..publish import yt_quota
        yt_quota.spend("search")
    r = requests.get(f"{API}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _parse_duration(iso: str) -> int:
    """PT1M30S -> 90 giây."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


# ------------------------------------------------- Bước 1: gom kênh ứng viên
def find_candidate_channels(queries: list, months: int = 6, per_query: int = 15) -> dict:
    """Tìm video ngắn gần đây theo từ khóa, gom lại theo kênh."""
    published_after = (datetime.now(timezone.utc) - timedelta(days=30 * months)
                       ).isoformat(timespec="seconds")
    channels = {}
    for q in queries:
        try:
            res = _get("search", q=q["q"], part="snippet", type="video",
                       videoDuration="short", order="relevance",
                       publishedAfter=published_after, maxResults=per_query,
                       relevanceLanguage=q.get("lang", "vi"))
        except Exception as exc:
            log.warning("Tìm kiếm '%s' lỗi: %s", q["q"], exc)
            continue
        for item in res.get("items", []):
            cid = item["snippet"]["channelId"]
            channels.setdefault(cid, {
                "channel_id": cid,
                "title": item["snippet"]["channelTitle"],
                "lang": q.get("lang", "vi"),
                "found_via": q["q"],
            })
        log.info("'%s': %d video -> tổng %d kênh", q["q"], len(res.get("items", [])), len(channels))
    return channels


def filter_channels(channels: dict, min_subs: int, max_subs: int) -> list:
    """Giữ kênh cỡ vừa (nhỏ mà lớn nhanh được mới đáng học)."""
    kept = []
    ids = list(channels.keys())
    for i in range(0, len(ids), 50):   # API cho tối đa 50 id/lần
        res = _get("channels", id=",".join(ids[i:i + 50]),
                   part="statistics,contentDetails,snippet")
        for ch in res.get("items", []):
            subs = int(ch["statistics"].get("subscriberCount", 0))
            if not (min_subs <= subs <= max_subs):
                continue
            info = channels[ch["id"]]
            info.update(
                subs=subs,
                total_views=int(ch["statistics"].get("viewCount", 0)),
                video_count=int(ch["statistics"].get("videoCount", 0)),
                uploads_playlist=ch["contentDetails"]["relatedPlaylists"]["uploads"],
                created=ch["snippet"].get("publishedAt", ""),
            )
            kept.append(info)
    return kept


# -------------------------------------------- Bước 2: tìm video đột biến
def find_outliers(channel: dict, recent_n: int = 30, ratio_threshold: float = 5.0,
                  max_seconds: int = 180) -> list:
    """Lấy ~30 video gần nhất của kênh, video nào view >= ratio_threshold lần
    trung vị kênh thì tính là đột biến."""
    try:
        res = _get("playlistItems", playlistId=channel["uploads_playlist"],
                   part="contentDetails", maxResults=min(recent_n, 50))
        vids = [v["contentDetails"]["videoId"] for v in res.get("items", [])]
        if len(vids) < 8:            # kênh quá ít video, trung vị không tin được
            return []
        res = _get("videos", id=",".join(vids), part="statistics,contentDetails,snippet")
    except Exception as exc:
        log.warning("Kênh %s lỗi: %s", channel["title"], exc)
        return []

    items = []
    for v in res.get("items", []):
        items.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "views": int(v["statistics"].get("viewCount", 0)),
            "seconds": _parse_duration(v["contentDetails"]["duration"]),
            "published": v["snippet"]["publishedAt"],
        })
    views = [i["views"] for i in items]
    med = statistics.median(views) if views else 0
    if med < 200:                    # kênh gần như không có người xem -> bỏ
        return []
    outliers = []
    for i in items:
        ratio = i["views"] / med
        if ratio >= ratio_threshold and 0 < i["seconds"] <= max_seconds:
            outliers.append({**i, "ratio": round(ratio, 1),
                             "channel": channel["title"], "channel_subs": channel["subs"],
                             "lang": channel["lang"], "channel_median_views": int(med)})
    return outliers


# --------------------------------------------------------------- Chạy tất cả
def run_scan(cfg: dict) -> dict:
    ca = cfg["competitor_analysis"]
    channels = find_candidate_channels(ca["seed_queries"], ca["months_back"])
    # Kênh mà CHÍNH YOUTUBE đặt video của mình bên cạnh (agent Hiểu YouTube, nguồn "video đề xuất"):
    # YouTube coi là cùng nhóm người xem -> đáng học hơn kênh tìm thấy bằng từ khoá
    try:
        from ..yt_insights import neighbor_channels
        for cid, title in neighbor_channels().items():
            channels.setdefault(cid, {"channel_id": cid, "title": title, "lang": "vi",
                                      "found_via": "YouTube đặt cạnh video của kênh"})
    except Exception as exc:
        log.warning("Không đọc được kênh hàng xóm: %s", exc)
    kept = filter_channels(channels, ca["min_subs"], ca["max_subs"])
    log.info("Giữ %d/%d kênh cỡ %d-%d subs", len(kept), len(channels),
             ca["min_subs"], ca["max_subs"])
    all_outliers = []
    for ch in kept[: ca["max_channels"]]:
        outs = find_outliers(ch, ratio_threshold=ca["outlier_ratio"])
        if outs:
            log.info("  %s (%d subs): %d video đột biến", ch["title"], ch["subs"], len(outs))
        all_outliers += outs
    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channels_scanned": len(kept[: ca["max_channels"]]),
        "outliers": sorted(all_outliers, key=lambda o: -o["ratio"]),
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Lưu %d video đột biến vào %s", len(all_outliers), DATA_PATH)
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", action="store_true",
                        help="Sau khi quét, gọi LLM viết config/formula.yaml")
    args = parser.parse_args()

    from ..main import load_config
    cfg = load_config()
    result = run_scan(cfg)

    if args.formula and result["outliers"]:
        from .formula import synthesize_formula
        path = synthesize_formula(result, cfg)
        print(f"Đã viết công thức: {path}")


if __name__ == "__main__":
    main()
