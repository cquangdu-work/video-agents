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

from . import db, lang
from .sources import fetch_all
from .sources.youtube_check import count_popular_vietnamese_videos

log = logging.getLogger("pipeline")

CONFIG_PATH = lang.config_path()          # kênh đang chạy (CHANNEL_CONFIG; mặc định kênh Việt)


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Trọng số chấm điểm mà agent Phân tích đã học (data/learned.yaml) đè lên cấu hình gốc
    from .analysis.learned import apply_learned
    return apply_learned(cfg)


def collect(cfg: dict, con) -> int:
    """Bước 1: gom ý tưởng thô từ mọi nguồn, nạp vào DB (tự bỏ trùng)."""
    from . import topics
    # Chủ đề được yêu cầu (người xem, Du /chude, video đột biến) lấy TRƯỚC xoay vòng — src/topics.py
    try:
        cfg = topics.with_requests(cfg, con)
    except Exception as exc:
        log.warning("Không đọc được hàng đợi chủ đề (bỏ qua): %s", exc)
    from . import themes                 # CHỦ ĐỀ TUẦN của video dài: bảng số của chủ đề lấy trước xoay vòng
    if themes.wanted(con, cfg):
        cfg = themes.with_theme(cfg)
    items = fetch_all(cfg)
    log.info("Lấy được %d ý tưởng thô từ các nguồn", len(items))
    added = db.insert_raw_ideas(con, items, cfg["dedup"]["title_similarity_threshold"])
    log.info("Thêm %d ý tưởng MỚI vào kho (còn lại là trùng)", added)
    return added


FRESH_POINTS = 10       # ý tưởng từ số vừa công bố: xếp trước mọi ý tưởng khác (tổng điểm Biên tập ~15-27)
THEME_POINTS = 4        # ý tưởng khớp CHỦ ĐỀ TUẦN (src/themes.py) khi tuần này còn thiếu Short của chủ đề


