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

from . import db, lang

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


def build_text(videos: list, starts: list, span: str, cfg: dict, lead: int = None, intro: float = 0.0) -> tuple:
    """(tiêu đề, mô tả, thẻ) viết bằng code — không tốn lượt gọi model. Chương có mốc thời gian
    (YouTube tự chia chương: mốc đầu 0:00, từ 3 chương, mỗi chương >= 10 giây).

    lead: chương nổi bật (nhiều lượt xem nhất tuần) -> tiêu đề MỞ BẰNG câu chuyện đó (24/11/2026: video dài #9 có 2
    lượt xem, #14 có 0 — tiêu đề "7 câu chuyện qua con số tuần 15/11–21/11" không gợi tò mò, không ai tìm như vậy).
    intro: số giây lời dẫn mở đầu (có thì thêm chương "0:00 Giới thiệu", các chương sau dời theo)."""
    from .publish import metadata
    n = len(videos)
    tail = lang.pick(vi=f"{n} câu chuyện qua con số tuần {span}", ko=f"숫자로 본 이번 주 {n}편 ({span})")
    if lead is not None and 0 <= lead < len(videos):
        head = videos[lead]["title"]           # week_videos đã thêm đơn vị nếu tiêu đề Shorts bỏ mất (chapter_title)
        title = metadata._truncate_words(f"{head} | {tail}", metadata.TITLE_MAX)
    else:   # khuôn cũ (không biết chương nào nổi bật)
        title = metadata._truncate_words(lang.pick(
            vi=f"{n} câu chuyện qua con số tuần {span} | Việt Nam, Hàn Quốc và thế giới",
            ko=f"숫자로 본 이번 주 이야기 {n}편 ({span}) | 한국과 세계"), metadata.TITLE_MAX)
    lines = [lang.pick(vi=f"{n} câu chuyện dữ liệu Việt Nam – Hàn Quốc – thế giới trong tuần {span}, mỗi câu chuyện"
                          " một chương:",
                       ko=f"{span} 한 주 동안의 데이터 이야기 {n}편, 이야기마다 한 챕터:"), ""]
    if intro > 0:
        lines.append(lang.pick(vi="0:00 Giới thiệu", ko="0:00 소개"))
    lines += [f"{ts(s + intro)} {v['title']}" for v, s in zip(videos, starts)]
    sources, music = [], []
    for v in videos:
        for l in str(v["description"] or "").splitlines():
            if l.startswith(("Nguồn:", "출처:")) and l not in sources:
                sources.append(l)
            if l.startswith(("Nhạc nền:", "배경음악:")) and l not in music:
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


def chapter_views(videos: list):
    """[lượt xem công khai] theo thứ tự `videos` (API key, 1 đơn vị) — hoặc None nếu không đọc được."""
    import os
    from .publish import youtube
    key = os.getenv("YOUTUBE_API_KEY")
    ids = [v.get("youtube_id") for v in videos if v.get("youtube_id")]
    if not key or not ids:
        return None
    try:
        stats = youtube.public_stats(ids, key)
    except Exception as exc:
        log.warning("Không đọc được lượt xem các chương: %s", exc)
        return None
    return [stats.get(v.get("youtube_id"), {}).get("views", 0) for v in videos]


def lead_chapter(videos: list, views: list = None) -> int:
    """Chỉ số chương được xem nhiều nhất trên YouTube (số công khai, API key — không tốn quota OAuth). Lỗi -> 0."""
    views = views if views is not None else chapter_views(videos)
    if not views:
        return 0
    return -max((v, -k) for k, v in enumerate(views))[1]


MAX_CHAPTERS = 8


def pick_chapters(videos: list, views, limit: int = MAX_CHAPTERS) -> tuple:
    """Kênh Hàn 2 Shorts/ngày (24/11/2026) -> tới 14 Shorts/tuần: video dài ghép hết sẽ ~10 phút, dựng gần một giờ.
    Giữ `limit` Shorts được xem NHIỀU NHẤT (không đọc được lượt xem: mới nhất), vẫn xếp theo ngày đăng.
    -> (videos, views) đã lọc."""
    if len(videos) <= limit:
        return videos, views
    order = (sorted(range(len(videos)), key=lambda k: (-views[k], -k)) if views
             else list(range(len(videos) - 1, -1, -1)))
    keep = sorted(order[:limit])
    log.info("Tuần có %d Shorts — video dài lấy %d chương xem nhiều nhất", len(videos), limit)
    return [videos[k] for k in keep], ([views[k] for k in keep] if views else views)


def intro_text(videos: list, span: str, lead: int) -> str:
    """Lời dẫn mở đầu (~10 giây) do CODE ghép từ tiêu đề các Shorts đã đăng (đã qua mọi cổng) — không số mới."""
    n, top = len(videos), videos[lead]["title"].rstrip(" .?!")
    return lang.pick(vi=f"Tuần qua con số, {span}: {n} câu chuyện. Được xem nhiều nhất tuần này: {top}. "
                        "Cùng xem lại từng câu chuyện.",
                     ko=f"숫자로 본 한 주, {span}. 이번 주 이야기는 {n}편입니다. 가장 많이 본 이야기: {top}. "
                        "하나씩 다시 살펴볼까요?")


