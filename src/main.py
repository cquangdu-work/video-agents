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
        cfg = yaml.safe_load(f)
    # Trọng số chấm điểm mà agent Phân tích đã học (data/learned.yaml) đè lên cấu hình gốc
    from .analysis.learned import apply_learned
    return apply_learned(cfg)


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

    # --- Loại sớm ý tưởng không đọc được bài nguồn (bài Reddit bị chặn, link chết...):
    # không có nguồn thì Biên kịch không có số để viết, Kiểm chứng không có gì để đối
    # chiếu. Loại TRƯỚC khi chấm điểm để chúng không chiếm suất viết kịch bản
    # (lần chạy 12/11: 3 trong 5 suất bị phí như vậy).
    readable = []
    for idea in survivors:
        text = fetch_page_text(idea["source_url"])
        if not text.strip():
            db.set_status(con, idea["id"], "rejected", reason="Không tải được bài nguồn")
            log.warning("Bỏ “%s”: không tải được bài nguồn", idea["title"][:50])
            continue
        readable.append(dict(idea, source_text=text))
    survivors = readable
    if not survivors:
        log.warning("Không còn ý tưởng nào đọc được nguồn — dừng.")
        return 0

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
    want = cfg["daily"]["shortlist"]
    selected = sorted(selected, key=lambda i: -i["score"])
    # Kịch bản hụt chuẩn (thiếu số, quá ngắn) không được tính -> thử thêm ý tưởng kế
    # tiếp theo điểm, nhưng có trần để không đốt quota LLM vô hạn.
    selected = selected[: want + int(cfg["daily"].get("extra_script_tries", 2))]
    log.info("Biên tập chọn %d ý tưởng (cần %d kịch bản đạt)", len(selected), want)

    # --- Biên kịch + Kiểm chứng từng ý tưởng (sai số liệu thì trả về viết lại 1 lần)
    sent = good = 0
    for idea in selected:
        if good >= want:
            break
        # Biên kịch nhận toàn văn bài nguồn (đã tải ở bước lọc trên) để có số liệu mà viết
        source_text = idea["source_text"]
        try:
            script, fc, status = _script_one(crew, idea, source_text, cfg)
        except Exception as exc:
            # Một ý tưởng hỏng (LLM trả sai khuôn, mọi model quá tải...) không được kéo
            # sập cả khâu: ghi lại rồi sang ý tưởng kế tiếp.
            db.set_status(con, idea["id"], "rejected", reason=f"Lỗi khi viết kịch bản: {exc}"[:300])
            log.warning("Bỏ “%s”: lỗi khi viết kịch bản (%s: %s)", idea["title"][:50],
                        type(exc).__name__, str(exc)[:200])
            continue
        good += status == "verified"
        db.save_script(con, idea["id"], script["hooks"],
                       yaml.safe_dump(script["scenes"], allow_unicode=True),
                       factcheck=fc, status=status)
        db.set_status(con, idea["id"], "scripted")

        msg = format_script_message(idea, script, fc)
        if use_telegram and send_message(msg):
            sent += 1
        else:
            print("\n" + "=" * 60 + "\n" + msg)
    log.info("Kịch bản đạt chuẩn trong lượt này: %d/%d", good, want)
    return sent


def _script_one(crew, idea: dict, source_text: str, cfg: dict) -> tuple:
    """Biên kịch -> Kiểm chứng (sai số liệu thì viết lại 1 lần) -> cổng chuẩn.
    Trả về (kịch bản, hồ sơ kiểm chứng, 'verified' | 'draft')."""
    script = crew.write_script(idea, cfg, source_text=source_text)
    fc = crew.fact_check(script, idea, source_text, cfg)
    # Kiểm chứng bằng LLM chỉ soát các "claims" được khai; code tự soát TỪNG con số trong
    # lời đọc xem có trong bài nguồn không (bắt kiểu hook "99% người..." tự chế)
    unsourced = crew.unsourced_numbers(script, idea, source_text)
    if not fc.get("pass") or unsourced:
        feedback = "\n".join(
            [f"- SAI: {v.get('claim', '')} -> {v.get('note', '')}"
             for v in fc.get("verdicts", []) if not v.get("ok")]
            + [f"- BỊA SỐ: con số {n} trong lời đọc không có trong bài nguồn — bỏ đi hoặc"
               f" thay bằng con số có thật trong nguồn" for n in unsourced])
        log.warning("Kiểm chứng trượt — trả về Biên kịch viết lại:\n%s", feedback)
        script = crew.write_script(idea, cfg, feedback=feedback, source_text=source_text)
        fc = crew.fact_check(script, idea, source_text, cfg)
        unsourced = crew.unsourced_numbers(script, idea, source_text)
    problems = crew.script_problems(script, cfg)
    if unsourced:
        problems.append("con số không có trong bài nguồn: " + ", ".join(unsourced))
    if problems:
        # Ghi lý do vào hồ sơ kiểm chứng để về sau tra được vì sao kịch bản bị giữ lại
        fc["standard_problems"] = problems
        log.warning("Kịch bản cho “%s” hụt chuẩn (%s) — giữ ở trạng thái nháp, không dựng",
                    idea["title"][:50], "; ".join(problems))
    return script, fc, "verified" if fc.get("pass") and not problems else "draft"


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
