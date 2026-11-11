"""Đọc CẢ BÀI trong một lần gọi TTS rồi cắt lại thành từng câu.

Vì sao: free tier của Gemini TTS chỉ cho khoảng 15 lần gọi mỗi ngày cho mỗi model.
Đọc từng câu thì một video 12-15 câu ngốn sạch quota của ngày — chạy lại một lần
là hết. Đọc cả bài một lần: 1 lần gọi cho 1 video, giọng cũng liền mạch hơn.

Cách cắt (hàm synth_batch):
1. Nối các câu, gọi TTS một lần -> batch.wav
2. Whisper cho mốc thời gian từng từ -> DÓNG chuỗi từ nghe được với chuỗi từ của
   kịch bản (difflib) -> biết câu nào hết ở từ nào  (hàm sentence_gaps)
3. Dời điểm cắt vào giữa khoảng lặng thật gần đó (đo năng lượng âm thanh), để
   không cắt trúng tiếng                               (hàm quiet_cut)
4. Cắt WAV, gọt khoảng lặng thừa hai đầu -> v_XX.wav y như khi đọc từng câu,
   nên phần còn lại của assemble không cần biết giọng được tạo kiểu nào.

Chỗ nào không chắc ăn (Whisper nghe thiếu chữ, hai câu dính liền không có khoảng
lặng, một câu dài/ngắn bất thường) thì KHÔNG ghi file nào và trả về 0 — assemble
quay lại cách đọc từng câu. Thà tốn quota còn hơn ra video cắt cụt giữa chữ.
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
MIN_PAUSE = 0.06      # giây — khoảng lặng ngắn hơn thế thì không coi là chỗ ngắt câu
SEARCH = 0.30         # giây — tìm khoảng lặng quanh mốc của Whisper trong bán kính này
KEEP_HEAD, KEEP_TAIL = 0.05, 0.10   # giây lặng giữ lại ở đầu/cuối mỗi câu sau khi gọt
FRAME = 0.01          # giây — độ phân giải khi đo năng lượng


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
    if any(b[0] <= a[1] for a, b in zip(gaps, gaps[1:])):
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
    if best is None or (best[1] - best[0]) * FRAME < MIN_PAUSE:
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


def split_at_sentences(wav: Path, texts: list, words: list, out_paths: list) -> bool:
    """Cắt wav thành len(texts) file theo chỗ ngắt câu. Trả về False (không ghi gì)
    nếu có chỗ không chắc ăn."""
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        params = w.getparams()
        raw = w.readframes(w.getnframes())
    if params.sampwidth != 2:
        log.warning("WAV không phải 16-bit (%d byte/mẫu) — không cắt", params.sampwidth)
        return False
    samples = np.frombuffer(raw, dtype=np.int16)
    if params.nchannels > 1:
        samples = samples.reshape(-1, params.nchannels).mean(axis=1).astype(np.int16)
    total = len(samples) / params.framerate
    env = energy(samples, params.framerate)
    thr = quiet_threshold(env)

    gaps = sentence_gaps(texts, words) if len(texts) > 1 else []
    if gaps is None:
        return False
    cuts = []
    for k, (end_prev, start_next) in enumerate(gaps):
        lo = max(end_prev - SEARCH, cuts[-1] + 0.3 if cuts else 0.0)
        cut = quiet_cut(env, thr, lo, start_next + SEARCH)
        if cut is None:
            log.warning("Giữa câu %d và %d không có khoảng lặng — không dám cắt", k + 1, k + 2)
            return False
        cuts.append(cut)
    bounds = [0.0] + cuts + [total]

    # Câu nào dài/ngắn bất thường so với số chữ của nó = cắt nhầm chỗ
    chars = [max(len(t), 1) for t in texts]
    for k, t in enumerate(texts):
        dur, expect = bounds[k + 1] - bounds[k], total * chars[k] / sum(chars)
        if dur < 0.4 or not 0.4 <= dur / expect <= 2.5:
            log.warning("Câu %d dài %.1fs, lẽ ra khoảng %.1fs — không dám cắt", k + 1, dur, expect)
            return False

    bytes_per_frame = params.sampwidth * params.nchannels
    for k, out in enumerate(out_paths):
        a, b = _trim(env, thr, bounds[k], bounds[k + 1])
        i, j = int(a * params.framerate), int(b * params.framerate)
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:
            w.setparams(params)
            w.writeframes(raw[i * bytes_per_frame:j * bytes_per_frame])
    return True


def synth_batch(texts: list, out_paths: list, workdir: Path, synth=None, transcribe=None) -> int:
    """Đọc các câu `texts` bằng ít lần gọi TTS nhất, ghi mỗi câu ra một file trong
    `out_paths`. Trả về số câu đã có file. Câu nào chưa có thì bên gọi tự đọc lẻ.

    synth/transcribe: để test thay hàm giả; mặc định là Gemini TTS và Whisper.
    QuotaExhausted từ TTS được ném thẳng lên cho assemble xử lý.
    """
    if synth is None:
        from .tts import synth
    if transcribe is None:
        from .subtitles import transcribe_words as transcribe
    done = 0
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
            ok = split_at_sentences(raw, part, words, [out_paths[i] for i in chunk])
        except Exception as exc:            # lỗi khi cắt không được làm sập cả bước lắp ráp
            log.warning("Cắt giọng đọc theo câu lỗi (%s)", exc)
            ok = False
        if ok:
            done += len(chunk)
        else:
            log.warning("Mẻ %d: quay về đọc từng câu", n + 1)
    return done
