"""Bước DU DUYỆT qua Telegram + agent Đăng bài (giai đoạn 4).

    python -m src.review send 6       # kiểm định -> viết tiêu đề/mô tả -> gửi video kèm nút bấm
    python -m src.review listen       # chạy nền: chờ Du bấm nút rồi xử lý (dùng trên VM)
    python -m src.review listen --once   # xử lý các nút đã bấm rồi thoát (để thử)

Luồng:
    send:   final_<id>.mp4 --Kiểm định--> --metadata--> Telegram [✅ Duyệt đăng] [❌ Loại]
    listen: ✅ -> đăng (mode manual: gửi gói file + chữ để Du tự đăng;
                        mode api: tự upload YouTube)
            ❌ -> đánh dấu loại; Du trả lời tin video để ghi lý do

Nguyên tắc: KHÔNG có đường nào tới bước đăng mà không qua nút ✅ của Du
(luật "không tự động hoá 100%" trong CLAUDE.md).
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import db, lang
from . import telegram_bot as tg

log = logging.getLogger("review")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONFIG_PATH = lang.config_path()          # kênh đang chạy (CHANNEL_CONFIG; mặc định kênh Việt)

_YT_LINK = re.compile(r"(?:youtu\.be/|youtube\.com/(?:shorts/|watch\?v=|live/))([\w-]{11})")
_CALLBACK = re.compile(r"^(ok|no|done|retry|tt|fb|fp|ig|ip):(\d+)$")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------- Gửi duyệt
def format_review_caption(video_id: int, script_id: int, meta: dict, checks: list,
                          second_line: str = None) -> str:
    qc_line = " · ".join(f"{'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}" for c in checks)
    lines = [f"🎬 Video #{video_id} chờ duyệt (kịch bản #{script_id})",
             f"📌 {meta['title']}"]
    if qc_line:
        lines += ["", f"Kiểm định: {qc_line}"]
    if second_line:
        lines.append(second_line)
    lines += [f"⚠️ {w}" for w in meta.get("warnings", [])]
    lines += ["", "Trả lời (reply) tin này để ghi chú hoặc lý do loại."]
    return "\n".join(lines)


def send_for_review(script_id: int, force: bool = False, skip_qc: bool = False):
    """Kiểm định + viết metadata + gửi Telegram. Trả về id video, hoặc None nếu bị chặn."""
    cfg, con = load_config(), db.connect()
    try:
        return _send_for_review(cfg, con, script_id, force, skip_qc)
    finally:
        con.close()      # Windows: kết nối mở giữ khóa file DB


def second_source_line(row: dict, cfg: dict):
    """Dòng "Nguồn 2" cho tin nhắn duyệt: lấy từ hồ sơ kiểm chứng; kịch bản viết trước khi có
    bước này thì đối chiếu ngay lúc gửi. Lỗi thì bỏ dòng, không chặn việc gửi duyệt."""
    from . import second_source
    try:
        result = (json.loads(row.get("factcheck") or "{}") or {}).get("second_source")
        if not result:
            idea = {k: row.get(k) for k in ("summary", "source_name")}
            result = second_source.check(idea, second_source.scale_for(row.get("summary"), cfg))
        return second_source.review_line(result)
    except Exception as exc:
        log.warning("Không lấy được dòng nguồn thứ hai: %s", exc)
        return None


def music_credit(script_id: int):
    """Tên bài nhạc nền mà assemble đã ghi vào meta.json (video không nhạc -> None)."""
    path = ROOT / "data" / "render" / f"audio_{script_id}" / "meta.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("music_credit")
    except (OSError, ValueError):
        return None


def _send_for_review(cfg, con, script_id, force, skip_qc):
    from .publish import metadata

    row = db.get_script_with_idea(con, script_id)
    if not row:
        print(f"Không có kịch bản #{script_id} trong DB.")
        return None
    video_path = OUTPUT / f"final_{script_id}.mp4"
    if not video_path.exists():
        print(f"Chưa có {video_path.name} — chạy trước: python -m src.assemble {script_id}")
        return None
    if row["script_status"] != "verified" and not force:
        print(f"Kịch bản #{script_id} chưa qua Kiểm chứng (status={row['script_status']}) — không gửi.")
        return None

    checks = []
    if not skip_qc:
        from . import qc
        checks = qc.collect_checks(script_id)
        if not all(c["ok"] for c in checks) and not force:
            from . import learning           # lỗi dựng cũng là bài học (agent Sản xuất / báo cáo tuần)
            learning.record_problems(con, [f"{c['name']}: {c['value']}" for c in checks if not c["ok"]],
                                     "qc", script_id=script_id)
            for c in checks:
                print(f"  {'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}")
            print("Kiểm định CHƯA ĐẠT — không gửi duyệt (thêm --force nếu vẫn muốn gửi).")
            return None

    scenes = yaml.safe_load(row["body"]) or []
    hooks = json.loads(row["hooks"] or "[]")
    idea = {k: row[k] for k in ("title", "angle", "summary", "source_url", "source_name")}
    meta = metadata.build_metadata(idea, scenes, hooks, cfg, music_credit(script_id))

    video_id = db.upsert_video(con, script_id, video_path.relative_to(ROOT).as_posix(),
                               meta["title"], meta["description"], meta["tags"], checks)
    mid = tg.send_video(
        video_path, format_review_caption(video_id, script_id, meta, checks,
                                          second_source_line(row, cfg)),
        buttons=[[("✅ Duyệt đăng", f"ok:{video_id}"), ("❌ Loại", f"no:{video_id}")]])
    if not mid:
        # Trả None (lệnh thoát mã 1) để chuỗi hằng ngày biết là CHƯA tới tay Du và thử lại
        print(f"Đã lưu video #{video_id} nhưng KHÔNG gửi được Telegram — chạy lại lệnh send.")
        return None
    db.update_video(con, video_id, tg_message_id=mid)
    tg.send_message("Mô tả sẽ đăng kèm:\n\n" + meta["description"], reply_to=mid)
    if lang.code() != "vi":
        # Kênh tiếng Hàn: bản dịch tiếng Việt để Du duyệt nhanh (dịch máy — chỉ để hiểu nội dung; mọi con số
        # đã được code đối chiếu với nguồn trước khi tới đây)
        from .crew import translate_for_review
        voices = [str(s.get("voice") or "") for s in scenes if isinstance(s, dict) and s.get("voice")]
        tr = translate_for_review(voices, meta["title"], meta["description"])
        if tr:
            tg.send_message("🇻🇳 Bản dịch để duyệt (máy dịch — chỉ để hiểu nội dung; số liệu đã được code đối chiếu"
                            " với nguồn):\n\n" + tr[:3500], reply_to=mid)
    try:
        prepare_fb_post(con, video_id, script_id, row, scenes, cfg, mid)
    except Exception:                           # bài viết là phần thêm: lỗi không được chặn video
        log.exception("Không soạn được bài viết Facebook cho video #%s", video_id)
    try:
        prepare_ig_post(con, video_id, script_id, row, scenes, cfg, mid, tags=meta.get("tags") or [])
    except Exception:
        log.exception("Không soạn được bài viết Instagram cho video #%s", video_id)
    print(f"Đã gửi video #{video_id} vào Telegram, chờ Du duyệt.")
    return video_id


# ---------------------------------------------------------------- Đăng bài
def _publish_manual(con, video: dict, cfg: dict) -> None:
    """Gửi 'gói đăng bài': file gốc + tiêu đề/mô tả chạm-để-copy. Du tự đăng."""
    yt = cfg["publish"]["youtube"]
    tg.send_document(ROOT / video["file"], caption=f"📦 File gốc video #{video['id']} — tải về rồi đăng")
    text = (f"<b>Tiêu đề</b> (chạm để copy)\n{tg.code(video['title'])}\n\n"
            f"<b>Mô tả</b>\n{tg.code(video['description'])}\n\n")
    if yt.get("contains_synthetic_media", True):
        text += "Khi đăng: bật mục khai báo <b>nội dung có AI / đã chỉnh sửa</b> trong app.\n\n"
    text += "Đăng xong: gửi link video vào đây, hoặc bấm nút dưới."
    tg.send_message(text, as_html=True,
                    buttons=[[("📤 Đã đăng xong", f"done:{video['id']}")]])


def _publish_api(con, video: dict, cfg: dict) -> None:
    """Tự upload YouTube. Lỗi thì trả video về 'approved' và đưa nút Thử lại."""
    from .publish import youtube

    yt = cfg["publish"]["youtube"]
    # Chốt chống upload trùng: chỉ một lượt được chuyển approved -> publishing
    if not db.transition_video(con, video["id"], "approved", "publishing"):
        return
    try:
        # mỗi khung giờ một video: khung đã có video khác hẹn thì lùi sang ngày kế tiếp (_taken_times)
        taken = _taken_times(con, "youtube", long=not video.get("script_id"))
        res = youtube.upload(ROOT / video["file"], video["title"], video["description"],
                             video["tags"], yt, publish_at=youtube.compute_publish_at(yt, taken=taken))
    except youtube.YouTubeAuthError as exc:
        # Chưa cấp quyền / token hết hạn: thử lại cũng vô ích -> gửi gói để Du tự đăng hôm nay,
        # kèm cách sửa. Video về lại 'approved' nên nút "Đã đăng xong" của gói vẫn dùng được.
        db.transition_video(con, video["id"], "publishing", "approved")
        tg.send_message(f"⚠️ Chưa upload tự động được video #{video['id']}: {exc}\n"
                        "Gửi gói để Du tự đăng lần này. Cách bật upload tự động: mục"
                        " “Đăng tự động qua API” trong README.")
        _publish_manual(con, video, cfg)
        return
    except Exception as exc:
        log.exception("Upload YouTube lỗi")
        db.transition_video(con, video["id"], "publishing", "approved")
        tg.send_message(f"⚠️ Upload video #{video['id']} lỗi:\n{exc}",
                        buttons=[[("🔁 Thử lại", f"retry:{video['id']}")]])
        return
    thumb_note = ""
    if not video.get("script_id"):          # video dài (src/longform.py): không phải Shorts
        res["url"] = f"https://youtu.be/{res['id']}"
        thumb = (ROOT / video["file"]).with_suffix(".thumb.jpg")      # longform.thumb_path
        if thumb.exists() and youtube.can_set_thumbnails() is False:
            thumb_note = (f"\nℹ️ Chưa gắn hình thu nhỏ tự dựng: kênh chưa xác minh số điện thoại (YouTube Studio → Cài"
                          f" đặt → Kênh → Điều kiện sử dụng tính năng). Xác minh xong, gắn bằng: python -m src.longform"
                          f" --thumb {video['id']} --upload")
        elif thumb.exists():
            try:
                youtube.set_thumbnail(res["id"], thumb)
                thumb_note = "\n🖼 Đã gắn hình thu nhỏ tự dựng"
            except Exception as exc:
                log.warning("Gắn hình thu nhỏ lỗi: %s", exc)
                thumb_note = f"\n⚠️ Chưa gắn được hình thu nhỏ: {exc}"
    db.update_video(con, video["id"], youtube_id=res["id"], youtube_url=res["url"],
                    youtube_privacy=res["privacy"])
    db.transition_video(con, video["id"], "publishing", "published")
    log.info("Đã upload video #%d lên YouTube: %s (%s, hẹn %s)", video["id"], res["url"],
             res["privacy"], res["publish_at"] or "không")

    msg = f"🚀 Đã upload video #{video['id']}:\n{res['url']}\nChế độ hiển thị: {res['privacy']}{thumb_note}"
    if res["publish_at"]:
        # nhớ giờ hẹn: quá giờ mà video vẫn riêng tư (project chưa audit) thì bot báo Du
        db.set_state(con, f"yt_publish_at_{video['id']}", res["publish_at"])
        msg += f"\nHẹn công khai lúc {_local_times(res['publish_at'], yt)}"
    if res["privacy"] != res["requested_privacy"]:
        msg += (f"\n\n⚠️ Yêu cầu “{res['requested_privacy']}” nhưng YouTube đặt “{res['privacy']}”."
                " Nhiều khả năng dự án API chưa qua audit nên video bị khoá riêng tư —"
                " xem mục YouTube trong README.")
    elif res["privacy"] == "private" and not res["publish_at"]:
        msg += "\nVideo đang RIÊNG TƯ — vào YouTube Studio chuyển Công khai khi sẵn sàng."
    tg.send_message(msg)
    try:
        from .publish import playlists      # danh sách phát theo dạng video; lỗi không ảnh hưởng việc đăng
        playlists.add(con, db.get_video(con, video["id"]), cfg)
    except Exception as exc:
        log.warning("Chưa thêm video #%s vào danh sách phát: %s", video["id"], exc)


def _taken_times(con, kind: str, now: datetime = None, long: bool = False) -> set:
    """Các giờ (UTC "…Z") đã có video hẹn đăng trong TƯƠNG LAI trên một nền tảng — để video sau không hẹn trùng khung
    (compute_publish_at lùi sang ngày kế tiếp). Ca thật 21/11: hai video kênh Hàn duyệt cùng lúc, cùng hẹn 19:00.

    YouTube: Shorts chỉ tránh Shorts, video dài (script_id rỗng, `long`) chỉ tránh video dài — hai loại nằm ở hai kệ
    khác nhau nên không giành người xem; cho video dài thứ Bảy chiếm khung 19:00 thì mọi Shorts sau đó lùi một ngày."""
    now = now or datetime.now(timezone.utc)
    z = lambda v: datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    if kind == "youtube":
        rows = con.execute("SELECT s.value, v.id, v.script_id FROM state s LEFT JOIN videos v"
                           " ON s.key = 'yt_publish_at_' || v.id WHERE s.key LIKE 'yt_publish_at_%'").fetchall()
        vals = [v for v, vid, sid in rows if vid is None or (sid is None) == bool(long)]
    elif kind == "fb_post":
        vals = [v for (v,) in con.execute("SELECT value FROM state WHERE key LIKE 'fbpost_at_%'")]
    elif kind == "instagram":
        vals = [v for (v,) in con.execute("SELECT instagram_due FROM videos WHERE instagram_id IS NULL")]
    elif kind == "ig_post":
        vals = [v for (v,) in con.execute("SELECT ig_post_due FROM videos WHERE ig_post_id IS NULL")]
    else:                                              # facebook (Reel)
        vals = [v for (v,) in con.execute("SELECT facebook_at FROM videos WHERE facebook_at IS NOT NULL")]
    out = set()
    for v in vals:
        try:
            t = z(v)
        except (TypeError, ValueError):
            continue
        if t > now:
            out.add(t.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return out


def _local_times(utc_iso: str, yt: dict) -> str:
    """'2026-11-13T12:00:00Z' -> '19:00 13/11 giờ Việt Nam (21:00 giờ Hàn)'."""
    t = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    if lang.code() == "ko":                  # kênh Hàn hẹn theo giờ Hàn (utc_offset_hours 9) — không ghi "giờ Việt Nam"
        return f"{t + timedelta(hours=9):%H:%M %d/%m} giờ Hàn"
    vn = t + timedelta(hours=float(yt.get("utc_offset_hours", 7)))
    return f"{vn:%H:%M %d/%m} giờ Việt Nam ({t + timedelta(hours=9):%H:%M} giờ Hàn)"


def publish(con, video: dict, cfg: dict) -> None:
    if video["status"] != "approved":       # không bao giờ đăng thứ chưa được Du duyệt
        raise ValueError(f"Video #{video['id']} chưa được duyệt (status={video['status']})")
    mode = cfg["publish"]["youtube"].get("mode", "manual")
    (_publish_api if mode == "api" else _publish_manual)(con, video, cfg)
    if video.get("script_id"):              # video dài 16:9 không hợp TikTok / Reels
        push_tiktok(con, video, cfg)
        push_facebook(con, video, cfg)
        push_fb_post(con, video, cfg)
        schedule_instagram(con, video, cfg)
        schedule_ig_post(con, video, cfg)


# --------------------------------------------------------- bài viết Facebook (src/fb_post.py)
def _fb_post_cfg(cfg: dict) -> dict:
    fcfg = cfg["publish"].get("facebook") or {}
    return {**fcfg, **(fcfg.get("posts") or {})} if (fcfg.get("enabled") and (fcfg.get("posts") or {}).get("enabled")) \
        else {}


def prepare_fb_post(con, video_id: int, script_id: int, row: dict, scenes: list, cfg: dict, reply_to) -> None:
    """Lúc gửi video duyệt: soạn bài viết Facebook (chữ + ảnh) và gửi xem trước ngay dưới video. ✅ ở video là duyệt cả
    bài; Du trả lời tin xem trước bằng câu khác -> thành nội dung bài. Chưa bật / chưa kết nối Trang -> bỏ qua."""
    from . import fb_post
    from .publish import facebook
    pcfg = _fb_post_cfg(cfg)
    if not pcfg or not facebook.connected():
        return
    voices = [str(s.get("voice") or "") for s in scenes if isinstance(s, dict) and s.get("voice")]
    idea = {k: row.get(k) for k in ("title", "summary", "source_url", "source_name")}
    text = fb_post.draft(idea, voices, cfg)
    if not text:
        tg.send_message("ℹ️ Bài viết Facebook kèm video này không qua được cổng kiểm số liệu sau 2 lần viết — chỉ"
                        " đăng Reel.", reply_to=reply_to)
        return
    text = fb_post.with_hashtags(text, cfg)
    img = fb_post.image(script_id)
    if img:
        tg.send_photo(img, caption="📝 Ảnh của bài viết Facebook (đăng kèm video khi bấm ✅)", reply_to=reply_to)
    msg = tg.send_message("📝 Bài viết Facebook sẽ đăng kèm (bấm ✅ ở video là duyệt cả bài này; TRẢ LỜI tin này bằng"
                          " nội dung khác để sửa):\n\n" + text, reply_to=reply_to)
    db.update_video(con, video_id, fb_post=text, fb_post_image=str(img) if img else None, fb_post_msg=msg)


def push_fb_post(con, video: dict, cfg: dict) -> None:
    """Sau ✅: đăng bài viết đã duyệt lên Trang, hẹn giờ publish.facebook.posts.post_time_local. Mỗi video một lần."""
    from .publish import facebook, youtube
    pcfg = _fb_post_cfg(cfg)
    key = f"fbpost_{video['id']}"
    if not pcfg or not video.get("fb_post") or db.get_state(con, key) or not facebook.connected():
        return
    img = video.get("fb_post_image")
    if not img or not Path(img).exists():
        tg.send_message(f"ℹ️ Bài viết Facebook của video #{video['id']} thiếu ảnh — không đăng.")
        return
    iso = youtube.compute_publish_at({**pcfg, "publish_time_local": pcfg.get("post_time_local", "11:30")},
                                     taken=_taken_times(con, "fb_post"))
    at = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None
    db.set_state(con, key, "posting")
    try:
        res = facebook.post_photo(Path(img), video["fb_post"], at)
    except Exception as exc:
        log.exception("Đăng bài viết Facebook lỗi")
        db.set_state(con, key, "")
        tg.send_message(f"⚠️ Bài viết Facebook của video #{video['id']} lỗi:\n{exc}",
                        buttons=[[("🔁 Thử lại bài viết", f"fp:{video['id']}")]])
        return
    db.set_state(con, key, res["id"])
    if iso and res["scheduled"]:
        db.set_state(con, f"fbpost_at_{video['id']}", iso)       # giờ đã hẹn (khung khác không dùng trùng)
    db.update_video(con, video["id"], fb_post_id=res["id"])
    when = f"hẹn đăng lúc {_local_times(iso, pcfg)}" if res["scheduled"] else "đã đăng"
    tg.send_message(f"📝 Bài viết Facebook của video #{video['id']} {when}.")


# --------------------------------------------------------- Instagram Reels (src/publish/instagram.py, kênh Hàn)
def schedule_instagram(con, video: dict, cfg: dict) -> None:
    """Sau ✅: ghi giờ đăng Instagram (API không hẹn giờ được — vòng lặp của bot đăng khi tới giờ)."""
    from .publish import instagram, youtube
    icfg = cfg["publish"].get("instagram") or {}
    if not icfg.get("enabled") or video.get("instagram_id") or video.get("instagram_due"):
        return
    if not instagram.ready():
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if db.get_state(con, "ig_auth_nagged") != today:
            db.set_state(con, "ig_auth_nagged", today)
            tg.send_message("ℹ️ Chưa đăng được lên Instagram: cần kết nối Trang Facebook liên kết với tài khoản"
                            " Instagram, có quyền instagram_basic + instagram_content_publish — gửi /facebook để xem cách.")
        return
    due = (youtube.compute_publish_at(icfg, taken=_taken_times(con, "instagram"))
           or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    db.update_video(con, video["id"], instagram_due=due)
    tg.send_message(f"📸 Instagram: video #{video['id']} sẽ đăng lúc {_local_times(due, icfg)}"
                    " (bot tự đăng khi tới giờ).")


def publish_instagram_due(con, cfg: dict, now: datetime = None) -> list:
    """Đăng các Reel Instagram đã tới giờ (gọi từ housekeeping của bot). Mỗi video một lần (chốt ig_<id>)."""
    from .publish import facebook, instagram
    icfg = cfg["publish"].get("instagram") or {}
    if not icfg.get("enabled"):
        return []
    now = now or datetime.now(timezone.utc)
    done = []
    rows = con.execute("SELECT * FROM videos WHERE instagram_due IS NOT NULL AND instagram_id IS NULL"
                       " AND status IN ('approved', 'publishing', 'published')").fetchall()
    for r in rows:
        if datetime.fromisoformat(r["instagram_due"].replace("Z", "+00:00")) > now:
            continue
        key = f"ig_{r['id']}"
        if db.get_state(con, key):
            continue
        db.set_state(con, key, "uploading")
        video = db.get_video(con, r["id"])
        try:
            res = instagram.upload_reel(ROOT / video["file"], instagram.caption(video, cfg),
                                        bool(icfg.get("ai_generated", True)))
        except Exception as exc:
            log.exception("Đăng Instagram lỗi")
            db.set_state(con, key, "")
            auth = isinstance(exc, facebook.FacebookAuthError)
            tg.send_message(f"⚠️ Đăng video #{r['id']} lên Instagram lỗi:\n{exc}"
                            + ("\nKết nối lại: /facebook" if auth else ""),
                            buttons=[[("🔁 Thử lại Instagram", f"ig:{r['id']}")]])
            # thử lại thì đăng ngay: bỏ giờ hẹn cũ khỏi vòng lặp tự động cho tới khi Du bấm
            db.update_video(con, r["id"], instagram_due=None)
            continue
        db.set_state(con, key, res["id"])
        db.update_video(con, r["id"], instagram_id=res["id"])
        tg.send_message(f"📸 Đã đăng video #{r['id']} lên Instagram: {res['url']}")
        done.append(r["id"])
    return done


# --------------------------------------------------------- bài viết Instagram (kênh Hàn, Du xin 21/11/2026)
def _ig_post_cfg(cfg: dict) -> dict:
    icfg = cfg["publish"].get("instagram") or {}
    posts = icfg.get("posts") or {}
    return {**icfg, **posts} if (icfg.get("enabled") and posts.get("enabled")) else {}


def prepare_ig_post(con, video_id: int, script_id: int, row: dict, scenes: list, cfg: dict, reply_to,
                    tags=()) -> None:
    """Lúc gửi video duyệt: soạn bài viết Instagram (ảnh 4:5 + chữ, cùng các cổng kiểm số với kịch bản —
    src/fb_post.py) và gửi xem trước ngay dưới video. ✅ ở video là duyệt cả bài; Du TRẢ LỜI tin xem trước bằng câu
    khác -> thành nội dung bài. Chưa bật / chưa kết nối Instagram -> bỏ qua."""
    from . import fb_post
    from .publish import instagram
    if not _ig_post_cfg(cfg) or not instagram.ready():
        return
    voices = [str(s.get("voice") or "") for s in scenes if isinstance(s, dict) and s.get("voice")]
    idea = {k: row.get(k) for k in ("title", "summary", "source_url", "source_name")}
    text = fb_post.draft(idea, voices, cfg, platform="instagram")
    if not text:
        tg.send_message("ℹ️ Bài viết Instagram kèm video này không qua được cổng kiểm số liệu sau 2 lần viết — chỉ"
                        " đăng Reel.", reply_to=reply_to)
        return
    img = fb_post.image_4x5(script_id)
    if not img:                                  # Instagram không đăng bài chữ không ảnh
        tg.send_message("ℹ️ Không vẽ được ảnh cho bài viết Instagram — chỉ đăng Reel.", reply_to=reply_to)
        return
    topic = ["#" + re.sub(r"\s+", "", str(t)) for t in tags if str(t).strip()]
    text = fb_post.with_hashtags(text, cfg, topic, limit=4)
    tg.send_photo(img, caption="📸 Ảnh của bài viết Instagram (đăng kèm khi bấm ✅)", reply_to=reply_to)
    msg = tg.send_message("📸 Bài viết Instagram sẽ đăng kèm (bấm ✅ ở video là duyệt cả bài này; TRẢ LỜI tin này bằng"
                          " nội dung khác để sửa):\n\n" + text, reply_to=reply_to)
    db.update_video(con, video_id, ig_post=text, ig_post_image=str(img), ig_post_msg=msg)
    if lang.code() != "vi":                      # bản dịch để Du hiểu bài (máy dịch; số đã được code đối chiếu)
        from .crew import translate_for_review
        tr = translate_for_review([l for l in text.splitlines() if l.strip()])
        if tr:
            tg.send_message("🇻🇳 Dịch bài viết Instagram (máy dịch, chỉ để hiểu):\n\n" + tr[:3500], reply_to=msg)


def schedule_ig_post(con, video: dict, cfg: dict) -> None:
    """Sau ✅: ghi giờ đăng bài viết Instagram (API không hẹn giờ được — vòng lặp của bot đăng khi tới giờ). Mỗi khung
    giờ một bài: duyệt nhiều video cùng lúc thì bài sau lùi sang ngày kế tiếp."""
    from .publish import youtube
    pcfg = _ig_post_cfg(cfg)
    if not pcfg or not video.get("ig_post") or video.get("ig_post_id") or video.get("ig_post_due"):
        return
    due = (youtube.compute_publish_at({**pcfg, "publish_time_local": pcfg.get("post_time_local", "12:30")},
                                      taken=_taken_times(con, "ig_post"))
           or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    db.update_video(con, video["id"], ig_post_due=due)
    tg.send_message(f"📝 Bài viết Instagram của video #{video['id']} sẽ đăng lúc {_local_times(due, pcfg)}"
                    " (bot tự đăng khi tới giờ).")


def publish_ig_posts_due(con, cfg: dict, now: datetime = None) -> list:
    """Đăng các bài viết Instagram đã tới giờ (housekeeping của bot). Mỗi video một lần (chốt igpost_<id>)."""
    from .publish import facebook, instagram
    if not _ig_post_cfg(cfg):
        return []
    now = now or datetime.now(timezone.utc)
    done = []
    rows = con.execute("SELECT * FROM videos WHERE ig_post_due IS NOT NULL AND ig_post_id IS NULL AND ig_post IS NOT NULL"
                       " AND status IN ('approved', 'publishing', 'published')").fetchall()
    for r in rows:
        if datetime.fromisoformat(r["ig_post_due"].replace("Z", "+00:00")) > now:
            continue
        key = f"igpost_{r['id']}"
        if db.get_state(con, key):
            continue
        db.set_state(con, key, "posting")
        try:
            res = instagram.post_image(Path(r["ig_post_image"]), r["ig_post"])
        except Exception as exc:
            log.exception("Đăng bài viết Instagram lỗi")
            db.set_state(con, key, "")
            auth = isinstance(exc, facebook.FacebookAuthError)
            tg.send_message(f"⚠️ Bài viết Instagram của video #{r['id']} lỗi:\n{exc}"
                            + ("\nKết nối lại: /facebook" if auth else ""),
                            buttons=[[("🔁 Thử lại bài viết Instagram", f"ip:{r['id']}")]])
            db.update_video(con, r["id"], ig_post_due=None)     # thử lại thì đăng ngay, khi Du bấm nút
            continue
        db.set_state(con, key, res["id"])
        db.update_video(con, r["id"], ig_post_id=res["id"])
        tg.send_message(f"📝 Đã đăng bài viết Instagram của video #{r['id']}: {res['url']}")
        done.append(r["id"])
    return done


# --------------------------------------------------------------- Facebook Reels
def push_facebook(con, video: dict, cfg: dict) -> None:
    """Đăng video đã duyệt lên Trang Facebook dạng Reel (src/publish/facebook.py), hẹn cùng giờ YouTube.
    Mỗi video một lần (chốt bằng trạng thái fb_publish_<id>, đặt TRƯỚC khi tải lên để hai lượt bấm
    không đăng đôi); lỗi thì gỡ chốt và đưa nút thử lại. Chưa có app Facebook thì bỏ qua im lặng."""
    from .publish import facebook, youtube
    import os
    fcfg = cfg["publish"].get("facebook") or {}
    key = f"fb_publish_{video['id']}"
    if not fcfg.get("enabled") or not os.getenv("FACEBOOK_APP_ID") or db.get_state(con, key):
        return
    if not facebook.connected():
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if db.get_state(con, "fb_auth_nagged") != today:       # nhắc tối đa mỗi ngày một lần
            db.set_state(con, "fb_auth_nagged", today)
            tg.send_message("ℹ️ Chưa đăng được lên Facebook: chưa kết nối Trang — gửi /facebook để xem cách.")
        return
    try:
        from .assemble import ffprobe_duration
        secs = ffprobe_duration(ROOT / video["file"])
    except Exception:
        secs = 0.0
    if secs > facebook.MAX_SECONDS:
        tg.send_message(f"ℹ️ Video #{video['id']} dài {secs:.0f} giây — Reels qua API tối đa"
                        f" {facebook.MAX_SECONDS} giây nên không đăng lên Facebook.")
        return
    state, at, slot = str(fcfg.get("video_state") or "SCHEDULED").upper(), None, None
    if state == "SCHEDULED":
        from . import fb_insights            # agent Facebook: thử nhiều khung giờ đăng, học khung nào tốt
        slot = fb_insights.choose_slot(con, fcfg, video["id"])
        iso = youtube.compute_publish_at({**fcfg, "publish_time_local": slot}, taken=_taken_times(con, "facebook"))
        if iso:
            at = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        else:
            state = "PUBLISHED"
    db.set_state(con, key, "uploading")
    try:
        res = facebook.upload_reel(ROOT / video["file"], facebook.caption(video), state, at,
                                   bool(fcfg.get("ai_generated", True)))
    except facebook.FacebookAuthError as exc:
        db.set_state(con, key, "")
        tg.send_message(f"⚠️ Chưa đăng được video #{video['id']} lên Facebook: {exc}\nKết nối lại: /facebook",
                        buttons=[[("🔁 Thử lại Facebook", f"fb:{video['id']}")]])
        return
    except Exception as exc:
        log.exception("Đăng Facebook lỗi")
        db.set_state(con, key, "")
        tg.send_message(f"⚠️ Đăng video #{video['id']} lên Facebook lỗi:\n{exc}",
                        buttons=[[("🔁 Thử lại Facebook", f"fb:{video['id']}")]])
        return
    db.set_state(con, key, res["video_id"])
    db.update_video(con, video["id"], facebook_id=res["video_id"], facebook_slot=slot,
                    facebook_at=(datetime.fromtimestamp(at, timezone.utc) if at else datetime.now(timezone.utc))
                    .isoformat(timespec="seconds"))
    log.info("Đã đăng video #%d lên Facebook: %s (%s, %s)", video["id"], res["url"], res["state"], res["status"])
    when = (f"hẹn công khai lúc {_local_times(datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), fcfg)}"
            if res["state"] == "SCHEDULED" else
            "lưu NHÁP trên Trang (vào Meta Business Suite để đăng)" if res["state"] == "DRAFT" else "đã công khai")
    tg.send_message(f"📘 Facebook Reels: video #{video['id']} {when}.\n{res['url']}")


def _connect_facebook(con, msg: dict, text: str) -> None:
    """/facebook: hướng dẫn kết nối. /facebook <token>: đổi token -> page token, lưu trên VM, xoá tin có token."""
    from .publish import facebook
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        status = ""
        if facebook.connected():
            from . import fb_insights
            try:
                who = facebook.whoami()
                status = (f"✅ Đang kết nối Trang: {who.get('name')} ({who.get('followers_count', '?')} người theo"
                          f" dõi)\n{fb_insights.status_text(con)}\n\n")
            except Exception as exc:
                status = f"⚠️ Token Trang không dùng được nữa: {exc}\n\n"
        tg.send_message(
            status + "📘 Kết nối Trang Facebook (một lần, ~5 phút):\n"
            "1. developers.facebook.com → Tạo ứng dụng (loại Business / “Khác”), để chế độ Development.\n"
            "2. Cài đặt → Thông tin cơ bản: chép App ID và App Secret vào .env trên VM (FACEBOOK_APP_ID,"
            " FACEBOOK_APP_SECRET) rồi khởi động lại bot.\n"
            "3. Công cụ → Graph API Explorer: chọn app đó, “Get User Access Token”, tích pages_show_list,"
            " pages_read_engagement, pages_manage_posts (để đăng) + read_insights, pages_read_user_content,"
            " pages_manage_engagement (để agent Facebook đọc số liệu, đọc bình luận và đăng trả lời — CHỈ khi"
            " Du bấm ✅; pages_manage_engagement cũng cho phép ẩn/xoá bình luận trên Trang nhưng code không"
            " dùng), chọn Trang của kênh.\n"
            "4. Gửi vào đây: /facebook <token vừa chép>. Bot đổi sang token Trang không hết hạn và xoá tin"
            " chứa token."
            + ("\n\n📸 Kênh này đăng Reels lên INSTAGRAM qua Trang: tài khoản Instagram phải là tài khoản Chuyên"
               " nghiệp và LIÊN KẾT với Trang; ở bước 3 tích thêm instagram_basic, instagram_content_publish,"
               " instagram_manage_insights (agent Instagram đọc số liệu)."
               if (load_config()["publish"].get("instagram") or {}).get("enabled") else ""))
        return
    tg.delete_message(msg.get("message_id"))         # tin chứa token: không để lại trong lịch sử chat
    try:
        cfg_now = load_config()
        page_id = ((cfg_now["publish"].get("facebook") or {}).get("page_id"))
        who = facebook.connect(parts[1], page_id, prefer_name=cfg_now["channel"]["name"])   # nhiều Trang: Trang trùng tên kênh
    except Exception as exc:
        tg.send_message(f"⚠️ Kết nối Facebook chưa được: {exc}")
        return
    missing = who.get("missing_optional") or []
    tg.send_message(f"✅ Đã kết nối Trang Facebook: {who['page_name']}. Từ giờ video được duyệt (✅) sẽ được"
                    " đăng lên Trang dạng Reel." + (
                        "\nℹ️ Chưa có quyền: " + "; ".join(f"{p} ({facebook.OPTIONAL[p]})" for p in missing)
                        + " — muốn có thì lấy token mới tích thêm rồi gửi lại /facebook <token>." if missing else ""))


# --------------------------------------------------------------- TikTok (bản nháp)
def tiktok_caption(video: dict) -> str:
    """Chú thích gợi ý cho TikTok: tiêu đề + dòng nguồn + ghi công nhạc + hashtag (API hộp thư
    không nhận chú thích — Du dán khi hoàn tất bài trong app)."""
    lines = [l.strip() for l in str(video.get("description") or "").splitlines()]
    keep = [l for l in lines if l.startswith(("Nguồn:", "Nhạc nền:", "출처:", "배경음악:"))]
    tags = next((l for l in reversed(lines) if l.startswith("#")), "")
    return "\n".join(x for x in [video.get("title") or "", "", *keep, tags] if x is not None).strip()


def push_tiktok(con, video: dict, cfg: dict) -> None:
    """Đẩy video vào hộp thư TikTok của Du (nếu đã bật + đã kết nối). Mỗi video chỉ đẩy một lần;
    lỗi thì báo kèm nút thử lại. Chưa kết nối thì nhắc một lần, không chặn YouTube."""
    from .publish import tiktok
    import os
    tcfg = cfg["publish"].get("tiktok") or {}
    if not tcfg.get("enabled") or db.get_state(con, f"tt_publish_{video['id']}"):
        return
    if not os.getenv("TIKTOK_CLIENT_KEY"):          # chưa tạo app TikTok: bỏ qua, không nhắc
        return
    try:
        res = tiktok.upload_draft(ROOT / video["file"])
    except tiktok.TikTokAuthError as exc:
        if db.get_state(con, "tt_auth_nagged") != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            db.set_state(con, "tt_auth_nagged", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            tg.send_message(f"ℹ️ Chưa đẩy được lên TikTok: {exc}")
        return
    except Exception as exc:
        log.exception("Đẩy TikTok lỗi")
        tg.send_message(f"⚠️ Đẩy video #{video['id']} vào TikTok lỗi:\n{exc}",
                        buttons=[[("🔁 Thử lại TikTok", f"tt:{video['id']}")]])
        return
    db.set_state(con, f"tt_publish_{video['id']}", res["publish_id"])
    log.info("Đã đẩy video #%d vào hộp thư TikTok (%s)", video["id"], res["status"])
    where = ("đã nằm trong hộp thư" if res["status"] == "SEND_TO_USER_INBOX"
             else f"đang xử lý ({res['status']}) — vài phút nữa sẽ vào hộp thư")
    tg.send_message(
        f"📥 TikTok: video #{video['id']} {where}. Mở TikTok → Hộp thư → thông báo của app → hoàn tất"
        " và đăng. Khi đăng: bật “Nội dung do AI tạo”.\n\n<b>Chú thích</b> (chạm để copy)\n"
        + tg.code(tiktok_caption(video)), as_html=True)


# ------------------------------------------------------- Xử lý sự kiện Telegram
def _from_owner(chat: dict, user: dict) -> bool:
    """Chỉ nhận lệnh từ đúng cuộc trò chuyện của Du (TELEGRAM_CHAT_ID)."""
    owner = tg.chat_id()
    return bool(owner) and owner in (str((chat or {}).get("id", "")), str((user or {}).get("id", "")))


def _handle_callback(con, cq: dict, cfg: dict) -> None:
    msg = cq.get("message") or {}
    if not _from_owner(msg.get("chat"), cq.get("from")):
        log.warning("Bỏ qua nút bấm từ người lạ (user %s)", (cq.get("from") or {}).get("id"))
        return
    cm = _COMMENT_CALLBACK.match(cq.get("data") or "")
    if cm:                                   # nút của agent Cộng đồng (trả lời bình luận)
        _handle_comment_button(con, cq, cm.group(1), cm.group(2), msg.get("message_id"))
        return
    m = _CALLBACK.match(cq.get("data") or "")
    if not m:
        tg.answer_callback(cq["id"], "Nút không hợp lệ")
        return
    action, video_id = m.group(1), int(m.group(2))
    video = db.get_video(con, video_id)
    if not video:
        tg.answer_callback(cq["id"], "Không tìm thấy video này")
        return
    mid = msg.get("message_id")
    # Ghi nhật ký mọi nút Du bấm (journalctl --user -u video-agents-review): trước 19/11 bot không
    # ghi gì nên không tra được video nào được duyệt lúc nào, upload ra sao
    log.info("Nút %s cho video #%d (đang ở trạng thái %s)", action, video_id, video["status"])

    if action in ("ok", "no") and video["status"] == "pending_review":
        from . import learning           # quyết định của Du là tín hiệu tự học (src/learning.py)
        learning.record(con, "du", "approve" if action == "ok" else "reject", video.get("title") or "",
                        "review", script_id=video.get("script_id"))

    if action == "ok":
        if not db.transition_video(con, video_id, "pending_review", "approved"):
            tg.answer_callback(cq["id"], f"Video này đã xử lý rồi ({video['status']})")
            return
        tg.answer_callback(cq["id"], "Đã duyệt ✅")
        if mid:
            tg.clear_buttons(mid)
        publish(con, db.get_video(con, video_id), cfg)

    elif action == "no":
        if not db.transition_video(con, video_id, "pending_review", "rejected"):
            tg.answer_callback(cq["id"], f"Video này đã xử lý rồi ({video['status']})")
            return
        tg.answer_callback(cq["id"], "Đã loại ❌")
        if mid:
            tg.clear_buttons(mid)
        tg.send_message(f"Đã loại video #{video_id}. Trả lời tin video để ghi lý do — Biên kịch đọc"
                        " lý do khi viết lần sau. Muốn thành luật lâu dài: /hoc <luật>")

    elif action == "done":          # mode manual: Du báo đã tự đăng
        if not db.transition_video(con, video_id, "approved", "published"):
            tg.answer_callback(cq["id"], f"Không đổi được ({video['status']})")
            return
        tg.answer_callback(cq["id"], "Đã ghi nhận 📤")
        if mid:
            tg.clear_buttons(mid)
        tg.send_message(f"Đã ghi nhận video #{video_id} đã đăng. Gửi link YouTube vào đây "
                        "để agent Phân tích theo dõi số liệu của nó.")

    elif action == "tt":            # thử đẩy TikTok lại sau lỗi
        tg.answer_callback(cq["id"], "Đang thử lại TikTok…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] in ("approved", "publishing", "published"):
            push_tiktok(con, video, cfg)

    elif action == "fb":            # thử đăng Facebook lại sau lỗi
        tg.answer_callback(cq["id"], "Đang thử lại Facebook…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] in ("approved", "publishing", "published"):
            push_facebook(con, video, cfg)

    elif action == "fp":            # thử đăng lại bài viết Facebook
        tg.answer_callback(cq["id"], "Đang thử lại bài viết…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] in ("approved", "publishing", "published"):
            push_fb_post(con, video, cfg)

    elif action == "ig":            # thử đăng lại Instagram: đăng ngay
        tg.answer_callback(cq["id"], "Đang đăng lại Instagram…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] in ("approved", "publishing", "published") and not video.get("instagram_id"):
            db.update_video(con, video_id, instagram_due=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            publish_instagram_due(con, cfg)

    elif action == "ip":            # thử đăng lại bài viết Instagram: đăng ngay
        tg.answer_callback(cq["id"], "Đang đăng lại bài viết Instagram…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] in ("approved", "publishing", "published") and not video.get("ig_post_id"):
            db.update_video(con, video_id, ig_post_due=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            publish_ig_posts_due(con, cfg)

    elif action == "retry":        # mode api: thử upload lại sau lỗi
        tg.answer_callback(cq["id"], "Đang thử lại…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] == "approved" and not video["youtube_id"]:
            publish(con, video, cfg)


_COMMENT_CALLBACK = re.compile(r"^(cok|cno):([\w-]{5,80})$")


def _handle_comment_button(con, cq: dict, action: str, cid: str, mid) -> None:
    """✅ Đăng trả lời / ❌ Bỏ qua của một bình luận. Kênh CHỈ đăng khi Du bấm ✅ (src/community.py)."""
    from . import community
    from .publish import youtube
    row = con.execute("SELECT * FROM comments WHERE id = ?", (cid,)).fetchone()
    if not row:
        tg.answer_callback(cq["id"], "Không tìm thấy bình luận này")
        return
    log.info("Nút %s cho bình luận %s (đang %s)", action, cid, row["status"])
    if action == "cno":
        con.execute("UPDATE comments SET status = 'skipped' WHERE id = ? AND status = 'new'", (cid,))
        con.commit()
        tg.answer_callback(cq["id"], "Đã bỏ qua")
        if mid:
            tg.clear_buttons(mid)
        return
    try:
        community.post_reply(con, cid)
    except youtube.YouTubeAuthError as exc:   # chưa cấp quyền bình luận: GIỮ nút để bấm lại sau /capquyen
        tg.answer_callback(cq["id"], "Chưa có quyền đăng")
        tg.send_message(f"🔑 {exc}")
        return
    except Exception as exc:
        tg.answer_callback(cq["id"], "Chưa đăng được")
        tg.send_message(f"⚠️ Chưa đăng được trả lời: {exc}")
        return
    log.info("Đã đăng trả lời bình luận %s", cid)
    tg.answer_callback(cq["id"], "Đã đăng ✅")
    if mid:
        tg.clear_buttons(mid)
    tg.send_message(f"✅ Kênh đã trả lời {row['author']}: “{str(row['reply'])[:200]}”"
                    f" — https://youtube.com/shorts/{row['youtube_id']}")


def _redraft_comment(con, card, text: str, old_mid: int) -> None:
    """Du trả lời tin của một bình luận bằng câu của mình -> nháp mới + nút ✅ (KHÔNG đăng thẳng)."""
    from . import community
    if card["status"] == "posted":
        tg.send_message("Bình luận này kênh đã trả lời rồi.")
        return
    c = community.set_draft(con, card["id"], text)
    mid = tg.send_message("Nháp mới — bấm ✅ để đăng:\n\n" + community.card_text(c),
                          buttons=community.card_buttons(c))
    if mid:
        con.execute("UPDATE comments SET tg_message_id = ? WHERE id = ?", (mid, card["id"]))
        con.commit()
        tg.clear_buttons(old_mid)


RENEW_COMMANDS = {"/capquyen", "/cap_quyen", "capquyen", "cấp quyền", "gia hạn", "/giahan"}


def _start_renewal(con) -> None:
    """Gửi link cấp quyền YouTube để Du gia hạn ngay trên điện thoại."""
    from .publish import youtube
    try:
        a = youtube.start_phone_auth()
    except youtube.YouTubeAuthError as exc:
        tg.send_message(f"⚠️ Không tạo được link cấp quyền: {exc}")
        return
    db.set_state(con, "yt_auth_state", a["state"])
    db.set_state(con, "yt_auth_verifier", a["verifier"])
    tg.send_message(
        "🔑 Gia hạn quyền đăng YouTube (≈1 phút):\n"
        "1. Mở link dưới, đăng nhập, chọn kênh “Thế giới qua con số”.\n"
        "2. Có cảnh báo “chưa xác minh” thì bấm Advanced → Go to video-agents; tích HẾT các quyền. Quyền"
        " “xem, sửa, xoá video/bình luận” (youtube.force-ssl, thêm 19/11) là để kênh đăng câu trả lời bình"
        " luận Du bấm ✅ — YouTube không có quyền hẹp hơn; code chỉ dùng nó cho việc đó.\n"
        "3. Trang cuối báo KHÔNG kết nối được tới 127.0.0.1:8765 — đúng như vậy. Chép NGUYÊN địa chỉ"
        " trên thanh địa chỉ rồi gửi vào đây (trong vài phút, mã hết hạn nhanh).\n\n" + a["url"])


def _finish_renewal(con, text: str) -> None:
    from .publish import youtube
    state, verifier = db.get_state(con, "yt_auth_state"), db.get_state(con, "yt_auth_verifier")
    if not state or not verifier:
        tg.send_message("Chưa có yêu cầu cấp quyền nào đang chờ — gửi /capquyen để bắt đầu.")
        return
    try:
        youtube.finish_phone_auth(text, state, verifier)
        who = youtube.whoami()
    except Exception as exc:
        tg.send_message(f"⚠️ Gia hạn chưa được: {exc}")
        return
    db.set_state(con, "yt_auth_state", "")
    db.set_state(con, "yt_auth_verifier", "")
    tg.send_message(f"✅ Đã gia hạn quyền đăng YouTube cho kênh “{who.get('title', '?')}”."
                    + ("" if who.get("title") else "\n⚠️ Không đọc được tên kênh — kiểm tra đã chọn đúng kênh chưa.")
                    + ("\n💬 Có quyền bình luận: bấm ✅ ở tin bình luận là kênh đăng câu trả lời."
                       if youtube.has_scope(youtube.FORCE_SSL) else
                       "\nℹ️ Chưa có quyền bình luận (ô đó chưa được tích) — kênh chưa đăng được câu trả lời."
                       " Muốn có: /capquyen lại và tích hết."))


def _start_tiktok(con) -> None:
    from .publish import tiktok
    try:
        a = tiktok.start_auth()
    except tiktok.TikTokAuthError as exc:
        tg.send_message(f"⚠️ Không tạo được link TikTok: {exc}")
        return
    db.set_state(con, "tt_auth_state", a["state"])
    tg.send_message(
        "🎵 Kết nối TikTok (≈1 phút):\n"
        "1. Mở link dưới, đăng nhập đúng tài khoản TikTok của kênh, bấm cho phép (giữ cả 2 quyền).\n"
        "2. TikTok chuyển về trang của kênh — bấm “Sao chép” rồi dán vào đây.\n\n" + a["url"])


def _finish_tiktok(con, text: str) -> None:
    from .publish import tiktok
    state = db.get_state(con, "tt_auth_state")
    if not state:
        tg.send_message("Chưa có yêu cầu kết nối TikTok nào đang chờ — gửi /tiktok để bắt đầu.")
        return
    try:
        tiktok.finish_auth(text, state)
        who = tiktok.whoami()
    except Exception as exc:
        tg.send_message(f"⚠️ Kết nối TikTok chưa được: {exc}")
        return
    db.set_state(con, "tt_auth_state", "")
    tg.send_message(f"✅ Đã kết nối TikTok: {who.get('display_name', '?')}. Từ giờ video được duyệt sẽ được"
                    " đẩy vào hộp thư TikTok của tài khoản này.")


# bắt buộc dấu "/": ghi chú thường trả lời video ("học cách mở đầu khác đi…") không bị bắt nhầm thành lệnh
TEACH = re.compile(r"^/(hoc|học|day|dạy)\b\s*(.*)$", re.I | re.S)
FORGET = re.compile(r"^/(quen|quên)\b\s*(\d*)\s*$", re.I)


def _handle_teaching(text: str) -> bool:
    """Du dạy hệ thống qua Telegram (src/learning.py): /hoc <luật>, /luat, /quen <số>. True nếu đã xử lý."""
    from . import learning
    if text.lower() in ("/luat", "/luật"):
        rs = learning.rules()
        tg.send_message("📚 Luật Du đã dạy (Biên kịch đọc trước mỗi lần viết):\n"
                        + ("\n".join(f"{k}. {r['text']}" for k, r in enumerate(rs, 1)) or "(chưa có)")
                        + "\n\nDạy thêm: /hoc <luật> · Bỏ: /quen <số>")
        return True
    m = FORGET.match(text)
    if m and not m.group(2):
        tg.send_message("Gửi kèm số thứ tự luật muốn bỏ, ví dụ: /quen 2 (xem số bằng /luat)")
        return True
    if m:
        try:
            gone = learning.remove_rule(int(m.group(2)))
        except Exception as exc:
            tg.send_message(f"⚠️ Chưa bỏ được luật ({exc}). Kiểm tra data/learned.yaml trên VM.")
            return True
        tg.send_message(f"🗑 Đã bỏ luật: {gone['text']}" if gone else "Không có luật số đó — gửi /luat để xem.")
        return True
    m = TEACH.match(text)
    if m:
        rule = m.group(2).strip()
        if not rule:
            tg.send_message("Gửi kèm nội dung luật, ví dụ: /hoc không dùng từ “chúng ta” trong lời đọc")
            return True
        try:
            learning.add_rule(rule)
        except Exception as exc:          # file learned.yaml hỏng: báo chứ không ghi đè mất cái đã học
            tg.send_message(f"⚠️ Chưa ghi được luật ({exc}). Kiểm tra data/learned.yaml trên VM.")
            return True
        log.info("Du dạy luật mới: %s", rule)
        tg.send_message(f"✅ Đã ghi nhớ: “{rule}”. Áp dụng từ lượt viết kịch bản kế tiếp. (/luat để xem hết)")
        return True
    return False


# Du chỉnh CÁCH DỰNG (src/style.py): mỗi lệnh dời khung thử nghiệm của một núm một nấc. So trên chữ đã
# bỏ dấu: "/Nhạc nhỏ" = "/nhac nho".
STYLE_COMMANDS = {("nhac", "to"): ("music", 1), ("nhac", "lon"): ("music", 1),
                  ("nhac", "nho"): ("music", -1), ("nhac", "be"): ("music", -1),
                  ("giong", "nhanh"): ("tempo", 1), ("giong", "cham"): ("tempo", -1),
                  ("nhip", "nhanh"): ("pace", -1), ("nhip", "cham"): ("pace", 1),   # nhanh = ít giây mỗi hình
                  ("chu", "to"): ("captions", 1), ("chu", "lon"): ("captions", 1),
                  ("chu", "nho"): ("captions", -1), ("chu", "be"): ("captions", -1),
                  ("video", "ngan"): ("length", -1), ("video", "dai"): ("length", 1)}   # độ dài (20/11)


def _fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt, gộp khoảng trắng: "/Nhạc  nhỏ" -> "/nhac nho"."""
    import unicodedata
    s = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return " ".join("".join(ch for ch in s if unicodedata.category(ch) != "Mn").split())


