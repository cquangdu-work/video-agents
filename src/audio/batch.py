"""Đọc CẢ BÀI trong một lần gọi TTS rồi cắt lại thành từng câu.

Vì sao: free tier của Gemini TTS chỉ cho khoảng 15 lần gọi mỗi ngày cho mỗi model.
Đọc từng câu thì một video 12-19 câu ngốn sạch quota của ngày — chạy lại một lần
là hết. Đọc cả bài một lần: 1 lần gọi cho 1 video, giọng cũng liền mạch hơn.

Cách cắt (hàm synth_batch):
1. Nối các câu, gọi TTS một lần -> batch.wav
2. Whisper cho mốc thời gian từng từ -> DÓNG chuỗi từ nghe được với chuỗi từ của
   kịch bản (difflib) -> biết câu nào hết ở từ nào  (hàm sentence_gaps)
3. Dời điểm cắt vào giữa khoảng lặng thật gần đó (đo năng lượng âm thanh), để
   không cắt trúng tiếng                               (hàm quiet_cut)
4. Cắt WAV, gọt khoảng lặng thừa hai đầu -> v_XX.wav y như khi đọc từng câu.

Hai câu được đọc LIỀN HƠI (không có khoảng lặng ở giữa — model coi là một ý) thì
không cắt: cả hai nằm chung một file, hai cảnh hình dùng chung đoạn giọng đó.
Kết quả trả về là danh sách `owner`: owner[i] = câu mà file của nó chứa giọng câu i.

Chỗ nào không chắc ăn (Whisper nghe thiếu chữ, một đoạn dài/ngắn bất thường) thì
KHÔNG ghi file, owner[i] = None, và assemble đọc lẻ câu đó. Thà tốn thêm một lần
gọi còn hơn ra video cắt cụt giữa chữ.
"""
import difflib
import logging
import os
import re
import unicodedata
import wave
from pathlib import Path

log = logging.getLogger(__name__)

MIN_MATCH = 0.75      # tỷ lệ từ nghe được khớp kịch bản; thấp hơn = giọng đọc sai/thiếu
MIN_PAUSE = 0.15      # giây — lặng ngắn hơn thế là nghỉ giữa hai TỪ, không phải ngắt câu
SEARCH = 0.30         # giây — tìm khoảng lặng quanh mốc của Whisper trong bán kính này
KEEP_HEAD, KEEP_TAIL = 0.05, 0.10   # giây lặng giữ lại ở đầu/cuối mỗi đoạn sau khi gọt
FRAME = 0.01          # giây — độ phân giải khi đo năng lượng
JOIN = "nối"          # đánh dấu chỗ ngắt không cắt: hai câu đi chung một file


def batch_words() -> int:
    """Số từ tối đa cho một lần gọi TTS (.env TTS_BATCH_WORDS). 0 = tắt, đọc từng câu."""
    try:
        return int(os.getenv("TTS_BATCH_WORDS", "300"))
    except ValueError:
        return 300


def tokens(text: str) -> list:
    """Tách từ để so khớp: chữ thường, bỏ dấu câu. '38,4%' -> ['38', '4']."""
    text = unicodedata.normalize("NFC", str(text).lower())
    return re.sub(r"[^\w]+", " ", text).split()


def plan_chunks(texts: list, max_words: int) -> list:
    """Chia danh sách câu thành các mẻ liền nhau, mỗi mẻ không quá max_words từ.
    -> [[chỉ số câu, ...], ...]. Một câu dài hơn max_words vẫn đi thành mẻ riêng."""
    chunks, size = [], 0
    for i, t in enumerate(texts):
        n = len(t.split())
        if chunks and size + n <= max_words:
            chunks[-1].append(i)
            size += n
        else:
            chunks.append([i])
            size = n
    return chunks


