"""Kênh liên lạc với Du qua Telegram — gửi kịch bản/video và NHẬN nút bấm duyệt.

Dùng thẳng Bot API qua HTTP (requests) cho nhẹ, không cần thư viện bot:
  - gửi:  sendMessage / sendVideo / sendDocument (kèm nút bấm inline)
  - nhận: getUpdates kiểu "long polling" — bot hỏi Telegram "có gì mới không?" và
          Telegram giữ kết nối tới khi có sự kiện. Không cần mở cổng/webhook trên VM.
"""
import html
import json
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CAPTION_MAX = 1024       # giới hạn chú thích kèm video/file của Telegram
MESSAGE_MAX = 4096


def chat_id() -> str:
    return str(os.getenv("TELEGRAM_CHAT_ID") or "")


def _call(method: str, files: dict = None, http_timeout: int = 20, **params):
    """Gọi một hàm Bot API. Trả về trường "result" hoặc None nếu lỗi (đã ghi log)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        log.warning("Thiếu TELEGRAM_BOT_TOKEN — bỏ qua %s", method)
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    params = {k: v for k, v in params.items() if v is not None}
    try:
        if files:
            # Gửi file phải dùng multipart -> các tham số dạng object phải tự đóng JSON
            data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                        else str(v).lower() if isinstance(v, bool) else v)
                    for k, v in params.items()}
            r = requests.post(url, data=data, files=files, timeout=http_timeout)
        else:
            r = requests.post(url, json=params, timeout=http_timeout)
        body = r.json()
        if not body.get("ok"):
            log.error("Telegram %s lỗi: %s", method, body.get("description"))
            return None
        return body.get("result")
    except Exception as exc:
        # KHÔNG in exc nguyên văn kèm URL: URL chứa token của bot
        log.error("Telegram %s lỗi kết nối: %s", method, type(exc).__name__)
        return None


def keyboard(rows: list) -> dict:
    """[[("✅ Duyệt", "ok:3"), ("❌ Loại", "no:3")]] -> cấu trúc nút bấm inline."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                for row in rows]}


def send_message(text: str, buttons: list = None, as_html: bool = False,
                 reply_to: int = None):
    """Gửi tin nhắn chữ. Trả về message_id (truthy) hoặc None nếu không gửi được."""
    if not chat_id():
        log.warning("Thiếu TELEGRAM_CHAT_ID — không gửi được")
        return None
    res = _call("sendMessage", chat_id=chat_id(), text=text[:MESSAGE_MAX - 96],
                disable_web_page_preview=True,
                parse_mode="HTML" if as_html else None,
                reply_markup=keyboard(buttons) if buttons else None,
                reply_to_message_id=reply_to)
    return res["message_id"] if res else None


def _send_file(method: str, field: str, path: Path, caption: str, buttons: list, **extra):
    if not chat_id():
        log.warning("Thiếu TELEGRAM_CHAT_ID — không gửi được")
        return None
    with open(path, "rb") as fh:
        res = _call(method, files={field: (Path(path).name, fh)}, http_timeout=180,
                    chat_id=chat_id(), caption=(caption or "")[:CAPTION_MAX],
                    reply_markup=keyboard(buttons) if buttons else None, **extra)
    return res["message_id"] if res else None


def send_video(path: Path, caption: str = "", buttons: list = None):
    """Gửi video xem được ngay trong Telegram (để duyệt). Trả về message_id."""
    return _send_file("sendVideo", "video", path, caption, buttons, supports_streaming=True)


def send_photo(path: Path, caption: str = "", buttons: list = None, reply_to: int = None):
    """Gửi ẢNH (xem trước bài viết Facebook). Trả về message_id."""
    return _send_file("sendPhoto", "photo", path, caption, buttons, reply_to_message_id=reply_to)


def send_document(path: Path, caption: str = "", buttons: list = None):
    """Gửi FILE GỐC (Telegram không nén lại) — dùng khi Du cần tải về để tự đăng."""
    return _send_file("sendDocument", "document", path, caption, buttons)


def get_updates(offset: int = 0, timeout: int = 50):
    """Lấy sự kiện mới (nút bấm, tin nhắn). None = lỗi mạng, [] = không có gì mới."""
    # timeout = số giây Telegram giữ kết nối chờ sự kiện; HTTP phải chờ lâu hơn thế
    return _call("getUpdates", http_timeout=timeout + 15, offset=offset, timeout=timeout,
                 allowed_updates=["callback_query", "message"])


def answer_callback(callback_id: str, text: str = "") -> None:
    """Tắt vòng xoay "đang tải" trên nút vừa bấm, kèm một dòng thông báo nhỏ."""
    _call("answerCallbackQuery", callback_query_id=callback_id, text=text[:190])


def clear_buttons(message_id: int) -> None:
    """Gỡ nút khỏi tin nhắn đã xử lý xong — tránh bấm nhầm lần hai."""
    _call("editMessageReplyMarkup", chat_id=chat_id(), message_id=message_id,
          reply_markup={"inline_keyboard": []})


def delete_message(message_id) -> None:
    """Xoá một tin trong cuộc trò chuyện (vd tin Du gửi có chứa token). Lỗi thì bỏ qua."""
    if message_id:
        _call("deleteMessage", chat_id=chat_id(), message_id=message_id)


def code(text: str) -> str:
    """Bọc chữ trong <code> (chế độ HTML): trên điện thoại chạm một cái là copy."""
    return f"<code>{html.escape(str(text))}</code>"


def format_script_message(idea: dict, script: dict, factcheck: dict) -> str:
    hooks = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(script.get("hooks", [])))
    scenes = "\n".join(
        f"  🎬 {s['voice']}\n     [{s['visual']}]" for s in script.get("scenes", [])
    )
    fc = "✅ Kiểm chứng ĐẠT" if factcheck.get("pass") else "⚠️ Có điểm chưa kiểm chứng được"
    fails = [v for v in factcheck.get("verdicts", []) if not v.get("ok")]
    fc_detail = "\n".join(f"  ⚠️ {v['claim']} — {v['note']}" for v in fails)
    return (
        f"📝 {idea['title']}\n"
        f"📐 Góc: {idea['angle']}\n"
        f"🔗 Nguồn: {idea['source_url']}\n\n"
        f"HOOK (chọn 1):\n{hooks}\n\n"
        f"KỊCH BẢN:\n{scenes}\n\n"
        f"{fc}\n{fc_detail}"
    )