def run_agents(cfg: dict, con, use_telegram: bool = True) -> int:
    """Bước 2-5: 4 agent xử lý, trả về số kịch bản đã gửi."""
    from . import crew  # import muộn: cần crewai + API key
    from .page_text import fetch_page_text
    from .telegram_bot import format_script_message, send_message

    raw = db.todays_raw(con, limit=60)
    # ứng viên KẸT từ lượt trước sập giữa chừng (db.stuck_candidates) — đã có "góc", xét tiếp không cần săn lại
    stuck = db.stuck_candidates(con)
    if stuck:
        log.info("Nhặt lại %d ứng viên kẹt từ lượt chạy trước", len(stuck))
    if not raw and not stuck:
        log.warning("Kho không có ý tưởng thô mới — dừng.")
        return 0

    # --- Agent Săn ý tưởng: chọn ứng viên có "góc"
    candidates = crew.hunt_ideas(raw, cfg) if raw else []
    # SỐ VỪA CÔNG BỐ (kosis.build_monthly_map, dấu "신규 공표"): luôn là ứng viên — góc của nó chính là số mới, model Săn ý
    # tưởng không được bỏ sót (Du chốt 24/11/2026: video trong ngày công bố là lợi thế khó bắt chước của kênh)
    from .sources.datatable import is_fresh
    picked = {c.get("id") for c in candidates}
    candidates += [{"id": i["id"], "keyword": "",
                    "angle": "Số liệu tháng mới vừa được cơ quan thống kê công bố — video ra ngay sau khi công bố,"
                             " so với cùng tháng năm trước và theo từng tỉnh"}
                   for i in raw if is_fresh(i) and i["id"] not in picked]
    by_id = {i["id"]: i for i in raw}
    enriched = [dict(i, keyword="") for i in stuck]
    for c in candidates:
        idea = by_id.get(c["id"])
        if not idea:
            continue
        idea = dict(idea, angle=c["angle"], keyword=str(c.get("keyword") or "").strip())
        db.set_status(con, idea["id"], "candidate", angle=c["angle"])
        enriched.append(idea)
    log.info("Săn ý tưởng chọn %d ứng viên", len(enriched))

    # --- Lọc trùng lớp 2: YouTube (bỏ qua nếu chưa có API key). Tìm bằng TỪ KHÓA TIẾNG
    # VIỆT do Săn ý tưởng viết; thiếu thì dùng tiêu đề (tiêu đề báo Hàn/Anh tìm video
    # tiếng Việt thì gần như vô nghĩa).
    yt_cfg = cfg["dedup"]["youtube_check"]
    survivors = []
    for idea in enriched:
        query = idea["keyword"] or idea["title"]
        # số vừa công bố: chưa ai có video về tháng này (video cũ cùng đề tài là số cũ) -> không chặn
        n = None if is_fresh(idea) else count_popular_vietnamese_videos(query, yt_cfg)
        if n is not None and n > yt_cfg["max_popular_allowed"]:
            db.set_status(con, idea["id"], "rejected",
                          reason=f"Đã có {n} video tiếng Việt view cao cùng đề tài “{query}”")
            continue
        survivors.append(idea)

    # --- Loại sớm ý tưởng không đọc được bài nguồn (bài Reddit bị chặn, link chết...):
    # không có nguồn thì Biên kịch không có số để viết, Kiểm chứng không có gì để đối
    # chiếu. Loại TRƯỚC khi chấm điểm để chúng không chiếm suất viết kịch bản
    # (lần chạy 12/11: 3 trong 5 suất bị phí như vậy).
    readable = []
    for idea in survivors:
        text = source_text_for(idea, fetch_page_text)
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
        if s["total"] >= cfg["scoring_weights"]["min_total"] or is_fresh(idea):
            db.set_status(con, idea["id"], "selected", scores=s)
            selected.append(dict(idea, score=s["total"]))
        else:
            db.set_status(con, idea["id"], "rejected", reason=f"Điểm thấp ({s['total']})", scores=s)
    want = cfg["daily"]["shortlist"]
    # agent Tăng trưởng (src/growth.py): ý tưởng cùng mảng + dạng với video ĐỘT BIẾN gần đây được cộng điểm
    from . import growth, learning
    from .sources.datatable import topic_family
    grow = growth._data()
    from . import themes
    theme = themes.wanted(con, cfg)
    boost = lambda i: growth.IDEA_BOOST_POINTS * growth.boost_for(
        topic_family(i.get("source_name")), learning.video_kind(i.get("title"), i.get("source_name")), grow) \
        + (FRESH_POINTS if is_fresh(i) else 0) \
        + (THEME_POINTS if theme and themes.matches(theme, i.get("title"), i.get("summary")) else 0)
    selected = balance_families(sorted(selected, key=lambda i: -(i["score"] + boost(i))))
    # Kịch bản hụt chuẩn (thiếu số, quá ngắn) không được tính -> thử thêm ý tưởng kế
    # tiếp theo điểm, nhưng có trần để không đốt quota LLM vô hạn.
    selected = selected[: want + int(cfg["daily"].get("extra_script_tries", 2))]
    log.info("Biên tập chọn %d ý tưởng (cần %d kịch bản đạt)", len(selected), want)

    # --- Biên kịch + Kiểm chứng từng ý tưởng (sai số liệu thì trả về viết lại 1 lần)
    from . import learning
    sent = good = 0
    recent = db.recent_hooks(con)          # câu mở đầu gần đây: kịch bản mới phải mở khác đi
    for idea in selected:
        if good >= want:
            break
        # Biên kịch nhận toàn văn bài nguồn (đã tải ở bước lọc trên) để có số liệu mà viết
        source_text = idea["source_text"]
        # TỰ HỌC (src/learning.py): lỗi hay mắc, luật Du dạy, sở thích người xem, kịch bản mẫu
        lessons = learning.writer_lessons(con, idea, cfg)
        remember = lambda problems, stage, iid=idea["id"]: learning.record_problems(con, problems, stage, iid)
        # Thử nghiệm độ dài (src/style.py, Du xin 20/11 "thử video ngắn hơn"): mỗi kịch bản một mức 30/40/50
        # giây — Biên kịch và cổng chuẩn đọc khung giây của mức đó
        from . import style
        length = style.choose_length(cfg, idea["id"])
        cfg_i = style.with_length(cfg, length)
        try:
            script, fc, status = _script_one(crew, idea, source_text, cfg_i, recent, lessons, remember)
        except Exception as exc:
            # Một ý tưởng hỏng (LLM trả sai khuôn, mọi model quá tải...) không được kéo
            # sập cả khâu: ghi lại rồi sang ý tưởng kế tiếp.
            db.set_status(con, idea["id"], "rejected", reason=f"Lỗi khi viết kịch bản: {exc}"[:300])
            log.warning("Bỏ “%s”: lỗi khi viết kịch bản (%s: %s)", idea["title"][:50],
                        type(exc).__name__, str(exc)[:200])
            continue
        good += status == "verified"
        if script.get("scenes"):
            recent.insert(0, str(script["scenes"][0].get("voice") or ""))
        sid = db.save_script(con, idea["id"], script["hooks"],
                             yaml.safe_dump(script["scenes"], allow_unicode=True),
                             factcheck=fc, status=status)
        db.set_status(con, idea["id"], "scripted")
        if length:
            style.preassign(con, sid, length=length)
        learning.record(con, "outcome", status, idea["title"], "final", idea["id"], sid)

        msg = format_script_message(idea, script, fc)
        if use_telegram and send_message(msg):
            sent += 1
        else:
            print("\n" + "=" * 60 + "\n" + msg)
    log.info("Kịch bản đạt chuẩn trong lượt này: %d/%d", good, want)
    return sent


def balance_families(ideas: list) -> list:
    """Xếp xen kẽ các mảng chủ đề (datatable.topic_family: viet-han / the-gioi / bai-bao), trong
    mỗi mảng giữ thứ tự điểm; mảng có ý tưởng điểm cao nhất đi trước.
    [VH 26, VH 25, TG 24, BB 23] -> [VH 26, TG 24, BB 23, VH 25].

    Biên tập (model) hay chấm ý tưởng Việt–Hàn cao nhất vì bảng số dày đặc -> 3 suất viết kịch bản
    mỗi ngày đều về một mảng (ca thật 13-18/11). Xen kẽ thì mảng nào có ý tưởng đạt điểm sàn
    cũng được viết ít nhất một kịch bản."""
    from .sources.datatable import topic_family
    queues = {}
    for idea in ideas:
        queues.setdefault(topic_family(idea.get("source_name")), []).append(idea)
    out = []
    while any(queues.values()):
        for q in queues.values():
            if q:
                out.append(q.pop(0))
    return out


