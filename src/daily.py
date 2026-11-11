"""Chuỗi chạy HẰNG NGÀY — một lệnh nối toàn bộ dây chuyền (giai đoạn 4).

    python -m src.daily                # chạy thật (trên VM: systemd timer gọi mỗi sáng)
    python -m src.daily --dry-run      # chỉ in kế hoạch: sẽ chọn kịch bản nào, chạy bước nào
    python -m src.daily --skip-ideas   # bỏ bước săn ý tưởng, dùng kịch bản đã có trong DB

Dây chuyền:
    1. src.main      Săn ý tưởng -> Biên tập -> Biên kịch -> Kiểm chứng  (kịch bản 'verified')
    2. chọn kịch bản tốt nhất chưa có video
    3. src.produce   kịch bản -> spec cảnh        (bỏ qua nếu spec đã có)
    4. src.assemble  giọng + hình + phụ đề        (bỏ qua nếu video đã có)
    5. src.review    kiểm định -> gửi Telegram cho Du duyệt

Mỗi bước là một tiến trình con riêng (subprocess): bước nào sập/treo thì chỉ bước đó
chết, daily vẫn sống để thử kịch bản kế và BÁO CHO DU qua Telegram. Toàn bộ chữ các
bước in ra được ghi vào logs/daily_<ngày>.log.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import db
from . import telegram_bot as tg

log = logging.getLogger("daily")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "channel.yaml"
SPEC_DIR = ROOT / "data" / "specs"
OUTPUT = ROOT / "output"
LOG_DIR = ROOT / "logs"

MAX_FAILS_PER_SCRIPT = 2          # kịch bản dựng hỏng 2 lần thì thôi không thử nữa
EXIT_RETRY_LATER = 75             # bước con thoát mã này = "lỗi tạm thời của dịch vụ ngoài"
                                  # (assemble: hết quota TTS) — khớp src/assemble.py
STEP_TIMEOUT = {"ideas": 3600, "produce": 1800, "assemble": 5400, "review": 1200}  # giây


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def final_path(script_id: int) -> Path:
    return OUTPUT / f"final_{script_id}.mp4"


def videos_made_since(con, hours: float = 20, now: datetime = None) -> int:
    """Số video đã gửi duyệt trong N giờ qua — để chạy lại trong ngày không làm dư."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(hours=hours)).isoformat(timespec="seconds")
    # Chỉ tính video ĐÃ TỚI Telegram (có tg_message_id); gửi hụt thì không tính
    return con.execute("SELECT COUNT(*) FROM videos WHERE created_at >= ?"
                       " AND tg_message_id IS NOT NULL", (since,)).fetchone()[0]


def script_words(body: str) -> int:
    """Tổng số từ lời đọc của một kịch bản (cột scripts.body là YAML danh sách cảnh)."""
    try:
        scenes = yaml.safe_load(body or "") or []
        return sum(len(str(s.get("voice", "")).split()) for s in scenes)
    except Exception:
        return 0