def _handle_style(con, text: str) -> bool:
    """/kieu (xem), /kieu tat|bat, /nhac to|nho, /giong nhanh|cham, /nhip nhanh|cham, /chu to|nho."""
    from . import style
    t = _fold(text)
    parts = t.split()
    if not parts or parts[0] not in ("/kieu", "/nhac", "/giong", "/nhip", "/chu", "/video"):
        return False
    try:
        if t == "/kieu":
            tg.send_message(style.status_text())
        elif t in ("/kieu tat", "/kieu bat"):
            style.set_paused(t.endswith("tat"))
            tg.send_message("⏸ Tạm dừng thử nghiệm: video kế tiếp dùng tâm khung của mỗi núm. /kieu bat để thử tiếp."
                            if t.endswith("tat") else "▶️ Thử nghiệm tiếp: mỗi video một tổ hợp mới.")
        elif len(parts) == 2 and (parts[0][1:], parts[1]) in STYLE_COMMANDS:
            knob, direction = STYLE_COMMANDS[(parts[0][1:], parts[1])]
            last = style.latest_applied(con, knob)
            before, after = style.shift(knob, direction)
            label = style.KNOBS[knob]["label"]
            show = lambda vals: " · ".join(style.fmt(knob, v) for v in vals)
            if before == after:
                tg.send_message(f"{label}: đã ở giới hạn an toàn ({show(after)}), không dời thêm được.")
            else:
                log.info("Du chỉnh cách dựng: %s %s -> %s", knob, before, after)
                tg.send_message(f"🎛 {label}: khung thử mới {show(after)} (trước: {show(before)}). Áp dụng từ"
                                " video dựng kế tiếp; hệ thống sẽ không tự dời ngược lại."
                                + (f"\nVideo gửi gần nhất dùng {style.fmt(knob, last)}." if last is not None else ""))
        else:
            tg.send_message("Lệnh chỉnh cách dựng: /giong nhanh|cham · /nhac to|nho · /nhip nhanh|cham ·"
                            " /chu to|nho · /video ngan|dai · /kieu (xem) · /kieu tat|bat")
    except Exception as exc:                 # learned.yaml hỏng: báo chứ không ghi đè mất cái đã học
        tg.send_message(f"⚠️ Chưa chỉnh được ({exc}). Kiểm tra data/learned.yaml trên VM.")
    return True


