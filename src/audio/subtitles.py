"""Phụ đề khớp TỪNG TỪ bằng Whisper (faster-whisper, chạy CPU).

Ta đã biết chính xác lời đọc — Whisper chỉ dùng để lấy MỐC THỜI GIAN của từng từ
trong file giọng đã ghép. Xuất ra .ass (hiện theo cụm 3 từ, kiểu video ngắn).
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def transcribe_words(audio_path: Path, model_size: str = "small") -> list:
    """[(từ, giây bắt đầu, giây kết thúc), ...]

    Nạp WAV bằng numpy rồi đưa thẳng mảng cho Whisper — né xung đột phiên bản
    thư viện av giữa faster-whisper và manim (cùng venv).
    """
    import subprocess
    import wave as wave_mod

    import numpy as np
    from faster_whisper import WhisperModel   # import muộn: model tải lần đầu hơi lâu

    wav16 = audio_path.with_name(audio_path.stem + "_16k.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(audio_path),
                    "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(wav16)], check=True)
    with wave_mod.open(str(wav16), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32) / 32768.0

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    from .. import lang                           # ngôn ngữ của kênh (vi | ko)
    segments, _ = model.transcribe(audio, language=lang.whisper_code(), word_timestamps=True)
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


def merge_number_pieces(heard: list) -> list:
    """Whisper (tiếng Hàn) tách một con số thành nhiều "từ": "11", ".6", "%로" — kịch bản chỉ có MỘT từ "11.6%로". Ghép
    mảnh bắt đầu bằng . , % vào từ trước khi từ trước tận cùng bằng chữ số (lấy mốc đầu của từ trước, mốc cuối của
    mảnh). Ca thật 24/11/2026 (chạy thử bản đồ 시군구): ba con số thập phân làm độ khớp tụt còn 59% < 60% -> phụ đề
    lùi về chữ Whisper và ngắt dòng ngay giữa số (".6 %로 최저입니다")."""
    out = []
    for w, s, e in heard:
        text = str(w).strip()
        if out and text[:1] in ".,%" and str(out[-1][0]).strip()[-1:].isdigit():
            pw, ps, _ = out[-1]
            out[-1] = (str(pw).strip() + text, ps, e)
        else:
            out.append((w, s, e))
    return out


def script_words_timed(script_words: list, heard: list, min_match: float = 0.6) -> list:
    """Phụ đề hiện CHỮ CỦA KỊCH BẢN, chỉ mượn MỐC THỜI GIAN của Whisper.

    script_words: các từ đúng như kịch bản viết (còn nguyên dấu câu, số liệu).
    heard: [(từ Whisper nghe được, bắt đầu, kết thúc)].
    -> [(từ kịch bản, bắt đầu, kết thúc)]

    Whisper nghe nhầm là chuyện thường ("phàn nàn" thành "phan an", "Paris" thành
    "berries", số bị viết kiểu khác). Chữ nghe nhầm mà hiện lên phụ đề là lỗi chính tả
    ngay trên video. Ở đây difflib dóng hai chuỗi từ: từ nào khớp thì lấy đúng mốc của
    nó; đoạn không khớp thì các từ kịch bản chia đều quãng thời gian của đoạn đó.
    Khớp quá kém (giọng đọc hỏng) thì trả nguyên `heard` như cũ.
    """
    import difflib

    from .batch import tokens

    key = lambda w: "".join(tokens(w))
    heard = merge_number_pieces(heard)
    a, b = [key(w) for w in script_words], [key(h[0]) for h in heard]
    if not a or not b:
        return list(heard)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    if sm.ratio() < min_match:
        log.warning("Phụ đề: chữ nghe được chỉ khớp %.0f%% kịch bản — dùng chữ của Whisper",
                    sm.ratio() * 100)
        return list(heard)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out += [(script_words[i1 + k], heard[j1 + k][1], heard[j1 + k][2])
                    for k in range(i2 - i1)]
        elif i2 > i1:                           # có từ kịch bản cần được xếp chỗ
            if j2 > j1:                         # ... thay cho một đoạn Whisper nghe khác đi
                t0, t1 = heard[j1][1], heard[j2 - 1][2]
            else:                               # ... mà Whisper bỏ sót: nhét vào khe hai bên
                t0 = heard[j1 - 1][2] if j1 else 0.0
                t1 = heard[j1][1] if j1 < len(heard) else t0
            t1 = max(t1, t0 + 0.12 * (i2 - i1))
            step = (t1 - t0) / (i2 - i1)
            out += [(script_words[i1 + k], t0 + k * step, t0 + (k + 1) * step)
                    for k in range(i2 - i1)]
        # tag == "insert": Whisper nghe thừa chữ không có trong kịch bản -> bỏ
    fixed, last_end = [], 0.0                   # mốc phải tăng dần, không chồng lên nhau
    for word, start, end in out:
        start = max(start, last_end)
        end = max(end, start + 0.05)
        fixed.append((word, start, end))
        last_end = end
    return fixed


SENTENCE_END = (".", "!", "?", "…", ":", ";")


def chunk_words(words: list, chunk_size: int = 3, pause: float = 0.35) -> list:
    """Chia các từ thành cụm phụ đề tối đa chunk_size từ, và LUÔN ngắt cụm ở cuối câu
    (từ kết thúc bằng . ! ? …) hoặc chỗ nghỉ dài hơn `pause` giây.

    Trước đây cứ đếm đủ 3 từ là ngắt nên cụm hay vắt ngang hai câu ("phòng nữa. Công"):
    chữ của câu sau hiện ra khi người xem còn đang nghe câu trước.
    """
    ends = lambda w: w[0].rstrip('"”’)').endswith(SENTENCE_END)
    chunks = []
    for i, w in enumerate(words):
        prev = words[i - 1] if i else None
        new = (not chunks or len(chunks[-1]) >= chunk_size or ends(prev)
               or w[1] - prev[2] > pause)
        if new:
            chunks.append([])
        chunks[-1].append(w)
    # Cụm cuối câu chỉ còn MỘT từ ("...chưa từng | có.") chớp lên rồi tắt, rất khó đọc:
    # kéo một từ từ cụm trước sang cho thành 2 + 2.
    for k in range(1, len(chunks)):
        cur, before = chunks[k], chunks[k - 1]
        if (len(cur) == 1 and len(before) == chunk_size and chunk_size > 2
                and not ends(before[-1]) and cur[0][1] - before[-1][2] <= pause):
            cur.insert(0, before.pop())
    return chunks


def build_ass(words: list, out_path: Path, brand: dict, chunk_size: int = 3) -> Path:
    """Gom tối đa 3 từ một cụm (không vắt qua câu khác); từ đang đọc tô màu accent —
    đúng 'phụ đề theo từng từ'."""
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
    for chunk in chunk_words(words, chunk_size):
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