def pick_candidates(con, cfg: dict, now: datetime = None) -> list:
    """Kịch bản đủ điều kiện dựng, theo thứ tự ưu tiên. Trả về [{"id", "score", "has_final"}].

    Điều kiện: đã qua Kiểm chứng, chưa gửi duyệt lần nào, còn mới, chưa hỏng quá số lần,
    lời đọc đủ dài.
    Ưu tiên: cái đã dựng xong video (khỏi tốn công) -> điểm Biên tập cao -> mới hơn.
    """
    max_age = cfg["daily"].get("max_script_age_days", 3)
    min_words = cfg["daily"].get("min_script_words", 150)
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=max_age)).isoformat(timespec="seconds")
    rows = con.execute(
        "SELECT s.id, s.body, i.scores FROM scripts s JOIN ideas i ON i.id = s.idea_id"
        " WHERE s.status = 'verified' AND s.created_at >= ?"
        # video gửi Telegram hụt (chưa có tg_message_id) vẫn được thử gửi lại
        " AND s.id NOT IN (SELECT script_id FROM videos WHERE tg_message_id IS NOT NULL"
        "                  OR status != 'pending_review')", (since,)).fetchall()
    out = []
    for r in rows:
        if int(db.get_state(con, f"prod_fail_{r['id']}", "0")) >= MAX_FAILS_PER_SCRIPT:
            continue
        words = script_words(r["body"])
        if words < min_words:
            # Chặn TRƯỚC khi tốn quota giọng đọc + công dựng: kịch bản đời cũ (3 cảnh,
            # ~115 từ) cho ra video ~40 giây, kiểu gì cũng rớt Kiểm định độ dài.
            log.info("Bỏ qua kịch bản #%d: lời đọc chỉ %d từ (cần ≥ %d)", r["id"], words, min_words)
            continue
        try:
            score = float(json.loads(r["scores"] or "{}").get("total", 0))
        except (ValueError, TypeError):
            score = 0.0
        out.append({"id": r["id"], "score": score, "has_final": final_path(r["id"]).exists()})
    return sorted(out, key=lambda c: (not c["has_final"], -c["score"], -c["id"]))


def _spec_usable(path: Path) -> bool:
    """Spec dùng được = tồn tại VÀ có lời đọc (spec đời cũ không có 'voice'
    sẽ cho ra video câm — phải sinh lại)."""
    if not path.exists():
        return False
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return any((sc.get("voice") or "").strip() for sc in spec)
    except Exception:
        return False


def plan_steps(script_id: int) -> list:
    """Các bước còn phải chạy cho một kịch bản: [(tên, khoá timeout, tham số python)].

    Spec đã có (và dùng được) thì KHÔNG sinh lại: assemble giữ cache giọng đọc
    theo thứ tự cảnh, spec mới + giọng cũ sẽ lệch nhau.
    """
    sid, steps = str(script_id), []
    if not final_path(script_id).exists():
        if not _spec_usable(SPEC_DIR / f"script_{sid}.yaml"):
            steps.append(("Dựng spec cảnh", "produce", ["-m", "src.produce", sid, "--spec-only"]))
        steps.append(("Lắp ráp video", "assemble", ["-m", "src.assemble", sid]))
    steps.append(("Kiểm định + gửi duyệt", "review", ["-m", "src.review", "send", sid]))
    return steps


def run_step(name: str, key: str, args: list, log_file: Path) -> tuple:
    """Chạy một bước bằng tiến trình con. Trả về (thành công?, mấy dòng cuối để báo lỗi)."""
    log.info("▶ %s: python %s", name, " ".join(args))
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} {name}: {' '.join(args)}\n")
        fh.flush()
        try:
            # PYTHONUTF8: stdout của tiến trình con trỏ vào file -> Windows sẽ mã hóa
            # cp949 và sập với tiếng Việt nếu không ép UTF-8 (Linux không ảnh hưởng)
            proc = subprocess.run([sys.executable, *args], cwd=ROOT, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=STEP_TIMEOUT[key],
                                  env={**os.environ, "PYTHONUTF8": "1"})
            ok, why = proc.returncode == 0, f"mã thoát {proc.returncode}"
        except subprocess.TimeoutExpired:
            ok, why = False, f"quá {STEP_TIMEOUT[key] // 60} phút"
    if ok:
        return True, ""
    lines = log_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return False, f"{why}\n" + "\n".join(lines[-6:])


def run_daily(skip_ideas: bool = False, dry_run: bool = False, runner=run_step) -> int:
    """Trả về số video đã gửi duyệt trong lượt chạy này."""
    cfg, con = load_config(), db.connect()
    try:
        return _run_daily(cfg, con, skip_ideas, dry_run, runner)
    finally:
        con.close()      # Windows: kết nối mở giữ khóa file DB