def _handle_growth(con, text: str) -> bool:
    """/kenh: tình trạng kênh (agent Tăng trưởng). /chude <từ khoá>: Du yêu cầu làm sớm một chủ đề —
    khớp với chỉ số kênh đang có nguồn (src/topics.py), xếp hàng cho lượt săn ý tưởng kế tiếp."""
    from . import growth, topics
    from .main import load_config
    t = _fold(text)
    if t == "/kenh":
        tg.send_message(growth.status_text(load_config()))
        return True
    if t.startswith("/kenhlon"):             # agent Học kênh lớn: xem sổ tay / thêm kênh muốn học
        from .analysis import big_channels
        parts = text.split(maxsplit=2)
        if len(parts) >= 3 and _fold(parts[1]) in ("them", "add"):
            try:
                info = big_channels.add_channel(parts[2])
            except Exception as exc:
                tg.send_message(f"⚠️ Chưa thêm được kênh: {exc}")
                return True
            tg.send_message(f"🏆 Đã thêm kênh “{info['title']}” ({info['subs']:,} người đăng ký) — agent Học kênh"
                            " lớn quét từ lượt Phân tích Chủ nhật tới.".replace(",", "."))
        else:
            tg.send_message(big_channels.status_text())
        return True
    if t == "/youtube":                      # agent Hiểu YouTube + agent Tin YouTube
        from . import yt_insights, yt_news
        news = yt_news.latest_lines(con)
        tg.send_message("\n".join([yt_insights.status_text()]
                                  + (["", "📰 Tin YouTube gần nhất liên quan tới kênh:"] + news if news else []))[:3900])
        return True
    words = text.split()
    if t.startswith("/chude"):
        query = " ".join(words[1:])
    elif t.startswith("/chu de"):
        query = " ".join(words[2:])
    else:
        return False
    if not query.strip():
        tg.send_message("Gửi kèm chủ đề, ví dụ: /chude thất nghiệp — kênh sẽ ưu tiên làm chủ đề đó.")
        return True
    cfg = load_config()
    keys = topics.match(cfg, query)
    if not keys:
        topics.request(con, None, query, "du")
        tg.send_message(f"Kênh chưa có nguồn số liệu cho “{query}” — đã ghi vào danh sách mong muốn (báo cáo"
                        " tuần sẽ nhắc để thêm chỉ số mới).")
        return True
    names, lines = topics.catalog(cfg), []
    for key in keys:
        done = topics.covered(con, key)
        if done:
            lines.append(f"• {names[key]}: kênh đã có video — https://youtube.com/shorts/{done[0][1]}")
            continue
        status = topics.request(con, key, query, "du")
        lines.append(f"• {names[key]}: " + {"pending": "đã xếp hàng — lượt săn ý tưởng kế tiếp lấy trước",
                                            "duplicate": "đã có trong hàng đợi gần đây"}[status])
    tg.send_message("📌 Chủ đề “" + query + "”:\n" + "\n".join(lines))
    return True


