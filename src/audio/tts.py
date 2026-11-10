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


def synth(text: str, out_path: Path) -> Path:
    """Một câu/đoạn -> file WAV. Tự thử lại khi quá tải (503/429)."""
    model = os.getenv("TTS_MODEL", "gemini-3.8-flash-tts")
    voice = os.getenv("TTS_VOICE", "Kore")
    key = os.getenv("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    last = None
    for attempt in range(6):
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
            wait = 45 * (attempt + 1)          # free tier TTS giới hạn ~vài lần/phút
            log.warning("TTS lỗi (%s) — chờ %ds thử lại", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"TTS thất bại sau 6 lần: {last}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()
