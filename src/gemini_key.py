"""KHOÁ GEMINI DỰ PHÒNG (22/11/2026): khoá chính bị Google chặn thì tự chạy bằng khoá dự phòng.

Ca thật: khoá Gemini riêng của kênh Hàn (project Google Cloud mới) chạy được ngày 21/11, sáng 22/11 bị chặn ở mọi
model — 403 "The Gemini API free tier is not available for this project" — và lượt 07:30 không ra video. Diễn đàn
của Google có nhiều ca giống vậy, không báo trước, không rõ khi nào được mở lại.

Cách làm: `.env` có thêm GEMINI_API_KEY_FALLBACK (khoá của kênh kia). Đầu mỗi lượt daily và lúc bot duyệt khởi động,
`ensure()` gọi thử khoá chính MỘT lần (model nhỏ, câu hỏi một chữ). Bị chặn (403 PERMISSION_DENIED) -> đặt
GEMINI_API_KEY = khoá dự phòng cho tiến trình này và mọi tiến trình con (các bước của daily kế thừa biến môi trường;
load_dotenv không ghi đè biến đã có), báo Du qua Telegram tối đa mỗi ngày một lần. Lỗi khác (mạng, 429 hết hạn mức,
503) -> giữ khoá chính: đó không phải khoá hỏng.
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)
PROBE_MODEL = "gemini-3.5-flash-lite"
NOTICE = Path(__file__).resolve().parent.parent / "data" / "gemini_key_notice.txt"     # ngày đã báo Du


def probe(key: str, post=None) -> str:
    """"ok" | "blocked" (khoá bị Google chặn / sai) | "error" (lỗi khác: mạng, hết hạn mức...)."""
    try:
        r = (post or requests.post)(
            f"https://generativelanguage.googleapis.com/v1beta/models/{PROBE_MODEL}:generateContent",
            params={"key": key}, timeout=30, json={"contents": [{"parts": [{"text": "1"}]}],
                                                   "generationConfig": {"maxOutputTokens": 1}})
    except requests.RequestException:
        return "error"
    if r.status_code == 200:
        return "ok"
    if r.status_code in (400, 401, 403):
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        text = f"{err.get('status', '')} {err.get('message', '')}"
        if r.status_code == 403 or "API_KEY_INVALID" in text or "API key not valid" in text:
            return "blocked"
    return "error"


def ensure(notify: bool = True, post=None) -> str:
    """Bảo đảm GEMINI_API_KEY của tiến trình này dùng được. -> "primary" | "fallback" | "skip"."""
    if os.getenv("GEMINI_KEY_CHECKED"):              # tiến trình cha đã kiểm (bước con của daily)
        return "skip"
    os.environ["GEMINI_KEY_CHECKED"] = "1"
    key, fallback = os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_API_KEY_FALLBACK")
    if not key or not fallback or key == fallback:
        return "skip"
    if probe(key, post) != "blocked":
        return "primary"
    if probe(fallback, post) == "blocked":
        log.error("Cả khoá Gemini chính lẫn dự phòng đều bị Google chặn")
        return "primary"
    os.environ["GEMINI_API_KEY"] = fallback
    log.warning("Khoá Gemini chính bị Google chặn — tiến trình này chạy bằng khoá dự phòng (GEMINI_API_KEY_FALLBACK)")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        seen = NOTICE.read_text(encoding="utf-8").strip()
    except OSError:
        seen = ""
    if notify and seen != today:
        try:
            from . import telegram_bot as tg
            tg.send_message("⚠️ Khoá Gemini chính của kênh này bị Google chặn (403 — project không được dùng gói miễn"
                            " phí). Hôm nay chạy bằng khoá dự phòng (dùng chung hạn mức với kênh kia) — video vẫn ra"
                            " bình thường. Muốn sửa hẳn: gửi Claude khoá mới hoặc bật thanh toán cho project bị chặn.")
            NOTICE.parent.mkdir(parents=True, exist_ok=True)
            NOTICE.write_text(today, encoding="utf-8")
        except Exception as exc:
            log.warning("Không báo được Du qua Telegram: %s", exc)
    return "fallback"