def _handle_message(con, msg: dict) -> None:
    if not _from_owner(msg.get("chat"), msg.get("from")):
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if _handle_teaching(text) or _handle_growth(con, text) or _handle_style(con, text):
        return
    if _fold(text).split()[0] == "/facebook":
        _connect_facebook(con, msg, text)
        return
    if text.lower() in ("/tiktok", "tiktok"):
        _start_tiktok(con)
        return
    if "tiktok-callback" in text:
        _finish_tiktok(con, text)
        return
    if text.lower() in RENEW_COMMANDS:
        _start_renewal(con)
        return
    if "127.0.0.1:8765" in text:
        _finish_renewal(con, text)
        return
    reply_mid = (msg.get("reply_to_message") or {}).get("message_id")
    replied = None
    if reply_mid:
        # trả lời TIN CỦA MỘT BÌNH LUẬN (agent Cộng đồng) = câu Du muốn kênh đăng — xét TRƯỚC link YouTube:
        # câu trả lời có thể chứa link video mà không được hiểu thành "gắn link cho video"
        post_of = con.execute("SELECT id, status FROM videos WHERE fb_post_msg=?", (reply_mid,)).fetchone()
        if post_of:                          # Du sửa bài viết Facebook đi kèm video (src/fb_post.py)
            if post_of["status"] not in ("pending_review", "approved"):
                tg.send_message("Bài viết này đã đăng hoặc video đã bị loại — không sửa được nữa.")
                return
            from . import fb_post
            new = fb_post.with_hashtags(text.strip(), load_config())
            db.update_video(con, post_of["id"], fb_post=new)
            tg.send_message(f"✏️ Đã thay nội dung bài viết Facebook của video #{post_of['id']} bằng câu của Du"
                            " (đăng khi video được ✅).")
            return
        ig_of = con.execute("SELECT id, status, ig_post_id FROM videos WHERE ig_post_msg=?", (reply_mid,)).fetchone()
        if ig_of:                            # Du sửa bài viết Instagram đi kèm video
            if ig_of["ig_post_id"] or ig_of["status"] not in ("pending_review", "approved", "published"):
                tg.send_message("Bài viết này đã đăng hoặc video đã bị loại — không sửa được nữa.")
                return
            from . import fb_post
            db.update_video(con, ig_of["id"], ig_post=fb_post.with_hashtags(text.strip(), load_config()))
            tg.send_message(f"✏️ Đã thay nội dung bài viết Instagram của video #{ig_of['id']} bằng câu của Du"
                            " (bot đăng khi tới giờ hẹn).")
            return
        card = con.execute("SELECT id, status FROM comments WHERE tg_message_id=?", (reply_mid,)).fetchone()
        if card:
            _redraft_comment(con, card, text, reply_mid)
            return
        replied = con.execute("SELECT id FROM videos WHERE tg_message_id=?", (reply_mid,)).fetchone()

    link = _YT_LINK.search(text)
    if link:
        # Link YouTube: gắn vào video được reply, không thì video đã duyệt gần nhất chưa có link
        row = replied or con.execute(
            "SELECT id FROM videos WHERE status IN ('approved','published')"
            " AND youtube_id IS NULL ORDER BY id DESC").fetchone()
        if not row:
            tg.send_message("Không có video nào đang chờ link.")
            return
        db.update_video(con, row["id"], youtube_id=link.group(1),
                        youtube_url=f"https://youtube.com/shorts/{link.group(1)}")
        db.transition_video(con, row["id"], "approved", "published")
        tg.send_message(f"Đã lưu link cho video #{row['id']} ✅")
    elif replied:
        db.update_video(con, replied["id"], review_note=text[:1000])
        from . import learning           # Biên kịch đọc các nhận xét gần nhất của Du (tự học)
        sid = con.execute("SELECT script_id FROM videos WHERE id=?", (replied["id"],)).fetchone()["script_id"]
        learning.record(con, "du", "note", text[:400], "review", script_id=sid)
        tg.send_message(f"Đã ghi chú cho video #{replied['id']} 📝 — Biên kịch sẽ đọc nhận xét này khi viết"
                        " (muốn thành luật lâu dài: /hoc <luật>)")


