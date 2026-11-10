"""Pipeline Giai đoạn 1: mỗi sáng chạy một lần.

    python -m src.main --dry-run      # chỉ lấy ý tưởng thô + nạp DB, không gọi LLM
    python -m src.main                # chạy đủ 4 agent, gửi kịch bản vào Telegram
    python -m src.main --no-telegram  # chạy đủ nhưng chỉ in ra màn hình

Thứ tự: lấy nguồn -> lọc trùng (DB + YouTube) -> Săn ý tưởng -> Biên tập
        -> Biên kịch -> Kiểm chứng -> gửi Telegram.
"""
import argparse
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import db
from .sources import fetch_all
from .sources.youtube_check import count_popular_vietnamese_videos

log = logging.getLogger("pipeline")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "channel.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect(cfg: dict, con) -> int:
    """Bước 1: gom ý tưởng thô từ mọi nguồn, nạp vào DB (tự bỏ trùng)."""
    items = fetch_all(cfg)
    log.info("Lấy được %d ý tưởng thô từ các nguồn", len(items))
    added = db.insert_raw_ideas(con, items, cfg["dedup"]["title_similarity_threshold"])
    log.info("Thêm %d ý tưởng MỚI vào kho (còn lại là trùng)", added)
    return added


def run_agents(cfg: dict, con, use_telegram: bool = True) -> int:
    """Bước 2-5: 4 agent xử lý, trả về số kịch bản đã gửi."""
    from . import crew  # import muộn: cần crewai + API key
    from .page_text import fetch_page_text
    from .telegram_bot import format_script_message, send_message

    raw = db.todays_raw(con, limit=60)
    if not raw:
        log.warning("Kho không có ý tưởng thô mới — dừng.")
        return 0

    # --- Agent Săn ý tưởng: chọn ứng viên có "góc"
    candidates = crew.hunt_ideas(raw, cfg)
    by_id = {i["id"]: i for i in raw}
    enriched = []
    for c in candidates:
        idea = by_id.get(c["id"])
        if not idea:
            continue
        idea = dict(idea, angle=c["angle"])
        db.set_status(con, idea["id"], "candidate", angle=c["angle"])
        enriched.append(idea)
    log.info("Săn ý tưởng chọn %d ứng viên", len(enriched))

    # --- Lọc trùng lớp 2: YouTube (bỏ qua nếu chưa có API key)
    yt_cfg = cfg["dedup"]["youtube_check"]
    survivors = []
    for idea in enriched:
        n = count_popular_vietnamese_videos(idea["title"], yt_cfg)
        if n is not None and n > yt_cfg["max_popular_allowed"]:
            db.set_status(con, idea["id"], "rejected",
                          reason=f"Đã có {n} video tiếng Việt view cao")
            continue
        survivors.append(idea)

    # --- Agent Biên tập: chấm điểm, lấy top
    scored = crew.score_ideas(survivors, cfg)
    scores_by_id = {s["id"]: s for s in scored}
    selected = []
    for idea in survivors:
        s = scores_by_id.get(idea["id"])
        if not s:
            continue
        if s["total"] >= cfg["scoring_weights"]["min_total"]:
            db.set_status(con, idea["id"], "selected", scores=s)
            selected.append(dict(idea, score=s["total"]))
        else:
            db.set_status(con, idea["id"], "rejected", reason=f"Điểm thấp ({s['total']})", scores=s)
    selected = sorted(selected, key=lambda i: -i["score"])[: cfg["daily"]["shortlist"]]
    log.info("Biên tập chọn %d ý tưởng", len(selected))

    # --- Biên kịch + Kiểm chứng từng ý tưởng
    sent = 0
    for idea in selected:
        script = crew.write_script(idea, cfg)
        source_text = fetch_page_text(idea["source_url"])
        fc = crew.fact_check(script, idea, source_text, cfg)
        status = "verified" if fc.get("pass") else "draft"
        db.save_script(con, idea["id"], script["hooks"],
                       yaml.safe_dump(script["scenes"], allow_unicode=True),
                       factcheck=fc, status=status)
        db.set_status(con, idea["id"], "scripted")

        msg = format_script_message(idea, script, fc)
        if use_telegram and send_message(msg):
            sent += 1
        else:
            print("\n" + "=" * 60 + "\n" + msg)
    return sent


def main():
    # Console Windows mặc định cp949 (máy cài tiếng Hàn) không in được tiếng Việt
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    parser = argparse.ArgumentParser(description="Pipeline sản xuất kịch bản video")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ lấy ý tưởng thô, không gọi LLM/Telegram")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Chạy đủ agent nhưng in kịch bản ra màn hình")
    args = parser.parse_args()

    cfg = load_config()
    con = db.connect()
    collect(cfg, con)

    if args.dry_run:
        rows = db.todays_raw(con, limit=10)
        print(f"\n--- 10 ý tưởng thô mới nhất (tổng raw trong kho: xem data/pipeline.db) ---")
        for r in rows:
            print(f"  [{r['id']}] ({r['source_name']}) {r['title'][:90]}")
        return

    sent = run_agents(cfg, con, use_telegram=not args.no_telegram)
    log.info("Hoàn tất: %d kịch bản đã gửi Telegram", sent)


if __name__ == "__main__":
    sys.exit(main())