def _run_daily(cfg, con, skip_ideas, dry_run, runner) -> int:
    want = int(cfg["daily"].get("videos_per_day", 1))
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"daily_{datetime.now():%Y-%m-%d}.log"

    already = videos_made_since(con)
    if already >= want:
        log.info("Hôm nay đã gửi duyệt %d video — không làm thêm.", already)
        return 0

    problems = []
    if not skip_ideas and not dry_run:
        ok, tail = runner("Săn ý tưởng + viết kịch bản", "ideas",
                          ["-m", "src.main", "--no-telegram"], log_file)
        if not ok:      # vẫn đi tiếp: có thể còn kịch bản tốt từ hôm trước
            problems.append(f"Bước ý tưởng/kịch bản lỗi ({tail.splitlines()[0]})")

    candidates = pick_candidates(con, cfg)
    if dry_run:
        print(f"Cần {want - already} video. Ứng viên theo thứ tự ưu tiên:")
        for c in candidates:
            print(f"  kịch bản #{c['id']} (điểm {c['score']}, "
                  f"{'đã có video' if c['has_final'] else 'chưa dựng'}):"
                  f" {' -> '.join(s[0] for s in plan_steps(c['id']))}")
        if not candidates:
            print("  (không có kịch bản nào đủ điều kiện)")
        return 0

    made, attempts = 0, 0
    for c in candidates:
        if made >= want - already or attempts >= int(cfg["daily"].get("max_attempts", 2)):
            break
        attempts += 1
        failed, retry_later = None, False
        for name, key, args in plan_steps(c["id"]):
            ok, tail = runner(name, key, args, log_file)
            if not ok:
                retry_later = tail.splitlines()[:1] == [f"mã thoát {EXIT_RETRY_LATER}"]
                failed = f"Kịch bản #{c['id']} hỏng ở bước “{name}”: {tail}"
                break
        if retry_later:
            # Hết quota giọng đọc: KHÔNG phải lỗi của kịch bản -> không tính lần hỏng
            # (kẻo 2 hôm hết quota là kịch bản bị loại oan), và không thử kịch bản kế
            # (nó cũng cần TTS, chỉ đốt thêm quota rồi hỏng y hệt).
            msg = (f"Kịch bản #{c['id']} tạm dừng ở bước “{name}”: hết quota giọng đọc (TTS)."
                   " Phần giọng đã đọc xong được giữ lại. Quota hồi khoảng 16-17h giờ Hàn;"
                   " sau đó chạy lại `python -m src.daily --skip-ideas` là làm tiếp.")
            problems.append(msg)
            log.warning(msg)
            break
        if failed:
            fails = int(db.get_state(con, f"prod_fail_{c['id']}", "0")) + 1
            db.set_state(con, f"prod_fail_{c['id']}", fails)
            problems.append(failed)
            log.warning(failed)
        else:
            made += 1

    if made == 0:
        reason = "\n\n".join(problems) if problems else "Không có kịch bản nào qua được Kiểm chứng."
        tg.send_message(f"⚠️ Hôm nay chưa có video để duyệt.\n\n{reason}"[:3500]
                        + f"\n\nChi tiết: logs/{log_file.name}")
    elif problems:
        tg.send_message("ℹ️ Đã gửi video, nhưng có trục trặc trên đường:\n\n"
                        + "\n\n".join(problems)[:3000])
    log.info("Xong: %d video gửi duyệt, %d trục trặc", made, len(problems))
    return made


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Chạy cả dây chuyền một lần trong ngày")
    ap.add_argument("--dry-run", action="store_true", help="Chỉ in kế hoạch, không chạy gì")
    ap.add_argument("--skip-ideas", action="store_true", help="Không săn ý tưởng mới")
    args = ap.parse_args()
    run_daily(skip_ideas=args.skip_ideas, dry_run=args.dry_run)
    # Luôn thoát 0: lỗi đã báo qua Telegram; thoát khác 0 chỉ làm systemd báo đỏ vô ích


if __name__ == "__main__":
    main()