def handle_update(con, upd: dict, cfg: dict) -> None:
    if "callback_query" in upd:
        _handle_callback(con, upd["callback_query"], cfg)
    elif "message" in upd:
        _handle_message(con, upd["message"])


# ------------------------------------------------------------ Việc định kỳ
CHECK_AFTER_MINUTES = 30        # quá giờ hẹn chừng này mới soát (YouTube cần vài phút để công khai)


def remind_token(con, yt: dict, now: datetime = None) -> bool:
    """App OAuth ở chế độ Testing: refresh token chết sau `oauth_token_days` ngày. Nhắc Du
    gia hạn từ 1 ngày trước, mỗi ngày tối đa một lần. Trả về True nếu vừa nhắc."""
    from .publish import youtube
    days = yt.get("oauth_token_days")
    age = youtube.token_age_days(now)
    if yt.get("mode") != "api" or not days or age is None or age < float(days) - 1:
        return False
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    if db.get_state(con, "yt_token_reminded") == today:
        return False
    db.set_state(con, "yt_token_reminded", today)
    left = float(days) - age
    when = f"còn khoảng {left * 24:.0f} giờ" if left > 0 else "đã HẾT HẠN"
    tg.send_message(f"🔑 Quyền đăng YouTube {when} (ứng dụng Google đang ở chế độ Testing:"
                    f" {days} ngày phải gia hạn một lần). Gửi /capquyen để gia hạn ngay trên điện thoại.")
    return True


