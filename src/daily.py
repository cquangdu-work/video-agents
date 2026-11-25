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
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import db
from . import lang
from . import telegram_bot as tg

log = logging.getLogger("daily")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = lang.config_path()          # kênh đang chạy (CHANNEL_CONFIG; mặc định kênh Việt)
SPEC_DIR = ROOT / "data" / "specs"
OUTPUT = ROOT / "output"
LOG_DIR = ROOT / "logs"
LOCK = ROOT / "data" / "daily.lock"

MAX_FAILS_PER_SCRIPT = 2          # kịch bản dựng hỏng 2 lần thì thôi không thử nữa
PREF_WEIGHT = 2.0                 # 1 độ lệch chuẩn "người xem thích" = 2 điểm Biên tập (thang ~15-30)
FB_PREF_SHARE = 0.5               # sở thích người xem Facebook tính bằng nửa YouTube (kênh chính vẫn là YouTube)
EXIT_RETRY_LATER = 75             # bước con thoát mã này = "lỗi tạm thời của dịch vụ ngoài"
                                  # (assemble: hết quota TTS) — khớp src/assemble.py
STEP_TIMEOUT = {"ideas": 3600, "produce": 1800, "assemble": 5400, "review": 1200,  # giây
                "community": 900}


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def final_path(script_id: int) -> Path:
    return OUTPUT / f"final_{script_id}.mp4"


def videos_made_today(con, cfg: dict, now: datetime = None) -> int:
    """Số video đã gửi duyệt trong NGÀY hôm nay theo giờ của Du (daily.utc_offset_hours,
    Hàn = +9) — để chạy lại trong ngày không làm dư.

    Đếm theo ngày lịch chứ không theo "N giờ qua": hôm nào video ra muộn (lượt chạy
    bù buổi chiều vì sáng hết quota) thì sáng hôm sau vẫn phải làm video mới.
    """
    since = _today_since(cfg, now)
    # Chỉ tính Shorts ĐÃ TỚI Telegram (có tg_message_id); gửi hụt thì không tính.
    # Video dài hằng tuần (src/longform.py, script_id rỗng) không tính: thứ Bảy sáng hết
    # quota TTS thì lượt chạy bù 17:40 vẫn phải làm Shorts dù video dài đã gửi lúc 09:30.
    return con.execute("SELECT COUNT(*) FROM videos WHERE created_at >= ?"
                       " AND tg_message_id IS NOT NULL AND script_id IS NOT NULL",
                       (since,)).fetchone()[0]


def _today_since(cfg: dict, now: datetime = None) -> str:
    """0:00 hôm nay theo giờ của Du (daily.utc_offset_hours), dạng UTC ISO — để so với cột created_at."""
    tz = timezone(timedelta(hours=float(cfg["daily"].get("utc_offset_hours", 9))))
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


def todays_mix(con, cfg: dict, now: datetime = None) -> list:
    """[(mảng, dạng video)] của các Shorts đã gửi duyệt HÔM NAY — video sau trong ngày phải khác cả hai."""
    from . import learning
    from .sources.datatable import topic_family
    rows = con.execute("SELECT i.source_name, i.title FROM videos v JOIN scripts s ON s.id = v.script_id"
                       " JOIN ideas i ON i.id = s.idea_id WHERE v.created_at >= ? AND v.tg_message_id IS NOT NULL"
                       " AND v.script_id IS NOT NULL", (_today_since(cfg, now),)).fetchall()
    return [(topic_family(r["source_name"]), learning.video_kind(r["title"], r["source_name"])) for r in rows]


def clashes(c: dict, mix: list) -> bool:
    """Kịch bản trùng MẢNG hoặc trùng DẠNG (bản đồ / cuộc đua / biểu đồ / bài báo) với một video đã làm hôm nay.
    Kênh Hàn 2 video/ngày (Du chốt phương án A 24/11/2026): hai video cùng ngày phải khác nhau rõ — hai bản đồ hay hai
    video Hàn–Nhật trong một ngày là đúng kiểu "nội dung lặp khuôn" YouTube không cho kiếm tiền."""
    return any(c.get("family") == f or c.get("kind") == k for f, k in mix)


