"""Test nhạc nền: đọc kho, đoán tâm trạng, xoay vòng, và (nếu máy có ffmpeg) trộn thật để đo
xem nhạc có tự nhỏ đi khi có giọng không — đo bằng số, không cần nghe.

    python -m unittest discover -s tests -v
"""
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from src import assets_db, db
from src.audio import music


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for name in ("calm - Rain.mp3", "BRIGHT_Sunny.wav", "serious-Storm.m4a", "Lofi Beat.mp3",
                     "ghi chu.txt", "nature - Birds.mp3"):
            (self.dir / name).write_bytes(b"x")

    def test_mood_comes_from_the_file_name_prefix(self):
        got = {t["name"]: t["mood"] for t in music.scan_library(self.dir)}
        self.assertEqual(got, {"calm - Rain.mp3": "calm", "BRIGHT_Sunny.wav": "bright",
                               "serious-Storm.m4a": "serious", "Lofi Beat.mp3": "calm",
                               "nature - Birds.mp3": "calm"})                # tiền tố lạ -> calm
        self.assertEqual(music.scan_library(self.dir / "khong_co"), [])

    def test_mood_of_the_narration(self):
        self.assertEqual(music.pick_mood("Mỗi năm 540.000 người tử vong vì nắng nóng, thêm cả bão lũ"),
                         "serious")
        self.assertEqual(music.pick_mood("Việt Nam vượt Philippines, tăng gấp 21 lần, dẫn đầu khu vực"),
                         "bright")
        self.assertEqual(music.pick_mood("Điện tiêu thụ bình quân đầu người của hai nước"), "calm")
        self.assertEqual(music.pick_mood("Tuổi thọ tăng, ít người chết trẻ hơn"), "calm")   # 1 dấu hiệu chưa đủ

    def test_least_used_track_of_the_right_mood_wins(self):
        tracks = music.scan_library(self.dir)
        pick = music.choose_track(tracks, "calm", {"calm - Rain.mp3": 2, "Lofi Beat.mp3": 0,
                                                    "nature - Birds.mp3": 1}, salt="v1")
        self.assertEqual(pick["name"], "Lofi Beat.mp3")
        self.assertEqual(music.choose_track(tracks, "bright", {}, "v1")["name"], "BRIGHT_Sunny.wav")
        only_calm = [t for t in tracks if t["mood"] == "calm"]
        self.assertEqual(music.choose_track(only_calm, "serious", {}, "v1")["mood"], "calm")  # lùi về calm
        self.assertIsNone(music.choose_track([], "calm", {}, "v1"))
        same = {music.choose_track(only_calm, "calm", {}, "video-7")["name"] for _ in range(3)}
        self.assertEqual(len(same), 1)                                   # chạy lại cùng video: cùng bài

    def test_select_registers_licence_and_respects_the_switch(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(db, "DB_PATH", Path(d) / "t.db"):
            con = assets_db.init_assets()
            cfg = {"music": {"enabled": True, "license": "Giấy phép thử", "target_lufs": -32}}
            t = music.select(con, "dẫn đầu, kỷ lục mới", "script_9", cfg, self.dir,
                             measure=lambda p: -12.0)
            self.assertEqual((t["mood_wanted"], t["name"]), ("bright", "BRIGHT_Sunny.wav"))
            self.assertEqual((t["gain_db"], t["credit"]), (-20.0, "Sunny"))
            row = con.execute("SELECT license, tags FROM assets WHERE name=?", (t["name"],)).fetchone()
            self.assertEqual(tuple(row), ("Giấy phép thử", "bright"))
            self.assertIsNone(music.select(con, "x", "s", {"music": {"enabled": False}}, self.dir))
            self.assertIsNone(music.select(con, "x", "s", cfg, Path(d) / "trong"))
            con.close()


class LoudnessAndCreditTest(unittest.TestCase):
    def test_each_track_is_brought_to_the_same_loudness(self):
        # Đo thật 12/11: kho của Du chênh 17 dB (-9,6 đến -26,6 LUFS)
        self.assertEqual(music.gain_for(-9.6, -32, -20), -22.4)
        self.assertEqual(music.gain_for(-26.6, -32, -20), -5.4)
        self.assertEqual(music.gain_for(-35.0, -32, -20), 0.0)          # không bao giờ khuếch đại
        self.assertEqual(music.gain_for(None, -32, -20), -20)          # đo hỏng -> mức mặc định

    def test_loudness_is_measured_once_and_remeasured_when_the_file_changes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "calm - A.mp3"
            f.write_bytes(b"x")
            calls = []
            measure = lambda p: calls.append(p.name) or -14.0
            self.assertEqual(music.track_lufs(f, measure), -14.0)
            self.assertEqual(music.track_lufs(f, measure), -14.0)
            self.assertEqual(len(calls), 1)                             # lần 2 lấy từ bộ đệm
            f.write_bytes(b"xyz")                                       # thay file -> đo lại
            music.track_lufs(f, measure)
            self.assertEqual(len(calls), 2)
            broken = Path(d) / "calm - Hong.mp3"
            broken.write_bytes(b"?")

            def fail(p):
                raise ValueError("file hỏng")
            with self.assertLogs("src.audio.music", level="WARNING"):
                self.assertIsNone(music.track_lufs(broken, fail))     # đo hỏng -> None, không sập

    def test_credit_line_comes_from_the_file_name(self):
        self.assertEqual(music.credit("bright-New Land - ALBIS.mp3"), "New Land — ALBIS")
        self.assertEqual(music.credit("serious-Dance of the U-boat - Aakash Gandhi.mp3"),
                         "Dance of the U-boat — Aakash Gandhi")
        self.assertEqual(music.credit("Lofi Beat.mp3"), "Lofi Beat")

    def test_description_credits_the_music(self):
        from src.publish import metadata
        cfg = {"publish": {"disclosure": "AI."}, "music": {"library": "YouTube Audio Library"}}
        idea = {"source_name": "World Bank", "source_url": "https://data.worldbank.org"}
        m = metadata.finalize({"title": "T", "description": "Mô tả"}, idea, [], cfg, "New Land — ALBIS")
        self.assertIn("Nhạc nền: New Land — ALBIS (YouTube Audio Library)", m["description"])
        self.assertNotIn("Nhạc nền", metadata.finalize({"title": "T"}, idea, [], cfg)["description"])


def write_wav(path: Path, samples, rate: int):
    import numpy as np
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(data.tobytes())


@unittest.skipUnless(shutil.which("ffmpeg"), "máy không có ffmpeg")
class DuckingTest(unittest.TestCase):
    def test_music_drops_while_the_voice_speaks(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rate = 24000
            t = np.arange(int(6 * rate)) / rate
            voice = 0.5 * np.sin(2 * np.pi * 440 * t) * ((t % 2) < 1)      # nói 1 giây, nghỉ 1 giây
            write_wav(d / "voice.wav", voice, rate)
            tm = np.arange(int(4 * 44100)) / 44100                          # nhạc 4 giây < video 6 giây: phải lặp
            write_wav(d / "music.wav", 0.5 * np.sin(2 * np.pi * 220 * tm), 44100)
            out = d / "mix.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error",
                            "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=6",
                            "-i", str(d / "voice.wav"), "-stream_loop", "-1", "-i", str(d / "music.wav"),
                            "-filter_complex", music.mix_filter(6.0, gain_db=-12),   # như thật: nhạc -27, giọng -15 LUFS
                            "-map", "[aout]", str(out)], check=True)
            with wave.open(str(out), "rb") as w:
                sr, n = w.getframerate(), w.getnframes()
                x = np.frombuffer(w.readframes(n), dtype="<i2").astype(float)
                if w.getnchannels() > 1:
                    x = x.reshape(-1, w.getnchannels()).mean(axis=1)
            self.assertAlmostEqual(n / sr, 6.0, delta=0.15)                 # dài đúng bằng giọng/video

            def level(freq, a, b):                                          # biên độ một tần số trong [a, b] giây
                seg = x[int(a * sr):int(b * sr)]
                tt = np.arange(len(seg)) / sr
                return abs(np.dot(seg, np.exp(-2j * np.pi * freq * tt))) / len(seg)
            music_while_talking = level(220, 2.2, 2.8)
            music_in_pauses = (level(220, 1.5, 1.9) + level(220, 3.5, 3.9)) / 2
            self.assertGreater(level(440, 2.2, 2.8), 10 * music_while_talking)   # giọng át hẳn nhạc
            self.assertLess(music_while_talking, 0.5 * music_in_pauses)          # nhạc tự nhỏ khi có giọng
            self.assertGreater(music_in_pauses, 0)                               # nghỉ thì nhạc lên lại


if __name__ == "__main__":
    unittest.main()