FB_REMIND_DAYS = 7


def remind_facebook_access(con, now: datetime = None) -> bool:
    """Quyền đọc dữ liệu của token Trang (Facebook / Instagram) hết sau 90 ngày: từ 7 ngày trước hạn, mỗi ngày nhắc Du
    một lần gửi lại /facebook <token mới>. Trả về True nếu vừa nhắc."""
    from .publish import facebook
    left = facebook.data_access_days_left(now)
    if left is None or left > FB_REMIND_DAYS:
        return False
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    if db.get_state(con, "fb_access_reminded") == today:
        return False
    db.set_state(con, "fb_access_reminded", today)
    when = f"còn khoảng {max(left, 0):.0f} ngày" if left > 0 else "đã HẾT"
    tg.send_message(f"🔑 Quyền đọc dữ liệu Facebook/Instagram {when} (Meta cho 90 ngày mỗi lần cấp). Quá hạn thì số"
                    " liệu, bình luận — và có thể cả đăng bài — sẽ dừng. Gia hạn: Graph API Explorer → lấy token mới (cùng"
                    " app, tích đủ quyền như lần trước) → gửi /facebook <token> cho bot này.")
    return True


def check_scheduled(con, now: datetime = None) -> list:
    """Video đã qua giờ hẹn công khai: hỏi YouTube chế độ hiển thị thật. Vẫn riêng tư thì báo Du
    (project API chưa qua audit thì YouTube khoá video ở riêng tư — giờ hẹn không có tác dụng).
    Trả về [(video_id, chế độ hiển thị)] của những video vừa soát."""
    from .publish import youtube
    now = now or datetime.now(timezone.utc)
    done = []
    rows = con.execute("SELECT id, youtube_id, youtube_url FROM videos"
                       " WHERE status='published' AND youtube_id IS NOT NULL").fetchall()
    for r in rows:
        at = db.get_state(con, f"yt_publish_at_{r['id']}")
        if not at:
            continue
        if now < datetime.fromisoformat(at.replace("Z", "+00:00")) + timedelta(minutes=CHECK_AFTER_MINUTES):
            continue
        privacy = (youtube.get_status(r["youtube_id"]) or {}).get("privacyStatus")
        db.update_video(con, r["id"], youtube_privacy=privacy)
        db.set_state(con, f"yt_publish_at_{r['id']}", "")          # mỗi video chỉ soát một lần
        if privacy == "public":
            tg.send_message(f"🌐 Video #{r['id']} đã công khai đúng giờ: {r['youtube_url']}")
        else:
            tg.send_message(
                f"⚠️ Video #{r['id']} đã quá giờ hẹn nhưng vẫn “{privacy}”: {r['youtube_url']}\n"
                "Nhiều khả năng YouTube khoá vì project API chưa qua audit. Vào YouTube Studio →"
                " Nội dung → đổi chế độ hiển thị thành Công khai. Bot sẽ báo lại mỗi video cho tới khi"
                " audit xong (README, mục Đăng tự động qua API).")
        done.append((r["id"], privacy))
    return done