def max_script_words(cfg: dict) -> float:
    """Trần số từ của khổ video hiện tại (channel.video_seconds_max x tốc độ đọc, dư 5% như cổng
    chuẩn của Biên kịch). Cấu hình thiếu (test cũ) -> không giới hạn."""
    ch = cfg.get("channel") or {}
    if "video_seconds_max" not in ch:
        return float("inf")
    wps = float((cfg.get("pacing") or {}).get("words_per_second", 3.4))
    return 1.05 * float(ch["video_seconds_max"]) * wps


def script_words(body: str) -> int:
    """Tổng số từ lời đọc của một kịch bản (cột scripts.body là YAML danh sách cảnh)."""
    try:
        scenes = yaml.safe_load(body or "") or []
        return sum(len(str(s.get("voice", "")).split()) for s in scenes)
    except Exception:
        return 0


def script_numbers(body: str) -> int:
    """Số con số KHÁC NHAU viết bằng chữ số trong lời đọc của một kịch bản."""
    from .utils import digit_set
    try:
        scenes = yaml.safe_load(body or "") or []
        return len(digit_set(" ".join(str(s.get("voice", "")) for s in scenes)))
    except Exception:
        return 0


def opening_problems(body: str) -> list:
    """Câu mở đầu (lời cảnh 1) phạm luật kể chuyện nào (src/story.py)."""
    from .story import hook_problems
    try:
        scenes = yaml.safe_load(body or "") or []
        return hook_problems(str(scenes[0].get("voice", ""))) if scenes else []
    except Exception:
        return []


def comparison_problems(body: str, summary: str) -> list:
    """Lỗi nội dung code soát được với bảng số (crew.content_problems: so sánh sai, nêu nguyên nhân,
    "liên tục tăng" trái dãy số, hook "Vì sao…?") trong lời đọc của một kịch bản ĐÃ LƯU — kịch bản viết
    trước khi có cổng vẫn có thể đang ở trạng thái "verified"."""
    from .crew import content_problems
    try:
        scenes = yaml.safe_load(body or "") or []
        return content_problems({"scenes": [s for s in scenes if isinstance(s, dict)]}, summary)
    except Exception:
        return []


def recent_families(con, n: int = 5) -> list:
    """Mảng chủ đề (datatable.topic_family) của n Shorts gửi duyệt gần nhất, mới trước cũ sau."""
    from .sources.datatable import topic_family
    rows = con.execute(
        "SELECT i.source_name FROM videos v JOIN scripts s ON s.id = v.script_id"
        " JOIN ideas i ON i.id = s.idea_id WHERE v.tg_message_id IS NOT NULL"
        " ORDER BY v.created_at DESC, v.id DESC LIMIT ?", (n,)).fetchall()
    return [topic_family(r["source_name"]) for r in rows]


def streak(family: str, recent: list) -> int:
    """Mảng này đã chiếm bao nhiêu video LIÊN TIẾP gần nhất (0 = video gần nhất là mảng khác)."""
    k = 0
    while k < len(recent) and recent[k] == family:
        k += 1
    return k