def sentence_gaps(texts: list, words: list):
    """Tìm chỗ ngắt giữa các câu trên trục thời gian.

    texts: các câu theo thứ tự đọc. words: [(từ, bắt đầu, kết thúc)] của Whisper.
    -> [(giây hết từ cuối câu k, giây bắt đầu từ đầu câu k+1), ...] (n-1 phần tử),
    hoặc None nếu dóng không đáng tin.

    Whisper nghe sai vài từ (nhất là con số) là bình thường: difflib chỉ cần các từ
    khớp ở HAI BÊN chỗ ngắt. Nếu quanh chỗ ngắt có từ không khớp, chỗ ngắt là khe
    RỘNG NHẤT giữa hai từ liên tiếp trong đoạn đó (ngắt câu luôn nghỉ lâu nhất).
    """
    script, owner = [], []                  # từ của kịch bản + nó thuộc câu số mấy
    for k, t in enumerate(texts):
        tk = tokens(t)
        if not tk:
            return None
        script += tk
        owner += [k] * len(tk)
    heard, word_of = [], []                 # từ nghe được + nó thuộc "từ Whisper" số mấy
    for wi, w in enumerate(words):
        tk = tokens(w[0])
        heard += tk
        word_of += [wi] * len(tk)
    if not heard:
        return None
    sm = difflib.SequenceMatcher(a=script, b=heard, autojunk=False)
    if sm.ratio() < MIN_MATCH:
        log.warning("Giọng đọc chỉ khớp %.0f%% kịch bản — không dám cắt", sm.ratio() * 100)
        return None
    pair = {}                               # vị trí từ kịch bản -> vị trí từ nghe được
    for a, b, n in sm.get_matching_blocks():
        for d in range(n):
            pair[a + d] = b + d
    matched = sorted(pair)
    gaps = []
    for k in range(1, len(texts)):
        first = owner.index(k)              # từ đầu tiên của câu k
        left = max((i for i in matched if i < first), default=None)
        right = min((i for i in matched if i >= first), default=None)
        if left is None or right is None:
            return None
        wl, wr = word_of[pair[left]], word_of[pair[right]]
        if wr <= wl:
            return None                     # hai câu rơi vào cùng một từ của Whisper
        j = max(range(wl, wr), key=lambda j: words[j + 1][1] - words[j][2])
        gaps.append((words[j][2], words[j + 1][1]))
    if any(b[0] < a[1] for a, b in zip(gaps, gaps[1:])):
        return None                         # các chỗ ngắt phải tăng dần, không chồng nhau
    return gaps


def energy(samples, rate: int) -> list:
    """Độ to của âm thanh theo từng khung 10 ms (RMS). samples: mảng numpy int16."""
    import numpy as np
    step = max(int(FRAME * rate), 1)
    n = len(samples) // step
    if n == 0:
        return []
    block = samples[:n * step].astype(np.float64).reshape(n, step)
    return list(np.sqrt((block ** 2).mean(axis=1)))


def quiet_threshold(env: list) -> float:
    """Dưới mức này coi là lặng: 4% độ to điển hình của tiếng nói (phân vị 90)."""
    loud = sorted(env)[int(len(env) * 0.9)] if env else 0.0
    return max(loud * 0.04, 30.0)


def quiet_cut(env: list, thr: float, lo: float, hi: float):
    """Giữa giây lo và hi, tìm quãng lặng dài nhất -> trả về giây ở chính giữa quãng đó.
    Không có quãng lặng nào dài từ MIN_PAUSE trở lên thì trả về None."""
    a, b = max(int(lo / FRAME), 0), min(int(hi / FRAME) + 1, len(env))
    best, start = None, None
    for i in range(a, b + 1):
        quiet = i < b and env[i] < thr
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best is None or (best[1] - best[0]) * FRAME < MIN_PAUSE - 1e-9:
        return None
    return (best[0] + best[1]) / 2 * FRAME


def _trim(env: list, thr: float, a: float, b: float) -> tuple:
    """Gọt khoảng lặng thừa ở hai đầu đoạn [a, b] giây, chừa lại một chút cho tự nhiên."""
    i, j = int(a / FRAME), min(int(b / FRAME), len(env))
    while i < j and env[i] < thr:
        i += 1
    while j > i and env[j - 1] < thr:
        j -= 1
    return max(a, i * FRAME - KEEP_HEAD), min(b, j * FRAME + KEEP_TAIL)


