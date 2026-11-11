"""Test đọc gộp cả bài rồi cắt theo câu — không gọi mạng, không cần Whisper/ffmpeg.

    python -m unittest discover -s tests -v
"""
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from src.audio import batch, tts

RATE = 24000
S1, S2, S3 = "Xin chào các bạn.", "Giá đã rớt 38,4% sau 15 ngày.", "Hẹn gặp lại!"


def make_wav(path: Path, plan: list) -> Path:
    """plan = [("tone"|"quiet", giây), ...] -> file WAV 24 kHz mono 16-bit."""
    chunks = []
    for kind, secs in plan:
        t = np.arange(int(secs * RATE)) / RATE
        amp = 9000 if kind == "tone" else 0
        chunks.append((amp * np.sin(2 * np.pi * 220 * t)).astype(np.int16))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(np.concatenate(chunks).tobytes())
    return path


def spread(text: str, start: float, end: float) -> list:
    """Giả lập Whisper: chia đều các từ của một câu trong khoảng [start, end]."""
    ws = text.split()
    step = (end - start) / len(ws)
    return [(w, start + i * step, start + (i + 1) * step - 0.02) for i, w in enumerate(ws)]


class AlignTest(unittest.TestCase):
    def test_tokens_drop_punctuation_and_split_numbers(self):
        self.assertEqual(batch.tokens("Giá rớt 38,4%!"), ["giá", "rớt", "38", "4"])

    def test_plan_chunks_respects_word_budget(self):
        texts = ["một hai ba", "bốn năm", "sáu bảy tám chín", "mười"]
        self.assertEqual(batch.plan_chunks(texts, 300), [[0, 1, 2, 3]])
        self.assertEqual(batch.plan_chunks(texts, 5), [[0, 1], [2, 3]])
        self.assertEqual(batch.plan_chunks(texts, 1), [[0], [1], [2], [3]])

    def test_boundary_found_when_everything_is_heard_right(self):
        words = spread(S1, 0.0, 1.0) + spread(S2, 1.3, 2.5) + spread(S3, 2.8, 3.6)
        gaps = batch.sentence_gaps([S1, S2, S3], words)
        self.assertEqual(len(gaps), 2)
        self.assertAlmostEqual(gaps[0][0], 0.98, places=2)     # hết "bạn."
        self.assertAlmostEqual(gaps[0][1], 1.30, places=2)     # bắt đầu "Giá"
        self.assertAlmostEqual(gaps[1][1], 2.80, places=2)

    def test_misheard_numbers_at_the_boundary_fall_back_to_the_widest_gap(self):
        # Whisper đọc số thành chữ và nghe sai cả từ đầu câu sau -> hai bên chỗ ngắt
        # đều không khớp; chỗ ngắt vẫn đúng vì đó là khe rộng nhất trong đoạn mù
        a = "Theo số liệu mới nhất thì sau 15 ngày giá của máy đã rớt 38,4%"
        b = "3.199 đô la là mức giá gốc của chiếc máy này khi mới lên kệ"
        heard = (spread("Theo số liệu mới nhất thì sau 15 ngày giá của máy đã rớt ba tám phẩy bốn",
                        0.0, 4.0)
                 + spread("ba nghìn đô la là mức giá gốc của chiếc máy này khi mới lên kệ", 4.5, 8.0))
        gaps = batch.sentence_gaps([a, b], heard)
        self.assertEqual(len(gaps), 1)
        self.assertLess(gaps[0][0], 4.0)
        self.assertAlmostEqual(gaps[0][1], 4.5, places=2)

    def test_garbled_reading_is_rejected(self):
        words = spread("một bài hát hoàn toàn khác không liên quan gì", 0.0, 3.0)
        self.assertIsNone(batch.sentence_gaps([S1, S2, S3], words))
        self.assertIsNone(batch.sentence_gaps([S1, "…"], spread(S1, 0, 1)))   # câu không có chữ


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.outs = [self.dir / f"v_{i:02d}.wav" for i in (1, 2, 3)]
        # Whisper lệch ~50-80 ms so với tiếng thật — hàm cắt phải tự dời vào khoảng lặng
        self.words = spread(S1, 0.0, 1.08) + spread(S2, 1.22, 2.55) + spread(S3, 2.75, 3.6)

    def test_cuts_land_in_the_real_silence_and_padding_is_trimmed(self):
        wav = make_wav(self.dir / "b.wav", [("tone", 1.0), ("quiet", 0.3), ("tone", 1.2),
                                           ("quiet", 0.3), ("tone", 0.8), ("quiet", 0.4)])
        self.assertTrue(batch.split_at_sentences(wav, [S1, S2, S3], self.words, self.outs))
        durs = [tts.wav_duration(p) for p in self.outs]
        for got, speech in zip(durs, (1.0, 1.2, 0.8)):
            # đúng phần có tiếng + chút lặng chừa lại, không dính tiếng của câu bên cạnh
            self.assertAlmostEqual(got, speech + batch.KEEP_HEAD + batch.KEEP_TAIL, delta=0.06)
        with wave.open(str(self.outs[1]), "rb") as w:
            head = np.frombuffer(w.readframes(int(0.03 * RATE)), dtype=np.int16)
        self.assertEqual(int(np.abs(head).max()), 0)           # mở đầu bằng lặng, không cắt trúng tiếng

    def test_sentences_glued_together_are_not_cut(self):
        wav = make_wav(self.dir / "b.wav", [("tone", 3.6)])     # đọc một lèo, không nghỉ
        self.assertFalse(batch.split_at_sentences(wav, [S1, S2, S3], self.words, self.outs))
        self.assertFalse(any(p.exists() for p in self.outs))

    def test_implausible_sentence_length_is_not_cut(self):
        wav = make_wav(self.dir / "b.wav", [("tone", 0.3), ("quiet", 0.3), ("tone", 3.0)])
        words = spread(S1, 0.0, 0.3) + spread("ừ", 0.6, 0.7) + spread("à " * 30, 0.7, 3.6)
        long, short = "à " * 30, "ừ"
        self.assertFalse(batch.split_at_sentences(wav, [S1, long, short],
                                                  spread(S1, 0.0, 0.3) + spread(long, 0.6, 3.5)
                                                  + spread(short, 3.5, 3.6), self.outs))
        self.assertFalse(any(p.exists() for p in self.outs))


class SynthBatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.outs = [self.dir / f"v_{i:02d}.wav" for i in (1, 2, 3)]
        self.sent = []

    def synth(self, plan):
        def fake(text, out, timeout=120):
            self.sent.append(text)
            make_wav(out, plan)
        return fake

    def test_one_call_for_the_whole_script(self):
        words = spread(S1, 0.0, 1.0) + spread(S2, 1.3, 2.5) + spread(S3, 2.8, 3.6)
        plan = [("tone", 1.0), ("quiet", 0.3), ("tone", 1.2), ("quiet", 0.3), ("tone", 0.8)]
        got = batch.synth_batch([S1, S2, S3], self.outs, self.dir,
                                synth=self.synth(plan), transcribe=lambda p: words)
        self.assertEqual(got, 3)
        self.assertEqual(self.sent, [f"{S1}\n\n{S2}\n\n{S3}"])   # đúng MỘT lần gọi TTS
        self.assertTrue(all(p.exists() for p in self.outs))

    def test_untrustworthy_cut_leaves_nothing_so_caller_reads_one_by_one(self):
        plan = [("tone", 3.6)]
        got = batch.synth_batch([S1, S2, S3], self.outs, self.dir, synth=self.synth(plan),
                                transcribe=lambda p: spread("nghe ra chuyện khác hẳn", 0, 3))
        self.assertEqual(got, 0)
        self.assertFalse(any(p.exists() for p in self.outs))

    def test_whisper_crash_is_contained_but_quota_error_propagates(self):
        def boom(p):
            raise OSError("thiếu model")
        plan = [("tone", 1.0)]
        self.assertEqual(batch.synth_batch([S1, S2], self.outs[:2], self.dir,
                                           synth=self.synth(plan), transcribe=boom), 0)

        def no_quota(text, out, timeout=120):
            raise tts.QuotaExhausted("hết quota")
        with self.assertRaises(tts.QuotaExhausted):
            batch.synth_batch([S1, S2], self.outs[:2], self.dir, synth=no_quota,
                              transcribe=lambda p: [])

    def test_batching_can_be_switched_off(self):
        with mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "0"}):
            self.assertEqual(batch.batch_words(), 0)
        with mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "nhiều"}):
            self.assertEqual(batch.batch_words(), 300)


if __name__ == "__main__":
    unittest.main()