def pick_candidates(con, cfg: dict, now: datetime = None) -> list:
    """Kịch bản đủ điều kiện dựng, theo thứ tự ưu tiên. Trả về [{"id", "score", "has_final", "family"}].

    Điều kiện: đã qua Kiểm chứng, chưa gửi duyệt lần nào, còn mới, chưa hỏng quá số lần,
    lời đọc đủ dài.
    Ưu tiên: mảng chủ đề KHÁC với chuỗi video gần nhất (không làm cùng mảng hai ngày liền nếu có
    lựa chọn khác — ca thật 13-18/11: 6/6 video là Việt–Hàn) -> cái đã dựng xong video (khỏi tốn
    công) -> điểm Biên tập + điểm "người xem thích" đã học (src/learning.py) -> mới hơn.
    """
    from . import growth, learning
    from .sources.datatable import anchored, is_fresh, topic_family
    prefs = learning.preferences()
    fb_prefs = learning.preferences("fb_preferences")
    ig_prefs = learning.preferences("ig_preferences")      # kênh Hàn: người xem Instagram (src/ig_insights.py)
    grow = growth._data()                  # ưu tiên của agent Tăng trưởng (đọc một lần)
    from . import themes                   # CHỦ ĐỀ TUẦN của video dài: còn thiếu Short thì kịch bản khớp chủ đề dựng trước
    theme = themes.wanted(con, cfg, (now.astimezone(timezone(timedelta(hours=float(
        cfg["daily"].get("utc_offset_hours", 9))))).date() if now else None))
    max_age = cfg["daily"].get("max_script_age_days", 3)
    min_words = cfg["daily"].get("min_script_words", 150)
    max_words = max_script_words(cfg)
    min_numbers = cfg["daily"].get("min_script_numbers", 4)
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=max_age)).isoformat(timespec="seconds")
    recent = recent_families(con)
    rows = con.execute(
        "SELECT s.id, s.body, i.scores, i.source_name, i.summary, i.title FROM scripts s"
        " JOIN ideas i ON i.id = s.idea_id"
        " WHERE s.status = 'verified' AND s.created_at >= ?"
        # video gửi Telegram hụt (chưa có tg_message_id) vẫn được thử gửi lại.
        # PHẢI loại script_id rỗng (video dài hằng tuần): trong SQL, `x NOT IN (…, NULL)`
        # không bao giờ đúng -> cả truy vấn ra rỗng. Ca thật 18/11: video dài #9 vào bảng
        # chiều 17/11, sáng 18/11 có 3 kịch bản đạt mà daily báo "0 video".
        " AND s.id NOT IN (SELECT script_id FROM videos WHERE script_id IS NOT NULL"
        "                  AND (tg_message_id IS NOT NULL OR status != 'pending_review'))",
        (since,)).fetchall()
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
        bad_hook = opening_problems(r["body"])
        if bad_hook:
            # Kịch bản viết trước luật kể chuyện (12/11): mở bằng "Đừng…"/"Sai lầm…" = video theo
            # mẫu + câu view, YouTube không cho kiếm tiền -> không đem đi dựng
            log.info("Bỏ qua kịch bản #%d: câu mở đầu %s", r["id"], bad_hook[0])
            continue
        wrong = comparison_problems(r["body"], r["summary"])
        if wrong:
            # Kịch bản viết trước cổng so sánh (19/11): ca thật #46 "đạt" Kiểm chứng với hook sai
            log.info("Bỏ qua kịch bản #%d: %s", r["id"], wrong[0])
            continue
        numbers = script_numbers(r["body"])
        if numbers < min_numbers:
            # Kênh "qua con số": kịch bản 1-2 con số dựng ra toàn cảnh chữ, không có biểu đồ
            log.info("Bỏ qua kịch bản #%d: lời đọc chỉ có %d con số (cần ≥ %d)",
                     r["id"], numbers, min_numbers)
            continue
        try:
            score = float(json.loads(r["scores"] or "{}").get("total", 0))
        except (ValueError, TypeError):
            score = 0.0
        family = topic_family(r["source_name"])
        # TỰ HỌC từ người xem (src/learning.py): kiểu mở đầu / mảng / dạng video nào giữ chân tốt,
        # có thưởng thăm dò cho cái ít được thử. Đơn vị độ lệch chuẩn, nhân PREF_WEIGHT điểm Biên tập.
        feats = learning.features(learning._hook_of(r["body"]), r["title"], r["source_name"])
        bonus = learning.preference_bonus(feats, prefs)
        # người xem FACEBOOK (agent Facebook, src/fb_insights.py) — nặng bằng nửa YouTube; chưa có số liệu = 0
        bonus += FB_PREF_SHARE * learning.preference_bonus(feats, fb_prefs)
        bonus += FB_PREF_SHARE * learning.preference_bonus(feats, ig_prefs)
        # agent Tăng trưởng (src/growth.py): cùng mảng + dạng với video ĐỘT BIẾN gần đây thì làm trước
        boost = growth.boost_for(feats["family"], feats["kind"], grow)
        out.append({"id": r["id"], "score": score, "has_final": final_path(r["id"]).exists(),
                    "family": family, "kind": feats["kind"],
                    # không nhắc nước của người xem (datatable.anchored) = coi như làm lại mảng hôm qua thêm một
                    # ngày: chỉ được dựng khi kịch bản có nhắc đều cùng mảng với video gần nhất
                    "streak": streak(family, recent) + (0 if anchored({"title": r["title"], "summary": r["summary"]})
                                                        else 1),
                    "fresh": is_fresh({"summary": r["summary"]}),
                    "theme": bool(theme and themes.matches(theme, r["title"], r["summary"])),
                    "long": words > max_words, "learned": bonus, "boost": boost})
    # Kịch bản DÀI hơn độ dài mới (viết trước 19/11 cho video 60-90 giây) xếp sau cùng: chỉ dựng khi
    # không còn kịch bản nào đúng khổ 45-60 giây (assemble đọc nhanh tối đa 1,12 lần vẫn ra ~80 giây)
    # số VỪA CÔNG BỐ (kosis.build_monthly_map) dựng trước nhất: giá trị của nó nằm ở chỗ ra ngay ngày công bố
    return sorted(out, key=lambda c: (c["long"], not c["fresh"], not c["theme"], c["streak"], not c["has_final"],
                                      -(c["score"] + PREF_WEIGHT * (c["learned"] + c["boost"])), -c["id"]))


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