def split_at_sentences(wav: Path, texts: list, words: list, out_paths: list,
                       can_join: list = None) -> list:
    """Cắt wav theo chỗ ngắt câu. -> owner (dài bằng texts):
      owner[i] == i     câu i có file riêng out_paths[i]
      owner[i] == j < i câu i được đọc liền hơi với câu j -> nằm chung trong out_paths[j]
      owner[i] is None  không chắc ăn, không ghi gì cho câu i (bên gọi đọc lẻ)

    can_join[k]: câu k và k+1 có được phép chung file không (hai cảnh phải liền nhau
    trong video). Mặc định là không.
    """
    import numpy as np
    n = len(texts)
    nothing = [None] * n
    with wave.open(str(wav), "rb") as w:
        params = w.getparams()
        raw = w.readframes(w.getnframes())
    if params.sampwidth != 2:
        log.warning("WAV không phải 16-bit (%d byte/mẫu) — không cắt", params.sampwidth)
        return nothing
    samples = np.frombuffer(raw, dtype=np.int16)
    if params.nchannels > 1:
        samples = samples.reshape(-1, params.nchannels).mean(axis=1).astype(np.int16)
    total = len(samples) / params.framerate
    env = energy(samples, params.framerate)
    thr = quiet_threshold(env)

    gaps = sentence_gaps(texts, words) if n > 1 else []
    if gaps is None:
        return nothing
    can_join = can_join or [False] * (n - 1)
    cuts, last = [], 0.0          # mỗi chỗ ngắt: giây cắt | JOIN | None (không dùng được)
    for k, (end_prev, start_next) in enumerate(gaps):
        cut = quiet_cut(env, thr, max(end_prev - SEARCH, last + 0.3), start_next + SEARCH)
        if cut is not None:
            cuts.append(cut)
            last = cut
        elif can_join[k]:
            log.info("Câu %d và %d được đọc liền hơi — để chung một đoạn giọng", k + 1, k + 2)
            cuts.append(JOIN)
        else:
            log.warning("Giữa câu %d và %d không có khoảng lặng — hai câu này sẽ đọc lẻ",
                        k + 1, k + 2)
            cuts.append(None)

    owner = list(nothing)
    chars = [max(len(t), 1) for t in texts]
    bytes_per_frame = params.sampwidth * params.nchannels
    a = 0
    while a < n:
        b = a                                           # đoạn [a..b] = các câu đi chung file
        while b < n - 1 and cuts[b] == JOIN:
            b += 1
        left = 0.0 if a == 0 else cuts[a - 1]
        right = total if b == n - 1 else cuts[b]
        if left is not None and right is not None:
            dur = right - left
            expect = total * sum(chars[a:b + 1]) / sum(chars)
            if dur >= 0.4 and 0.4 <= dur / expect <= 2.5:
                t0, t1 = _trim(env, thr, left, right)
                i, j = int(t0 * params.framerate), int(t1 * params.framerate)
                out_paths[a].parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(out_paths[a]), "wb") as w:
                    w.setparams(params)
                    w.writeframes(raw[i * bytes_per_frame:j * bytes_per_frame])
                for k in range(a, b + 1):
                    owner[k] = a
            else:   # dài/ngắn bất thường so với số chữ = cắt nhầm chỗ
                log.warning("Câu %d dài %.1fs, lẽ ra khoảng %.1fs — sẽ đọc lẻ", a + 1, dur, expect)
        a = b + 1
    return owner


def synth_batch(texts: list, out_paths: list, workdir: Path, can_join: list = None,
                synth=None, transcribe=None) -> list:
    """Đọc các câu `texts` bằng ít lần gọi TTS nhất. Trả về `owner` như split_at_sentences
    (chỉ số tính trên toàn bộ texts). Câu nào owner là None thì bên gọi tự đọc lẻ.

    synth/transcribe: để test thay hàm giả; mặc định là Gemini TTS và Whisper.
    QuotaExhausted từ TTS được ném thẳng lên cho assemble xử lý.
    """
    if synth is None:
        from .tts import synth
    if transcribe is None:
        from .subtitles import transcribe_words as transcribe
    can_join = can_join or [False] * (len(texts) - 1)
    owner = [None] * len(texts)
    for n, chunk in enumerate(plan_chunks(texts, batch_words())):
        if len(chunk) < 2:
            continue                        # một câu thì đọc lẻ luôn, khỏi cắt
        part = [texts[i] for i in chunk]
        raw = workdir / f"batch_{n:02d}.wav"
        log.info("TTS một lần cho %d câu (%d từ)...", len(part), sum(len(t.split()) for t in part))
        # Mỗi câu một đoạn riêng: model nghỉ lấy hơi giữa các đoạn -> có khoảng lặng để cắt
        synth("\n\n".join(part), raw, timeout=300)
        try:
            words = transcribe(raw)
            local = split_at_sentences(raw, part, words, [out_paths[i] for i in chunk],
                                       [can_join[i] for i in chunk[:-1]])
        except Exception as exc:            # lỗi khi cắt không được làm sập cả bước lắp ráp
            log.warning("Cắt giọng đọc theo câu lỗi (%s) — mẻ %d sẽ đọc lẻ", exc, n + 1)
            continue
        for pos, o in enumerate(local):
            if o is not None:
                owner[chunk[pos]] = chunk[o]
    return owner
