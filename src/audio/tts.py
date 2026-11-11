"""Giọng đọc bằng Gemini TTS (quyết định của Du 11/11/2026: giọng AI trước,
sau này muốn đổi sang giọng nhân bản của Du thì chỉ thay file này).

Chống "giọng máy đều đều" (luật chính sách): mỗi câu được kèm chỉ dẫn phong cách
đọc, và model TTS thế hệ mới tự nhấn nhá theo nội dung.
"""
import base64
import logging
import os
import time
import wave
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# QUAN TRỌNG: gemini-3.8-flash-tts đọc NGUYÊN VĂN mọi chữ trong text — đã thử
# chỉ dẫn phong cách cả tiếng Việt lẫn tiếng Anh đều bị đọc ra loa. Vì vậy chỉ
# gửi đúng nội dung; muốn đổi chất giọng thì đổi TTS_VOICE trong .env.
STYLE = ""

MAX_TRIES = 3            # số lần thử mỗi model khi lỗi là nhất thời (quá tải, quota phút)
MAX_WAIT = 150           # giây — trần cho một lần chờ


class QuotaExhausted(RuntimeError):
    """MỌI model TTS đều hết quota. Đây là lỗi TẠM THỜI của dịch vụ, không phải tại
    kịch bản: assemble bắt lỗi này để thoát bằng mã riêng, daily không tính là hỏng."""


# Model đã cạn quota trong tiến trình này -> các cảnh sau bỏ qua luôn, khỏi chờ lại.
# (Mỗi lượt assemble là một tiến trình mới nên sang hôm sau tập này tự rỗng.)
_spent = set()


def _model_chain() -> list:
    """Model chính + dự phòng. Free tier giới hạn quota THEO NGÀY cho TỪNG model,
    nên khi một model cạn (429 dai dẳng) thì nhảy sang model khác, bucket khác."""
    chain = [os.getenv("TTS_MODEL", "gemini-3.8-flash-lite-tts")]
    chain += [m.strip() for m in os.getenv("TTS_MODEL_FALLBACKS", "").split(",") if m.strip()]
    return chain


def _quota_info(resp) -> tuple:
    """Đọc thân lỗi 429 của Gemini -> (cạn quota NGÀY?, số giây API bảo chờ, mô tả ngắn).

    Thân lỗi có dạng {"error": {"message": ..., "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"retryDelay": "34s"}]}}
    Quota NGÀY thì chờ vài phút vô ích (tới khoảng 16-17h giờ Hàn mới hồi) -> đổi model
    ngay. Quota PHÚT thì chờ đúng số giây API báo là qua. Đọc không ra thì trả về
    (False, None, ...) để bên gọi xử lý kiểu thận trọng: chờ rồi thử lại.
    """
    try:
        err = resp.json().get("error", {})
        details = [d for d in err.get("details", []) if isinstance(d, dict)]
    except (ValueError, AttributeError):
        return False, None, (getattr(resp, "text", "") or "")[:160]
    quota_ids, delay = [], None
    for d in details:
        quota_ids += [str(v.get("quotaId", "")) for v in d.get("violations", [])
                      if isinstance(v, dict)]
        if "retryDelay" in d:
            try:
                delay = float(str(d["retryDelay"]).rstrip("s"))
            except ValueError:
                pass
    daily = any("PerDay" in q for q in quota_ids)
    note = ", ".join(q for q in quota_ids if q) or str(err.get("message", ""))[:160]
    return daily, delay, note


def synth(text: str, out_path: Path) -> Path:
    """Một câu/đoạn -> file WAV. Thử lại khi quá tải; cạn quota thì đổi model dự phòng.

    Các model cùng tên giọng (TTS_VOICE) nghe gần nhau nhưng không giống hệt —
    một video lỡ trộn 2 model vẫn nghe ổn, có log warning để biết mà nghe lại kỹ.
    """
    voice = os.getenv("TTS_VOICE", "Kore")
    key = os.getenv("GEMINI_API_KEY")
    body = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    chain = _model_chain()
    last = "chưa gọi được model nào"
    for model in chain:
        if model in _spent:
            continue
        if model != chain[0]:
            log.warning("TTS dùng model dự phòng: %s", model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(MAX_TRIES):
            wait = 45 * (attempt + 1)
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=120)
            except requests.RequestException as exc:      # rớt mạng, quá giờ
                # Chỉ ghi TÊN lỗi: nội dung lỗi của requests chứa cả URL kèm khoá API
                why = type(exc).__name__
                last = f"{model}: {why}"
                log.warning("TTS %s lỗi mạng (%s) — chờ %ds thử lại", model, why, wait)
                time.sleep(wait)
                continue
            if r.status_code == 200:
                part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(base64.b64decode(part["data"]))   # audio/wav sẵn
                return out_path
            if r.status_code == 429:
                daily, delay, note = _quota_info(r)
                last = f"{model}: HTTP 429 ({note})"
                if daily:
                    log.warning("TTS %s hết quota NGÀY (%s) — bỏ qua model này", model, note)
                    _spent.add(model)
                    break
                if attempt == MAX_TRIES - 1:
                    # Chờ đủ kiểu vẫn 429 -> coi như cạn, để các cảnh sau khỏi chờ lại
                    log.warning("TTS %s vẫn 429 sau %d lần (%s) — bỏ qua model này",
                                model, MAX_TRIES, note)
                    _spent.add(model)
                    break
                if delay is not None:
                    wait = min(delay + 2, MAX_WAIT)
                log.warning("TTS %s chạm giới hạn (%s) — chờ %.0fs thử lại", model, note, wait)
                time.sleep(wait)
            elif r.status_code >= 500:                    # máy chủ quá tải: chờ là qua
                last = f"{model}: HTTP {r.status_code}"
                log.warning("TTS %s quá tải (HTTP %d) — chờ %ds thử lại",
                            model, r.status_code, wait)
                time.sleep(wait)
            else:   # 400/403/404: sai tên model, khoá hỏng... thử lại cũng vậy -> model kế
                last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                log.warning("TTS %s từ chối (HTTP %d): %s", model, r.status_code, r.text[:200])
                break
    # Có model cạn quota -> chạy lại sau là được (kể cả khi model dự phòng khác bị
    # lỗi kiểu khác, ví dụ ghi sai tên): báo "tạm thời". Còn lại mới là hỏng thật.
    spent = [m for m in chain if m in _spent]
    if spent:
        raise QuotaExhausted(f"Hết quota TTS ({', '.join(spent)}). Lỗi cuối: {last}")
    raise RuntimeError(f"TTS thất bại trên mọi model: {last}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()
