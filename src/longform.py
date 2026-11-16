"""Video DÀI hằng tuần (16:9): ghép các Shorts đã đăng trong tuần thành một video nhiều chương.

    python -m src.longform              # dựng + gửi Du duyệt qua Telegram
    python -m src.longform --no-send    # chỉ dựng (xem file trong output/)

Vì sao: ngưỡng kiếm tiền YouTube từ 1/2/2027 là 1.000 người đăng ký + 8.000 giờ xem/năm HOẶC
20 triệu lượt xem Shorts/90 ngày — nhánh giờ xem của video dài dễ đạt hơn nhiều, và quảng cáo
video dài trả cao hơn Shorts. Video này KHÔNG tốn thêm lần gọi TTS nào: tiếng lấy từ bản phát
hành của từng Shorts, hình do Remotion vẽ lại ở bố cục ngang (render-web/src/Wide.tsx).

Duyệt và đăng dùng lại luồng của Shorts (bảng videos, nút ✅/❌, src/review.py) — bản ghi video
dài có script_id rỗng, không đẩy TikTok.
"""
import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

log = logging.getLogger("longform")

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "data" / "render"
OUTPUT = ROOT / "output"
TMP = ROOT / "data" / "tmp" / "longform"
MIN_CHAPTERS = 3
TG_LIMIT = 48 * 1024 * 1024        # bot Telegram nhận tối đa 50 MB


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True)


# ------------------------------------------------------------------ chọn chương
def week_videos(con, now: datetime, days: int = 7) -> list:
    """Shorts đã đăng (có trên YouTube) trong `days` ngày qua, cũ trước mới sau."""
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        "SELECT v.*, i.title AS idea_title FROM videos v LEFT JOIN scripts s ON s.id = v.script_id"
        " LEFT JOIN ideas i ON i.id = s.idea_id WHERE v.status='published' AND v.script_id IS NOT NULL"
        " AND v.youtube_id IS NOT NULL AND v.published_at >= ? ORDER BY v.published_at", (since,)).fetchall()
    return [dict(r, title=chapter_title(dict(r))) for r in rows]


def chapter_title(v: dict) -> str:
    """Tiêu đề chương = tiêu đề Shorts, nhưng THÊM đơn vị nếu tiêu đề cũ bỏ mất (Shorts đăng trước
    luật metadata.title_drops_unit, vd video #6 "Vốn FDI… gấp 5,06 lần" khi số là % GDP)."""
    from .publish import metadata
    unit = metadata.title_drops_unit(v["title"], {"title": v.get("idea_title") or ""})
    return f"{v['title'].rstrip()} ({unit})" if unit else v["title"]


def chapter_source(script_id: int) -> tuple:
    """(props Remotion, file có tiếng) KHỚP NHAU về thời gian cho một Shorts.

    Shorts dựng bằng engine Remotion: dùng thẳng props + bản phát hành. Shorts đời Manim (trước
    16/11) hoặc props lệch thời lượng: dựng lại bằng `assemble --out` (giọng đã có sẵn trong bộ
    đệm -> không tốn TTS), lấy props + tiếng của chính bản dựng lại đó."""
    props = RENDER / f"web_{script_id}.props.json"
    final = OUTPUT / f"final_{script_id}.mp4"
    meta_path = RENDER / f"audio_{script_id}" / "meta.json"
    try:
        engine = json.loads(meta_path.read_text(encoding="utf-8")).get("engine")
    except (OSError, ValueError):
        engine = None
    if engine == "web" and props.exists() and final.exists():
        p = json.loads(props.read_text(encoding="utf-8"))
        if abs(ffprobe_duration(final) - float(p["duration"])) < 0.12:
            return p, final
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / f"src_{script_id}.mp4"
    if out.exists() and props.exists():           # đã dựng lại ở lần chạy trước: dùng lại
        p = json.loads(props.read_text(encoding="utf-8"))
        if abs(ffprobe_duration(out) - float(p["duration"])) < 0.12:
            return p, out
    log.info("Shorts #%s chưa có bản Remotion khớp — dựng lại (không tốn TTS)", script_id)
    subprocess.run([sys.executable, "-m", "src.assemble", str(script_id), "--engine", "web", "--out", str(out)],
                   cwd=ROOT, check=True)
    return json.loads(props.read_text(encoding="utf-8")), out


# ------------------------------------------------------------------ mô tả
def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def build_text(videos: list, starts: list, span: str, cfg: dict) -> tuple:
    """(tiêu đề, mô tả, thẻ) viết bằng code — không tốn lượt gọi model. Chương có mốc thời gian
    (YouTube tự chia chương: mốc đầu 0:00, từ 3 chương, mỗi chương >= 10 giây)."""
    from .publish import metadata
    n = len(videos)
    lead = min((v["title"] for v in videos), key=len)
    title = metadata._truncate_words(f"{n} câu chuyện qua con số tuần {span}: {lead}", metadata.TITLE_MAX)
    lines = [f"{n} câu chuyện dữ liệu Việt Nam – Hàn Quốc – thế giới trong tuần {span}, mỗi câu chuyện"
             " một chương:", ""]
    lines += [f"{ts(s)} {v['title']}" for v, s in zip(videos, starts)]
    sources, music = [], []
    for v in videos:
        for l in str(v["description"] or "").splitlines():
            if l.startswith("Nguồn:") and l not in sources:
                sources.append(l)
            if l.startswith("Nhạc nền:") and l not in music:
                music.append(l)
    pub = cfg.get("publish", {})
    tail = [*sources, "", *music]
    if pub.get("disclosure"):
        tail += ["", pub["disclosure"]]
    tail += ["", " ".join(h for h in pub.get("hashtags_fixed", []) if h.lower() != "#shorts")]
    desc = "\n".join(lines + [""] + tail).strip()[: metadata.DESCRIPTION_MAX]
    tags, seen = [], set()
    for v in videos:
        for t in json.loads(v["tags"] or "[]"):
            if t.lower() not in seen and sum(len(x) + 3 for x in tags) + len(t) < metadata.TAGS_MAX_CHARS:
                tags.append(t)
                seen.add(t.lower())
    return title, desc, tags


