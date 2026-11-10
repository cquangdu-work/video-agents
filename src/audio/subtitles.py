"""Phụ đề khớp TỪNG TỪ bằng Whisper (faster-whisper, chạy CPU).

Ta đã biết chính xác lời đọc — Whisper chỉ dùng để lấy MỐC THỜI GIAN của từng từ
trong file giọng đã ghép. Xuất ra .ass (hiện theo cụm 3 từ, kiểu video ngắn).
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def transcribe_words(audio_path: Path, model_size: str = "small") -> list:
    """[(từ, giây bắt đầu, giây kết thúc), ...]"""
    from faster_whisper import WhisperModel   # import muộn: model tải lần đầu hơi lâu
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), language="vi", word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.word.strip(), w.start, w.end))
    log.info("Whisper: %d từ có mốc thời gian", len(words))
    return words


def _ts(sec: float) -> str:
    h, rem = divmod(max(sec, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words: list, out_path: Path, brand: dict, chunk_size: int = 3) -> Path:
    """Gom 3 từ một cụm; từ đang đọc tô màu accent — đúng 'phụ đề theo từng từ'."""
    c = brand["colors"]

    def ass_color(hex_color: str) -> str:              # #RRGGBB -> &H00BBGGRR
        r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
        return f"&H00{b}{g}{r}".upper()

    font = brand["fonts"]["primary"][1]                # Segoe UI: chắc chắn có trên Windows
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},76,{ass_color(c['text'])},{ass_color(c['accent'])},&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        start, end = chunk[0][1], chunk[-1][2]
        # mỗi từ trong cụm đổi sang màu accent đúng lúc nó được đọc
        for j, (word, ws, we) in enumerate(chunk):
            text = " ".join(
                (r"{\c" + _accent(c) + "}" + w + r"{\c" + _text(c) + "}") if k == j else w
                for k, (w, _, _) in enumerate(chunk))
            w_end = chunk[j + 1][1] if j + 1 < len(chunk) else end
            lines.append(f"Dialogue: 0,{_ts(ws)},{_ts(max(w_end, ws + 0.05))},Word,,0,0,0,,{text}")
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8-sig")
    return out_path


def _accent(c):
    r, g, b = c["accent"][1:3], c["accent"][3:5], c["accent"][5:7]
    return f"&H00{b}{g}{r}&".upper()


def _text(c):
    r, g, b = c["text"][1:3], c["text"][3:5], c["text"][5:7]
    return f"&H00{b}{g}{r}&".upper()
