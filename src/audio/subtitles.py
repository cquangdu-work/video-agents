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


# ------------------------------------------------------------------ cụm phụ đề tiếng Việt theo TỪ
# Tiếng Việt viết cách từng ÂM TIẾT: đếm 3 "từ" (khoảng trắng) một cụm là cắt ngang từ ghép — ca thật 26/11/2026
# (video CO2): "Trong 212 quốc" / "gia, Việt Nam" / "đứng thứ 91". Người xem tắt tiếng (và khán giả lớn tuổi
# của kênh) đọc rất khó. Cách làm: ghép âm tiết thành từ theo danh sách từ ghép (assets/lang/vi_words.txt + tên
# nước trong assets/geo/world.json), rồi chọn chỗ ngắt bằng quy hoạch động: cụm ~3 âm tiết, không cụm 1 âm tiết,
# không quá dài (xuống dòng), ưu tiên ngắt sau dấu phẩy, tránh tách con số khỏi chữ đi cùng ("thứ | 91").
ROOT = Path(__file__).resolve().parents[2]
VI_WORDS = ROOT / "assets" / "lang" / "vi_words.txt"
VI_GEO = ROOT / "assets" / "geo" / "world.json"
MAX_UNIT = 4                     # từ dài nhất (âm tiết) được giữ nguyên một khối
CHUNK_MAX = 4                    # cụm ghép từ nhiều từ: tối đa 4 âm tiết
SIZE_COST = {1: 3.0, 2: 0.3, 3: 0.0, 4: 0.6}     # 2 âm tiết thường là MỘT từ — vẫn dễ đọc
WRAP_CHARS = 17                  # quá chừng này ký tự thì phụ đề 88-96 px dễ xuống dòng
_PUNCT = "\"'“”‘’()[]«»"
_SOFT_END = (",", ";", ":")
UNIT_WORDS = {"lần", "kg", "km", "tấn", "tỷ", "triệu", "nghìn", "usd", "đô", "độ", "giờ", "phút", "giây", "tuổi",
              "kwh", "mét", "lít", "dặm", "điểm", "%", "người", "năm", "tháng", "ngày", "tuần"}
_ANY_END = (".", ",", "!", "?", "…", ";", ":")


def _key(token: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", str(token)).strip(_PUNCT + ".,!?…;:").lower()


def _vi_lexicon() -> frozenset:
    global _LEXICON
    if _LEXICON is None:
        import json
        words = set()
        try:
            for line in VI_WORDS.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    words.add(" ".join(_key(x) for x in line.split()))
        except OSError:
            log.warning("Không đọc được %s — phụ đề chia theo âm tiết", VI_WORDS)
        try:
            for c in json.loads(VI_GEO.read_text(encoding="utf-8"))["countries"].values():
                for name in [c.get("name", "")] + list(c.get("aliases") or []):
                    words.add(" ".join(_key(x) for x in str(name).replace("-", " ").split()))
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        _LEXICON = frozenset(w for w in words if 2 <= len(w.split()) <= MAX_UNIT)
    return _LEXICON


_LEXICON = None


def vi_units(tokens: list) -> list:
    """Độ dài (số âm tiết) của từng từ, ghép tham lam từ dài nhất: ["Trong","212","quốc","gia,"] -> [1, 1, 2].
    Không ghép qua dấu câu (âm tiết giữa từ không được mang dấu phẩy/chấm)."""
    lex, out, i = _vi_lexicon(), [], 0
    while i < len(tokens):
        for size in range(min(MAX_UNIT, len(tokens) - i), 1, -1):
            seq = tokens[i:i + size]
            if any(t.rstrip(_PUNCT).endswith(_ANY_END) for t in seq[:-1]):
                continue                    # có dấu câu bên trong
            if " ".join(_key(t) for t in seq) in lex:
                out.append(size)
                i += size
                break
        else:
            out.append(1)
            i += 1
    return out


def _is_number(token: str) -> bool:
    """Con số ("91", "1,37", "60,5%") — không tính chữ có số bên trong như "CO2"."""
    return token.strip(_PUNCT)[:1].isdigit()


def _vi_split(seg: list) -> list:
    """Một đoạn liền (không có cuối câu / chỗ nghỉ bên trong) -> các cụm, chỉ ngắt giữa hai từ."""
    tokens = [w[0] for w in seg]
    bounds = [0]
    for size in vi_units(tokens):
        bounds.append(bounds[-1] + size)

    def cost(a: int, b: int) -> float:
        part = tokens[a:b]
        c = SIZE_COST.get(b - a, 2.5)
        chars = len(" ".join(part))
        c += 1.5 if chars > WRAP_CHARS else 0.0
        c += 3.0 if chars > WRAP_CHARS + 6 else 0.0
        if any(t.rstrip(_PUNCT).endswith(_SOFT_END) for t in part[:-1]):
            c += 0.8                        # dấu phẩy nằm GIỮA cụm: "Năm 2023, lượng" — nên ngắt ở dấu phẩy
        if b < len(tokens):                 # chỗ ngắt nằm giữa đoạn
            if part[-1].rstrip(_PUNCT).endswith(_SOFT_END):
                c -= 0.5                    # ngắt sau dấu phẩy: tự nhiên nhất
            elif _is_number(tokens[b]):
                c += 1.0                    # "đứng thứ | 91": số tách khỏi chữ dẫn tới nó
            elif _is_number(part[-1]):     # sau số hay là chỗ ngắt tự nhiên ("đứng thứ 91 | về..."), trừ khi
                c += 1.2 if _key(tokens[b]) in UNIT_WORDS else 0.4    # chữ sau là đơn vị: "60,5 | kg"
        return c

    best = {0: (0.0, None)}
    for j in range(1, len(bounds)):
        b = bounds[j]
        for i in range(j - 1, -1, -1):
            a = bounds[i]
            if b - a > CHUNK_MAX and j - i > 1:
                break                       # nhiều từ ghép lại thì tối đa CHUNK_MAX âm tiết (một từ dài vẫn được)
            if a in best:
                c = best[a][0] + cost(a, b)
                if b not in best or c < best[b][0]:
                    best[b] = (c, a)
    cuts, b = [], len(tokens)
    while b:
        a = best[b][1]
        cuts.append(seg[a:b])
        b = a
    return cuts[::-1]


def chunk_words(words: list, chunk_size: int = 3, pause: float = 0.35, language: str = None) -> list:
    """Chia các từ thành cụm phụ đề tối đa chunk_size từ, và LUÔN ngắt cụm ở cuối câu
    (từ kết thúc bằng . ! ? …) hoặc chỗ nghỉ dài hơn `pause` giây.

    Trước đây cứ đếm đủ 3 từ là ngắt nên cụm hay vắt ngang hai câu ("phòng nữa. Công"):
    chữ của câu sau hiện ra khi người xem còn đang nghe câu trước.

    Kênh tiếng Việt: cụm theo TỪ chứ không theo âm tiết (_vi_split); kênh Hàn đã cách theo 어절 nên giữ như cũ.
    """
    ends = lambda w: w[0].rstrip('"”’)').endswith(SENTENCE_END)
    if language is None:
        from .. import lang
        language = lang.code()
    if language == "vi" and words:
        segs = []
        for i, w in enumerate(words):
            prev = words[i - 1] if i else None
            if not segs or ends(prev) or w[1] - prev[2] > pause:
                segs.append([])
            segs[-1].append(w)
        return [chunk for seg in segs for chunk in _vi_split(seg)]
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
