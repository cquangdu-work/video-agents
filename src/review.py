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
from pathlib import Path

import yaml

from . import db
from . import telegram_bot as tg

log = logging.getLogger("review")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONFIG_PATH = ROOT / "config" / "channel.yaml"

_YT_LINK = re.compile(r"(?:youtu\.be/|youtube\.com/(?:shorts/|watch\?v=|live/))([\w-]{11})")
_CALLBACK = re.compile(r"^(ok|no|done|retry):(\d+)$")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------- Gửi duyệt
def format_review_caption(video_id: int, script_id: int, meta: dict, checks: list) -> str:
    qc_line = " · ".join(f"{'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}" for c in checks)
    lines = [f"🎬 Video #{video_id} chờ duyệt (kịch bản #{script_id})",
             f"📌 {meta['title']}"]
    if qc_line:
        lines += ["", f"Kiểm định: {qc_line}"]
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
            for c in checks:
                print(f"  {'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}")
            print("Kiểm định CHƯA ĐẠT — không gửi duyệt (thêm --force nếu vẫn muốn gửi).")
            return None

    scenes = yaml.safe_load(row["body"]) or []
    hooks = json.loads(row["hooks"] or "[]")
    idea = {k: row[k] for k in ("title", "angle", "summary", "source_url", "source_name")}
    meta = metadata.build_metadata(idea, scenes, hooks, cfg)

    video_id = db.upsert_video(con, script_id, video_path.relative_to(ROOT).as_posix(),
                               meta["title"], meta["description"], meta["tags"], checks)
    mid = tg.send_video(
        video_path, format_review_caption(video_id, script_id, meta, checks),
        buttons=[[("✅ Duyệt đăng", f"ok:{video_id}"), ("❌ Loại", f"no:{video_id}")]])
    if not mid:
        # Trả None (lệnh thoát mã 1) để chuỗi hằng ngày biết là CHƯA tới tay Du và thử lại
        print(f"Đã lưu video #{video_id} nhưng KHÔNG gửi được Telegram — chạy lại lệnh send.")
        return None
    db.update_video(con, video_id, tg_message_id=mid)
    tg.send_message("Mô tả sẽ đăng kèm:\n\n" + meta["description"], reply_to=mid)
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
        res = youtube.upload(ROOT / video["file"], video["title"], video["description"],
                             video["tags"], yt)
    except Exception as exc:
        log.exception("Upload YouTube lỗi")
        db.transition_video(con, video["id"], "publishing", "approved")
        tg.send_message(f"⚠️ Upload video #{video['id']} lỗi:\n{exc}",
                        buttons=[[("🔁 Thử lại", f"retry:{video['id']}")]])
        return
    db.update_video(con, video["id"], youtube_id=res["id"], youtube_url=res["url"],
                    youtube_privacy=res["privacy"])
    db.transition_video(con, video["id"], "publishing", "published")

    msg = f"🚀 Đã upload video #{video['id']}:\n{res['url']}\nChế độ hiển thị: {res['privacy']}"
    if res["publish_at"]:
        msg += f"\nHẹn công khai lúc (UTC): {res['publish_at']}"
    if res["privacy"] != res["requested_privacy"]:
        msg += (f"\n\n⚠️ Yêu cầu “{res['requested_privacy']}” nhưng YouTube đặt “{res['privacy']}”."
                " Nhiều khả năng dự án API chưa qua audit nên video bị khoá riêng tư —"
                " xem mục YouTube trong README.")
    elif res["privacy"] == "private" and not res["publish_at"]:
        msg += "\nVideo đang RIÊNG TƯ — vào YouTube Studio chuyển Công khai khi sẵn sàng."
    tg.send_message(msg)


def publish(con, video: dict, cfg: dict) -> None:
    if video["status"] != "approved":       # không bao giờ đăng thứ chưa được Du duyệt
        raise ValueError(f"Video #{video['id']} chưa được duyệt (status={video['status']})")
    mode = cfg["publish"]["youtube"].get("mode", "manual")
    (_publish_api if mode == "api" else _publish_manual)(con, video, cfg)


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
        tg.send_message(f"Đã loại video #{video_id}. Trả lời tin video để ghi lý do — "
                        "agent Phân tích sẽ đọc để rút kinh nghiệm.")

    elif action == "done":          # mode manual: Du báo đã tự đăng
        if not db.transition_video(con, video_id, "approved", "published"):
            tg.answer_callback(cq["id"], f"Không đổi được ({video['status']})")
            return
        tg.answer_callback(cq["id"], "Đã ghi nhận 📤")
        if mid:
            tg.clear_buttons(mid)
        tg.send_message(f"Đã ghi nhận video #{video_id} đã đăng. Gửi link YouTube vào đây "
                        "để agent Phân tích theo dõi số liệu của nó.")

    elif action == "retry":         # mode api: thử upload lại sau lỗi
        tg.answer_callback(cq["id"], "Đang thử lại…")
        if mid:
            tg.clear_buttons(mid)
        if video["status"] == "approved" and not video["youtube_id"]:
            publish(con, video, cfg)


def _handle_message(con, msg: dict) -> None:
    if not _from_owner(msg.get("chat"), msg.get("from")):
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    reply_mid = (msg.get("reply_to_message") or {}).get("message_id")
    replied = None
    if reply_mid:
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
        tg.send_message(f"Đã ghi chú cho video #{replied['id']} 📝")


def handle_update(con, upd: dict, cfg: dict) -> None:
    if "callback_query" in upd:
        _handle_callback(con, upd["callback_query"], cfg)
    elif "message" in upd:
        _handle_message(con, upd["message"])


def listen(once: bool = False) -> None:
    """Vòng lặp chờ sự kiện. Vị trí đã đọc lưu trong DB nên khởi động lại không xử lý lặp."""
    cfg, con = load_config(), db.connect()
    try:
        offset = int(db.get_state(con, "tg_offset", "0"))
        log.info("Đang chờ Du bấm nút trên Telegram… (Ctrl+C để dừng)")
        while True:
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
    args = ap.parse_args()
    if args.cmd == "send":
        sys.exit(0 if send_for_review(args.script_id, args.force, args.skip_qc) else 1)
    listen(once=args.once)


if __name__ == "__main__":
    main()