# Lỗi đã biết -> câu giải thích + cách sửa cho tin Telegram (bản đầu chỉ báo "mã thoát 1", Du phải mở log mới biết
# — ca thật 22/11/2026: khoá Gemini kênh Hàn bị Google chặn, tin chỉ ghi "Bước ý tưởng/kịch bản lỗi (mã thoát 1)")
KNOWN_ERRORS = [
    (re.compile(r"free tier is not available|PERMISSION_DENIED|has been denied access", re.I),
     "Khoá Gemini (GEMINI_API_KEY trong .env) bị Google chặn — project không được dùng gói miễn phí. Cần đổi khoá"
     " hoặc bật thanh toán cho project đó."),
    (re.compile(r"API key not valid|API_KEY_INVALID", re.I),
     "Khoá Gemini sai hoặc đã bị xoá (GEMINI_API_KEY trong .env)."),
    (re.compile(r"RESOURCE_EXHAUSTED|\b429\b", re.I),
     "Hết hạn mức Gemini miễn phí hôm nay — lượt chạy bù buổi chiều sẽ làm tiếp."),
]


def explain(tail: str) -> str:
    """Câu giải thích cho lỗi đã biết trong mấy dòng log cuối; không nhận ra -> ""."""
    return next((msg for rx, msg in KNOWN_ERRORS if rx.search(tail or "")), "")


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