def make_intro(videos: list, span: str, series: str, chapters: list, lead: int, concurrency: int = 3):
    """Phần mở đầu video dài: giọng kênh đọc lời dẫn (1 lượt TTS/tuần) + danh sách chương (render-web WideIntro).
    Lỗi (hết hạn mức TTS...) -> None: video dài vẫn ra như cũ, chỉ thiếu lời dẫn. -> (file mp4, số giây)."""
    from .audio import tts
    from .render import web
    try:
        wav = tts.synth(intro_text(videos, span, lead), TMP / "intro.wav")
        dur = round(max(tts.wav_duration(wav) + 0.6, 10.5), 2)    # YouTube chỉ chia chương khi mỗi chương >= 10 giây
        props = {"brand": web.brand_props(), "duration": dur, "series": series, "chapters": chapters, "lead": lead,
                 "headline": lang.pick(vi=f"{len(videos)} câu chuyện qua con số", ko=f"숫자 이야기 {len(videos)}편"),
                 "leadLabel": lang.pick(vi="xem nhiều nhất", ko="가장 많이 봄")}
        if lang.code() != "vi":
            props["lang"] = lang.code()
        raw = web.render(props, TMP / "intro_raw.mp4", concurrency=concurrency, composition="WideIntro")
        part = TMP / "part_0.mp4"
        ff("-i", raw, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "apad",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", part)
        return part, ffprobe_duration(part)
    except Exception as exc:
        log.warning("Không làm được lời dẫn mở đầu (video dài vẫn ra, không có lời dẫn): %s", exc)
        return None


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
    views = chapter_views(videos)
    videos, views = pick_chapters(videos, views, int((cfg.get("longform") or {}).get("max_chapters", MAX_CHAPTERS)))
    # giờ của người xem chính (kênh Việt +7, kênh Hàn +9 — publish.youtube.utc_offset_hours)
    tz_vn = timezone(timedelta(hours=float(cfg.get("publish", {}).get("youtube", {}).get("utc_offset_hours", 7))))
    d0 = datetime.fromisoformat(videos[0]["published_at"]).astimezone(tz_vn)
    d1 = datetime.fromisoformat(videos[-1]["published_at"]).astimezone(tz_vn)
    span = lang.pick(vi=f"{d0:%d/%m}–{d1:%d/%m}", ko=f"{d0:%m.%d}–{d1:%m.%d}")
    series = lang.pick(vi=f"TUẦN QUA CON SỐ · {span}", ko=f"숫자로 본 한 주 · {span}")
    chapters = [v["title"] for v in videos]
    TMP.mkdir(parents=True, exist_ok=True)
    lead = lead_chapter(videos, views)
    parts, starts, t, stories = [], [], 0.0, []
    for k, v in enumerate(videos, 1):
        story, audio = chapter_source(v["script_id"])
        stories.append(story)
        wide = {"story": story, "chapter": k, "chapters": chapters, "series": series}
        if lang.code() != "vi":                # Wide.tsx đọc props.lang ở cấp ngoài để chọn phông + kiểu số
            wide["lang"] = lang.code()
        raw = web.render(wide,
                         TMP / f"wide_{k}.mp4", concurrency=concurrency, composition="Wide")
        part = TMP / f"part_{k}.mp4"
        # hình của chương + TIẾNG của bản phát hành (giọng + nhạc + hiệu ứng, đã chuẩn -16 LUFS)
        ff("-i", raw, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", part)
        starts.append(t)
        t += ffprobe_duration(part)
        parts.append(part)
    intro = make_intro(videos, span, series, chapters, lead, concurrency)
    if intro:
        parts.insert(0, intro[0])
    intro_secs = intro[1] if intro else 0.0
    lst = TMP / "parts.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    OUTPUT.mkdir(exist_ok=True)
    final = OUTPUT / f"weekly_{d1:%Y-%m-%d}.mp4"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final)
    title, desc, tags = build_text(videos, starts, span, cfg, lead=lead, intro=intro_secs)
    thumb = thumbnail(stories, len(videos), span, final.with_suffix(".thumb.jpg"))
    log.info("VIDEO DÀI: %s (%.0f giây, %d chương)", final, ffprobe_duration(final), len(videos))
    return {"file": final, "title": title, "description": desc, "tags": tags, "chapters": chapters,
            "starts": starts, "video_ids": [v["id"] for v in videos], "thumb": thumb}


def thumb_path(video_file) -> Path:
    """Hình thu nhỏ nằm cạnh file video: output/weekly_2026-11-21.mp4 -> output/weekly_2026-11-21.thumb.jpg."""
    return (ROOT / video_file).with_suffix(".thumb.jpg")


def thumbnail(stories: list, count: int, span: str, out: Path) -> Path:
    """Hình thu nhỏ 1280x720 (render-web/src/Thumb.tsx): số câu chuyện + khoảng ngày + 3 khung hình THẬT của các
    Shorts trong tuần (cảnh giàu hình nhất: bản đồ > cuộc đua > biểu đồ, cùng cách chọn khung với ảnh bài viết
    Facebook). Lỗi -> None (video vẫn đăng, YouTube tự chọn hình)."""
    from .fb_post import IMAGE_KINDS, pick_frame
    from .render import web
    picked = []
    for p in stories:
        frame, kind = pick_frame(p)
        if frame is not None:
            rank = IMAGE_KINDS.index(kind) if kind in IMAGE_KINDS else len(IMAGE_KINDS)
            picked.append((rank, len(picked), {"story": {**p, "words": [], "sfx": [], "finding": None, "opening": 0},
                                                "frame": frame}))
    cards = [c for _, _, c in sorted(picked, key=lambda x: x[:2])[:3]]
    if not cards:
        return None
    props = {"brand": web.brand_props(), "count": int(count), "span": span, "cards": cards,
             "series": lang.pick(vi="TUẦN QUA CON SỐ", ko="숫자로 본 한 주"),
             "label": lang.pick(vi=["CÂU CHUYỆN", "QUA CON SỐ"], ko=["편의", "숫자 이야기"])}
    if lang.code() != "vi":
        props["lang"] = lang.code()
    pf = out.with_suffix(".props.json")
    pf.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx, env = web.node_env()
    try:
        subprocess.run([npx, "remotion", "still", "src/index.ts", "Thumb", str(out.resolve()), f"--props={pf.resolve()}",
                        "--image-format=jpeg", "--jpeg-quality=90", "--log=error"], cwd=web.WEB, env=env, check=True,
                       timeout=600, capture_output=True, shell=str(npx).endswith(".cmd"))
    except Exception as exc:
        log.warning("Không vẽ được hình thu nhỏ: %s", exc)
        return None
    finally:
        pf.unlink(missing_ok=True)
    return out


def thumbnail_for(video: dict) -> Path:
    """Dựng lại hình thu nhỏ cho một video dài ĐÃ có (bổ sung cho video dựng trước khi có tính năng này): số chương
    + khoảng ngày đọc từ chính tiêu đề, khung hình từ props Remotion còn lưu của các Shorts trong tuần đó."""
    import re
    title = video["title"] or ""
    m_n = re.search(r"\d+", title)
    m_span = re.search(r"\d{1,2}[/.]\d{1,2}\s*[–-]\s*\d{1,2}[/.]\d{1,2}", title)
    if not (m_n and m_span):
        return None
    made = datetime.fromisoformat(video["created_at"])
    con = db.connect()
    try:
        week = week_videos(con, made)
    finally:
        con.close()
    # week_videos chỉ có mốc ĐẦU (lúc dựng thật thì chưa có gì mới hơn); dựng bổ sung cho video cũ phải bỏ Shorts
    # đăng SAU video dài (ca thật 21/11: hình của tuần 13-17/11 lấy cả video điện tái tạo đăng ngày 20/11)
    week = [v for v in week if datetime.fromisoformat(v["published_at"]) <= made]
    stories = []
    for v in week:
        f = RENDER / f"web_{v['script_id']}.props.json"
        if f.exists():
            stories.append(json.loads(f.read_text(encoding="utf-8")))
    return thumbnail(stories, int(m_n.group()), m_span.group(), thumb_path(video["file"]))


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
            if result.get("thumb"):
                from .publish import youtube
                ok = youtube.can_set_thumbnails()
                tg.send_photo(result["thumb"], "🖼 Hình thu nhỏ sẽ gắn khi đăng" if ok is not False else
                              "🖼 Hình thu nhỏ đã dựng — kênh chưa xác minh số điện thoại nên YouTube chưa cho gắn;"
                              " video vẫn đăng với hình YouTube tự cắt", reply_to=mid)
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
    ap.add_argument("--thumb", type=int, metavar="ID_VIDEO",
                    help="dựng hình thu nhỏ cho video dài đã có (chỉ dựng; thêm --upload để gắn lên YouTube)")
    ap.add_argument("--upload", action="store_true", help="cùng --thumb: gắn hình lên YouTube (thay đổi công khai)")
    a = ap.parse_args()
    if a.thumb:
        from .publish import youtube
        con = db.connect()
        try:
            v = db.get_video(con, a.thumb)
        finally:
            con.close()
        out = thumb_path(v["file"]) if a.upload and thumb_path(v["file"]).exists() else thumbnail_for(v)
        print("Hình thu nhỏ:", out)
        if out and a.upload and v.get("youtube_id"):
            youtube.set_thumbnail(v["youtube_id"], out)
            print("Đã gắn lên YouTube:", v["youtube_id"])
        return
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