def source_text_for(idea: dict, fetch) -> str:
    """Văn bản nguồn để Biên kịch lấy số và để đối chiếu.

    Ý tưởng từ kho dữ liệu (World Bank): phần tóm tắt CHÍNH LÀ bảng số liệu gốc, còn
    trang web của nó là ứng dụng JavaScript không có số trong HTML -> dùng tóm tắt.
    Các nguồn khác: tải toàn văn bài báo.
    """
    from .sources.datatable import is_data_source
    if is_data_source(idea.get("source_name")):       # World Bank, KOSIS...
        return idea.get("summary") or ""
    return fetch(idea["source_url"])


def _script_one(crew, idea: dict, source_text: str, cfg: dict, recent_hooks: list = None,
                lessons: str = "", remember=None) -> tuple:
    """Biên kịch -> Kiểm chứng (sai số liệu thì viết lại 1 lần) -> cổng chuẩn.
    lessons: bài học tự học (src/learning.writer_lessons); remember(problems, stage): ghi lỗi vào bộ nhớ.
    Trả về (kịch bản, hồ sơ kiểm chứng, 'verified' | 'draft')."""
    from . import learning
    learned = dict(lessons=lessons, log_problems=remember, hook_bonus=learning.hook_bonus)
    script = crew.write_script(idea, cfg, source_text=source_text, recent_hooks=recent_hooks, **learned)
    fc = crew.fact_check(script, idea, source_text, cfg)
    # Hai cổng CODE đứng sau agent Kiểm chứng (LLM): từng con số trong lời đọc phải có trong nguồn
    # (bắt kiểu hook "99% người..." tự chế), từng câu so sánh phải khớp bảng số (bắt kiểu "Hàn Quốc
    # 2025 mới đạt mức Việt Nam có từ 1990" — sai mà mọi con số đều có trong nguồn, ca thật #46)
    unsourced = crew.unsourced_numbers(script, idea, source_text)
    wrong_cmp = crew.content_problems(script, idea.get("summary"))
    if not fc.get("pass") or unsourced or wrong_cmp:
        feedback = "\n".join(
            [f"- SAI: {v.get('claim', '')} -> {v.get('note', '')}"
             for v in fc.get("verdicts", []) if not crew._is_true(v.get("ok"))]
            + [f"- SAI (cảnh {it['scene']}): \"{it['voice']}\" -> {it['note']}"
               for it in fc.get("sentence_issues", [])]
            + [f"- BỊA SỐ: con số {n} trong lời đọc không có trong bài nguồn — bỏ đi hoặc"
               f" thay bằng con số có thật trong nguồn" for n in unsourced]
            + [f"- SAI/KHÔNG CÓ CĂN CỨ: {p}" for p in wrong_cmp])
        log.warning("Kiểm chứng trượt — trả về Biên kịch viết lại:\n%s", feedback)
        if remember:                     # lỗi Kiểm chứng / chống bịa số cũng là bài học
            remember([line[2:] for line in feedback.splitlines() if line.startswith("- ")], "final")
        script = crew.write_script(idea, cfg, feedback=feedback, source_text=source_text,
                                   recent_hooks=recent_hooks, **learned)
        fc = crew.fact_check(script, idea, source_text, cfg)
        unsourced = crew.unsourced_numbers(script, idea, source_text)
        wrong_cmp = crew.content_problems(script, idea.get("summary"))
    # Cổng cuối: chỉ lỗi CHẶN (lỗi "nhắc" như câu kết chưa quay lại hook chỉ dùng khi viết lại)
    problems = crew.script_problems(script, cfg, include_soft=False)
    if unsourced:
        problems.append("con số không có trong bài nguồn: " + ", ".join(unsourced))
    problems += [f"nội dung — {p}" for p in wrong_cmp]
    if problems:
        # Ghi lý do vào hồ sơ kiểm chứng để về sau tra được vì sao kịch bản bị giữ lại
        fc["standard_problems"] = problems
        log.warning("Kịch bản cho “%s” hụt chuẩn (%s) — giữ ở trạng thái nháp, không dựng",
                    idea["title"][:50], "; ".join(problems))
    # Nguồn thứ hai (Our World in Data cho số liệu World Bank) — lưu kèm hồ sơ kiểm chứng để Du
    # xem lúc duyệt; không chặn kịch bản (hai cơ quan thống kê có thể ước tính khác nhau đôi chút)
    try:
        from . import second_source
        fc["second_source"] = second_source.check(idea, second_source.scale_for(idea.get("summary"), cfg))
    except Exception as exc:
        log.warning("Kiểm chứng nguồn thứ hai lỗi (bỏ qua): %s", exc)
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
