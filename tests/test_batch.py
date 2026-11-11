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
PAD = batch.KEEP_HEAD + batch.KEEP_TAIL


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


class SubtitleChunkTest(unittest.TestCase):
    def test_chunks_never_straddle_two_sentences(self):
        from src.audio.subtitles import chunk_words
        # Ca thật (video #4): cụm "phòng nữa. Công" hiện chữ của câu sau khi còn đọc câu trước
        words = (spread("Đừng vội kết nối AI với công việc văn phòng nữa!", 0.0, 2.9)
                 + spread("Công nghệ AI đang giúp doanh nghiệp.", 3.0, 5.0))
        texts = [" ".join(w[0] for w in c) for c in chunk_words(words)]
        self.assertEqual(texts, ["Đừng vội kết", "nối AI với", "công việc văn", "phòng nữa!",
                                 "Công nghệ AI", "đang giúp doanh", "nghiệp."])

    def test_a_long_pause_also_ends_the_chunk(self):
        from src.audio.subtitles import chunk_words
        words = [("một", 0.0, 0.2), ("hai", 0.25, 0.4), ("ba", 1.2, 1.4), ("bốn", 1.45, 1.6)]
        self.assertEqual([[w[0] for w in c] for c in chunk_words(words)],
                         [["một", "hai"], ["ba", "bốn"]])
        self.assertEqual(chunk_words([]), [])


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.outs = [self.dir / f"v_{i:02d}.wav" for i in (1, 2, 3)]
        self.texts = [S1, S2, S3]
        # Whisper lệch ~50-80 ms so với tiếng thật — hàm cắt phải tự dời vào khoảng lặng
        self.words = spread(S1, 0.0, 1.08) + spread(S2, 1.22, 2.55) + spread(S3, 2.75, 3.6)

    def split(self, plan, can_join=None):
        wav = make_wav(self.dir / "b.wav", plan)
        return batch.split_at_sentences(wav, self.texts, self.words, self.outs, can_join)

    def test_cuts_land_in_the_real_silence_and_padding_is_trimmed(self):
        owner = self.split([("tone", 1.0), ("quiet", 0.3), ("tone", 1.2), ("quiet", 0.3),
                            ("tone", 0.8), ("quiet", 0.4)])
        self.assertEqual(owner, [0, 1, 2])
        for p, speech in zip(self.outs, (1.0, 1.2, 0.8)):
            # đúng phần có tiếng + chút lặng chừa lại, không dính tiếng của câu bên cạnh
            self.assertAlmostEqual(tts.wav_duration(p), speech + PAD, delta=0.06)
        with wave.open(str(self.outs[1]), "rb") as w:
            head = np.frombuffer(w.readframes(int(0.03 * RATE)), dtype=np.int16)
        self.assertEqual(int(np.abs(head).max()), 0)           # mở đầu bằng lặng, không cắt trúng tiếng

    def test_sentences_read_in_one_breath_share_one_file(self):
        # Ca thật (kịch bản #4): model đọc "...từ tháng sáu. Kéo dài liên tục..." liền một hơi
        plan = [("tone", 1.0), ("quiet", 0.3), ("tone", 2.3)]   # câu 2 và 3 dính nhau
        self.assertEqual(self.split(plan, can_join=[True, True]), [0, 1, 1])
        self.assertTrue(self.outs[0].exists() and self.outs[1].exists())
        self.assertFalse(self.outs[2].exists())                  # câu 3 nằm trong file câu 2
        # hết file là hết tiếng nên phía sau không còn khoảng lặng nào để chừa lại
        self.assertAlmostEqual(tts.wav_duration(self.outs[1]), 2.3 + batch.KEEP_HEAD, delta=0.06)

    def test_glued_sentences_that_may_not_share_are_left_for_single_reading(self):
        plan = [("tone", 1.0), ("quiet", 0.3), ("tone", 2.3)]
        self.assertEqual(self.split(plan), [0, None, None])      # câu 1 vẫn dùng được
        self.assertTrue(self.outs[0].exists())
        self.assertFalse(self.outs[1].exists() or self.outs[2].exists())

    def test_a_tiny_gap_between_words_is_not_a_sentence_break(self):
        # lặng 60 ms là nghỉ giữa hai từ; cắt ở đó dễ phạm vào chữ
        plan = [("tone", 1.0), ("quiet", 0.3), ("tone", 1.2), ("quiet", 0.06), ("tone", 1.04)]
        self.assertEqual(self.split(plan), [0, None, None])

    def test_implausible_length_is_not_written(self):
        self.texts = ["à", "một hai ba bốn năm sáu bảy tám chín mười", "ừ"]
        self.words = (spread("à", 0.0, 2.0) + spread(self.texts[1], 2.3, 3.3) + spread("ừ", 3.6, 3.9))
        owner = self.split([("tone", 2.0), ("quiet", 0.3), ("tone", 1.0), ("quiet", 0.3), ("tone", 0.3)])
        self.assertIsNone(owner[0])                              # 1 chữ mà dài 2 giây
        self.assertFalse(self.outs[0].exists())


class SynthBatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.outs = [self.dir / f"v_{i:02d}.wav" for i in (1, 2, 3)]
        self.sent = []
        self.words = spread(S1, 0.0, 1.0) + spread(S2, 1.3, 2.5) + spread(S3, 2.8, 3.6)

    def synth(self, plan):
        def fake(text, out, timeout=120):
            self.sent.append(text)
            make_wav(out, plan)
        return fake

    def test_one_call_for_the_whole_script(self):
        plan = [("tone", 1.0), ("quiet", 0.3), ("tone", 1.2), ("quiet", 0.3), ("tone", 0.8)]
        owner = batch.synth_batch([S1, S2, S3], self.outs, self.dir,
                                  synth=self.synth(plan), transcribe=lambda p: self.words)
        self.assertEqual(owner, [0, 1, 2])
        self.assertEqual(self.sent, [f"{S1}\n\n{S2}\n\n{S3}"])   # đúng MỘT lần gọi TTS
        self.assertTrue(all(p.exists() for p in self.outs))

    def test_owner_indexes_are_global_across_chunks(self):
        # mỗi mẻ tối đa 12 từ -> mẻ 1 = câu 0,1; mẻ 2 = câu 2,3 (đọc liền hơi)
        texts = [S1, S2, S3, "Cảm ơn đã xem."]
        outs = self.outs + [self.dir / "v_04.wav"]
        plans = [[("tone", 1.0), ("quiet", 0.3), ("tone", 1.2)], [("tone", 2.0)]]
        heard = [spread(S1, 0.0, 1.0) + spread(S2, 1.3, 2.5),
                 spread(S3, 0.0, 1.0) + spread(texts[3], 1.0, 2.0)]

        def fake(text, out, timeout=120):
            make_wav(out, plans[len(self.sent)])
            self.sent.append(text)
        with mock.patch.dict("os.environ", {"TTS_BATCH_WORDS": "12"}):
            owner = batch.synth_batch(texts, outs, self.dir, can_join=[True, True, True],
                                      synth=fake, transcribe=lambda p: heard[len(self.sent) - 1])
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(owner, [0, 1, 2, 2])                    # câu 3 nằm trong file câu 2

    def test_untrustworthy_cut_leaves_nothing_so_caller_reads_one_by_one(self):
        owner = batch.synth_batch([S1, S2, S3], self.outs, self.dir, synth=self.synth([("tone", 3.6)]),
                                  transcribe=lambda p: spread("nghe ra chuyện khác hẳn", 0, 3))
        self.assertEqual(owner, [None, None, None])
        self.assertFalse(any(p.exists() for p in self.outs))

    def test_whisper_crash_is_contained_but_quota_error_propagates(self):
        def boom(p):
            raise OSError("thiếu model")
        self.assertEqual(batch.synth_batch([S1, S2], self.outs[:2], self.dir,
                                           synth=self.synth([("tone", 1.0)]), transcribe=boom),
                         [None, None])

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