def housekeeping(con, cfg: dict, now: datetime = None) -> None:
    """Các việc chạy định kỳ trong vòng lặp listen; lỗi ở đây không được làm sập bot."""
    yt = cfg["publish"]["youtube"]
    for job in (lambda: remind_token(con, yt, now), lambda: check_scheduled(con, now),
                lambda: publish_instagram_due(con, cfg, now), lambda: publish_ig_posts_due(con, cfg, now),
                lambda: remind_facebook_access(con, now)):
        try:
            job()
        except Exception:
            log.exception("Việc định kỳ lỗi (bỏ qua, lần sau thử lại)")


HOUSEKEEPING_EVERY = 30 * 60    # giây


def listen(once: bool = False) -> None:
    """Vòng lặp chờ sự kiện. Vị trí đã đọc lưu trong DB nên khởi động lại không xử lý lặp."""
    cfg, con = load_config(), db.connect()
    last_housekeeping = 0.0
    try:
        offset = int(db.get_state(con, "tg_offset", "0"))
        log.info("Đang chờ Du bấm nút trên Telegram… (Ctrl+C để dừng)")
        while True:
            if not once and time.time() - last_housekeeping >= HOUSEKEEPING_EVERY:
                last_housekeeping = time.time()
                housekeeping(con, cfg)
            updates = tg.get_updates(offset, timeout=0 if once else 50)
            for upd in updates or []:
                offset = upd["update_id"] + 1
                # Ghi vị trí TRƯỚC khi xử lý: một sự kiện gây lỗi không kẹt lại lặp vô hạn
                db.set_state(con, "tg_offset", offset)
                try:
                    handle_update(con, upd, cfg)
                except Exception as exc:
                    log.exception("Lỗi xử lý sự kiện %s", upd.get("update_id"))
                    tg.send_message(f"⚠️ Bot gặp lỗi khi xử lý thao tác vừa rồi: {exc}")
            if once:
                return
            if updates is None:        # mất mạng / Telegram lỗi -> nghỉ rồi thử lại
                time.sleep(10)
    finally:
        con.close()      # Windows: kết nối mở giữ khóa file DB


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Gửi video cho Du duyệt / chờ nút bấm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="Kiểm định + gửi video vào Telegram")
    s.add_argument("script_id", type=int)
    s.add_argument("--force", action="store_true", help="Gửi kể cả khi kiểm định chưa đạt")
    s.add_argument("--skip-qc", action="store_true", help="Bỏ qua kiểm định (chỉ để thử)")
    l = sub.add_parser("listen", help="Chờ Du bấm nút rồi xử lý")
    l.add_argument("--once", action="store_true", help="Xử lý các sự kiện đang chờ rồi thoát")
    g = sub.add_parser("ig-post", help="Bài viết Instagram cho video ĐÃ duyệt trước khi có tính năng này: soạn + gửi"
                                       " xem trước; thêm --schedule để hẹn đăng (chỉ sau khi Du duyệt bản xem trước)")
    g.add_argument("video_id", type=int)
    g.add_argument("--schedule", action="store_true")
    args = ap.parse_args()
    if args.cmd == "send":
        sys.exit(0 if send_for_review(args.script_id, args.force, args.skip_qc) else 1)
    if args.cmd == "ig-post":
        con, cfg = db.connect(), load_config()
        v = db.get_video(con, args.video_id)
        if args.schedule:
            schedule_ig_post(con, v, cfg)
        else:
            row = db.get_script_with_idea(con, v["script_id"])
            prepare_ig_post(con, v["id"], v["script_id"], dict(row), yaml.safe_load(row["body"]) or [], cfg,
                            v.get("tg_message_id"), tags=v.get("tags") or [])
            print("Bài viết:", (db.get_video(con, v["id"]) or {}).get("ig_post"))
        return
    listen(once=args.once)


if __name__ == "__main__":
    main()