# ------------------------------------------------------------------ dựng
def build(now: datetime = None, concurrency: int = 3) -> dict:
    from .render import web
    from .main import load_config
    now = now or datetime.now(timezone.utc)
    cfg = load_config()
    con = db.connect()
    try:
        videos = week_videos(con, now)
    finally:
        con.close()
    if len(videos) < MIN_CHAPTERS:
        raise RuntimeError(f"Tuần này mới có {len(videos)} Shorts đã đăng (cần >= {MIN_CHAPTERS})")
    tz_vn = timezone(timedelta(hours=7))
    d0 = datetime.fromisoformat(videos[0]["published_at"]).astimezone(tz_vn)
    d1 = datetime.fromisoformat(videos[-1]["published_at"]).astimezone(tz_vn)
    span = f"{d0:%d/%m}–{d1:%d/%m}"
    series = f"TUẦN QUA CON SỐ · {span}"
    chapters = [v["title"] for v in videos]
    TMP.mkdir(parents=True, exist_ok=True)
    parts, starts, t = [], [], 0.0
    for k, v in enumerate(videos, 1):
        story, audio = chapter_source(v["script_id"])
        raw = web.render({"story": story, "chapter": k, "chapters": chapters, "series": series},
                         TMP / f"wide_{k}.mp4", concurrency=concurrency, composition="Wide")
        part = TMP / f"part_{k}.mp4"
        # hình của chương + TIẾNG của bản phát hành (giọng + nhạc + hiệu ứng, đã chuẩn -16 LUFS)
        ff("-i", raw, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", part)
        starts.append(t)
        t += ffprobe_duration(part)
        parts.append(part)
    lst = TMP / "parts.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    OUTPUT.mkdir(exist_ok=True)
    final = OUTPUT / f"weekly_{d1:%Y-%m-%d}.mp4"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final)
    title, desc, tags = build_text(videos, starts, span, cfg)
    log.info("VIDEO DÀI: %s (%.0f giây, %d chương)", final, ffprobe_duration(final), len(videos))
    return {"file": final, "title": title, "description": desc, "tags": tags, "chapters": chapters,
            "starts": starts, "video_ids": [v["id"] for v in videos]}


def checks(path: Path) -> list:
    """Kiểm định phần dùng được cho video dài: độ dài, khung đen, âm lượng."""
    from . import qc
    d = ffprobe_duration(path)
    return [{"name": "Độ dài", "value": f"{d / 60:.1f} phút", "ok": d >= 180},
            qc.check_black_frames(path), qc.check_loudness(path)]


def preview(path: Path) -> Path:
    """Bản xem trước nhẹ cho Telegram (bản đầy đủ chỉ tải lên YouTube khi Du bấm ✅)."""
    out = TMP / "preview.mp4"
    for height, crf in ((720, 30), (540, 32), (360, 34)):
        ff("-i", path, "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out)
        if out.stat().st_size < TG_LIMIT:
            break
    return out


def send(result: dict) -> int:
    from . import telegram_bot as tg
    con = db.connect()
    try:
        res = checks(result["file"])
        cur = con.execute(
            "INSERT INTO videos (script_id, file, title, description, tags, qc, created_at)"
            " VALUES (NULL,?,?,?,?,?,?)",
            (result["file"].relative_to(ROOT).as_posix(), result["title"], result["description"],
             json.dumps(result["tags"], ensure_ascii=False), json.dumps(res, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        con.commit()
        vid = cur.lastrowid
        qc_line = " · ".join(f"{'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}" for c in res)
        caption = (f"🎞️ VIDEO DÀI #{vid} chờ duyệt ({len(result['chapters'])} chương, ghép Shorts tuần này)\n"
                   f"📌 {result['title']}\n\nKiểm định: {qc_line}\n"
                   "Đây là bản xem trước nén nhẹ; bấm ✅ thì bản đầy đủ 1080p được tải lên YouTube.")
        mid = tg.send_video(preview(result["file"]), caption,
                            buttons=[[("✅ Duyệt đăng", f"ok:{vid}"), ("❌ Loại", f"no:{vid}")]])
        if mid:
            db.update_video(con, vid, tg_message_id=mid)
            tg.send_message("Mô tả sẽ đăng kèm:\n\n" + result["description"], reply_to=mid)
        return vid
    finally:
        con.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="Video dài hằng tuần")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    try:
        result = build(concurrency=a.concurrency)
    except RuntimeError as exc:
        print(f"Bỏ qua tuần này: {exc}")
        return
    print(result["file"])
    if not a.no_send:
        print("Đã gửi duyệt video dài #%s" % send(result))


if __name__ == "__main__":
    main()
