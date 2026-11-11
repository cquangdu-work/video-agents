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


def _model_chain() -> list:
    """Model chính + dự phòng. Free tier giới hạn quota THEO NGÀY cho TỪNG model,
    nên khi một model cạn (429 dai dẳng) thì nhảy sang model khác, bucket khác."""
    chain = [os.getenv("TTS_MODEL", "gemini-3.8-flash-lite-tts")]
    chain += [m.strip() for m in os.getenv("TTS_MODEL_FALLBACKS", "").split(",") if m.strip()]
    return chain


def synth(text: str, out_path: Path) -> Path:
    """Một câu/đoạn -> file WAV. Thử lại khi quá tải; cạn quota thì đổi model dự phòng.

    Các model cùng tên giọng (TTS_VOICE) nghe gần nhau nhưng không giống hệt —
    một video lỡ trộn 2 model vẫn nghe ổn, có log warning để biết mà nghe lại kỹ.
    """
    voice = os.getenv("TTS_VOICE", "Kore")
    key = os.getenv("GEMINI_API_KEY")
    last = None
    for mi, model in enumerate(_model_chain()):
        if mi:
            log.warning("TTS chuyển sang model dự phòng: %s", model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        for attempt in range(3):
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=120)
                if r.status_code in (429, 503):
                    raise RuntimeError(f"HTTP {r.status_code}")
                r.raise_for_status()
                part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                audio = base64.b64decode(part["data"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(audio)        # mimeType là audio/wav sẵn
                return out_path
            except Exception as exc:
                last = exc
                wait = 45 * (attempt + 1)          # 429 nhất thời thì chờ là qua
                log.warning("TTS %s lỗi (%s) — chờ %ds thử lại", model, exc, wait)
                time.sleep(wait)
    raise RuntimeError(f"TTS thất bại trên mọi model: {last}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()