def acquire_lock(max_age_hours: float = 5) -> bool:
    """Một lúc chỉ MỘT lượt daily. Hai lượt chạy chồng (timer + gõ tay, hoặc hai phiên
    làm việc cùng lúc) sẽ ghi đè file giọng của nhau và đốt quota gấp đôi.
    Khoá cũ hơn max_age_hours coi như lượt trước chết giữa chừng -> dọn đi."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - LOCK.stat().st_mtime > max_age_hours * 3600:
            LOCK.unlink()
    except OSError:
        pass                                    # chưa có khoá: bình thường
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def run_daily(skip_ideas: bool = False, dry_run: bool = False, runner=run_step) -> int:
    """Trả về số video đã gửi duyệt trong lượt chạy này."""
    if not dry_run and not acquire_lock():
        log.warning("Đang có một lượt daily khác chạy (%s) — lượt này thoát.", LOCK)
        return 0
    cfg, con = load_config(), db.connect()
    if not dry_run:
        try:
            from . import backup
            backup.snapshot()              # bản chụp DB mỗi ngày trên VM (giữ 14 bản) — src/backup.py
        except Exception as exc:
            log.warning("Sao lưu DB lỗi: %s", exc)
        try:
            from . import gemini_key       # khoá Gemini chính bị Google chặn -> chạy bằng khoá dự phòng
            gemini_key.ensure()
        except Exception as exc:
            log.warning("Không kiểm được khoá Gemini: %s", exc)
    try:
        return _run_daily(cfg, con, skip_ideas, dry_run, runner)
    finally:
        con.close()      # Windows: kết nối mở giữ khóa file DB
        if not dry_run:
            LOCK.unlink(missing_ok=True)


def videos_wanted(cfg: dict, now: datetime = None) -> int:
    """Số video mỗi ngày. Có `cadence_since` (ngày đổi nhịp, giờ của Du) thì TRƯỚC ngày đó vẫn 1 video — kênh Hàn
    lên 2 video/ngày từ lượt 07:30 ngày 25/11/2026; không để lượt chạy bù 18:40 hôm trước làm sớm một video."""
    want = int(cfg["daily"].get("videos_per_day", 1))
    since = str(cfg["daily"].get("cadence_since") or "")
    if since:
        tz = timezone(timedelta(hours=float(cfg["daily"].get("utc_offset_hours", 9))))
        if (now or datetime.now(timezone.utc)).astimezone(tz).strftime("%Y-%m-%d") < since:
            return 1
    return want


def _run_daily(cfg, con, skip_ideas, dry_run, runner) -> int:
    want = videos_wanted(cfg)
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"daily_{datetime.now():%Y-%m-%d}.log"

    already = videos_made_today(con, cfg)
    if already >= want:
        log.info("Hôm nay đã gửi duyệt %d video — không làm thêm.", already)
        return 0

    problems = []
    if not skip_ideas and not dry_run:
        ok, tail = runner("Săn ý tưởng + viết kịch bản", "ideas",
                          ["-m", "src.main", "--no-telegram"], log_file)
        if not ok:      # vẫn đi tiếp: có thể còn kịch bản tốt từ hôm trước
            hint = explain(tail)
            problems.append(f"Bước ý tưởng/kịch bản lỗi ({tail.splitlines()[0]})" + (f"\n→ {hint}" if hint else ""))

    candidates = pick_candidates(con, cfg)
    if dry_run:
        print(f"Cần {want - already} video. Ứng viên theo thứ tự ưu tiên:")
        for c in candidates:
            print(f"  kịch bản #{c['id']} (mảng {c['family']}, điểm {c['score']}, "
                  f"{'đã có video' if c['has_final'] else 'chưa dựng'}):"
                  f" {' -> '.join(s[0] for s in plan_steps(c['id']))}")
        if not candidates:
            print("  (không có kịch bản nào đủ điều kiện)")
        return 0

    made, attempts = 0, 0
    mix = todays_mix(con, cfg)
    skipped = []
    for c in candidates:
        if made >= want - already or attempts >= int(cfg["daily"].get("max_attempts", 2)):
            break
        if clashes(c, mix):
            skipped.append(c["id"])
            continue
        attempts += 1
        failed, retry_later = None, False
        for name, key, args in plan_steps(c["id"]):
            ok, tail = runner(name, key, args, log_file)
            if not ok:
                retry_later = tail.splitlines()[:1] == [f"mã thoát {EXIT_RETRY_LATER}"]
                hint = explain(tail)
                failed = f"Kịch bản #{c['id']} hỏng ở bước “{name}”: {tail}" + (f"\n→ {hint}" if hint else "")
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
            mix.append((c["family"], c["kind"]))

    # Agent Cộng đồng (src/community.py): đọc bình luận mới mỗi sáng, MỘT lần mỗi ngày, không ảnh hưởng
    # việc ra video (lỗi thì chỉ ghi log)
    today = datetime.now().strftime("%Y-%m-%d")
    if (cfg.get("community") or {}).get("enabled") and db.get_state(con, "community_day") != today:
        ok, tail = runner("Cộng đồng (đọc bình luận)", "community", ["-m", "src.community"], log_file)
        db.set_state(con, "community_day", today)
        if not ok:
            log.warning("Agent Cộng đồng lỗi (không ảnh hưởng video): %s", tail.splitlines()[:1])

    if made + already < want and skipped and made + already > 0:
        problems.append(f"Hôm nay {made + already}/{want} video: kịch bản còn lại ({', '.join(f'#{i}' for i in skipped)})"
                        " trùng mảng hoặc dạng với video đã làm hôm nay — để dành cho ngày sau.")
    if made == 0 and already == 0:
        reason = "\n\n".join(problems) if problems else "Không có kịch bản nào qua được Kiểm chứng."
        tg.send_message(f"⚠️ Hôm nay chưa có video để duyệt.\n\n{reason}"[:3500]
                        + f"\n\nChi tiết: logs/{log_file.name}")
    elif problems:
        tg.send_message(("ℹ️ Đã gửi video, nhưng có trục trặc trên đường:\n\n" if made else "ℹ️ Lượt chạy bù:\n\n")
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
