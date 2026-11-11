"""Lắp ráp bản PHÁT HÀNH: spec (có lời đọc) -> giọng + hình + phụ đề + chuẩn âm lượng.

    python -m src.assemble 6                 # từ data/specs/script_6.yaml

Luồng:
1. TTS từng cảnh (Gemini) -> thời lượng cảnh = thời lượng giọng (hình khớp lời)
2. Render từng cảnh Manim theo thời lượng đó, nối thành video câm
3. Ghép audio các cảnh (đệm im lặng cho khớp từng cảnh video)
4. Whisper lấy mốc từng từ -> phụ đề .ass kiểu cụm 3 từ
5. ffmpeg: đốt phụ đề + trộn tiếng + loudnorm chuẩn -16 LUFS -> output/final_<id>.mp4
   (chỗ cắm nhạc nền để sẵn: thêm input nhạc + sidechaincompress khi Du có nhạc)
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

log = logging.getLogger("assemble")

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "data" / "render"
OUTPUT = ROOT / "output"


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id", type=int)
    args = ap.parse_args()

    spec_path = ROOT / "data" / "specs" / f"script_{args.script_id}.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    from . import assets_db
    from .audio.tts import synth, wav_duration
    from .render.engine import concat, render_scene

    # ---- 1. TTS từng cảnh, chỉnh thời lượng cảnh theo giọng
    audio_dir = RENDER / f"audio_{args.script_id}"
    for i, sc in enumerate(spec):
        voice = (sc.get("voice") or "").strip()
        if not voice:
            sc["_wav"] = None
            continue
        wav = audio_dir / f"v_{i:02d}.wav"
        if not wav.exists():                      # chạy lại không tốn TTS lần nữa
            log.info("TTS cảnh %d/%d: %s...", i + 1, len(spec), voice[:40])
            synth(voice, wav)
            import time
            time.sleep(30)                        # free tier TTS giới hạn số lần/phút
        sc["_wav"] = wav
        sc["seconds"] = max(2.0, min(wav_duration(wav) + 0.35, 9.0))

    # Lưu spec với thời lượng THẬT theo giọng — agent Kiểm định đối chiếu mốc này
    final_spec = [{k: v for k, v in sc.items() if k != "_wav"} for sc in spec]
    (spec_path.parent / f"script_{args.script_id}_final.yaml").write_text(
        yaml.safe_dump(final_spec, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ---- 2. Render hình theo thời lượng giọng
    files = []
    for i, sc in enumerate(spec):
        log.info("Render cảnh %d/%d: %s (%.1fs)", i + 1, len(spec), sc["template"], sc["seconds"])
        files.append(render_scene(sc, i))
    silent = concat(files, RENDER / f"silent_{args.script_id}.mp4")

    # ---- 3. Ghép audio khớp đúng thời lượng THẬT của từng cảnh video
    parts = []
    for i, (sc, f) in enumerate(zip(spec, files)):
        vdur = ffprobe_duration(f)
        part = audio_dir / f"pad_{i:02d}.wav"
        if sc["_wav"]:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(sc["_wav"]),
                            "-af", "apad", "-t", f"{vdur:.3f}",
                            "-ar", "24000", "-ac", "1", str(part)], check=True)
        else:                                      # cảnh không lời (intro) -> im lặng
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "anullsrc=r=24000:cl=mono", "-t", f"{vdur:.3f}",
                            str(part)], check=True)
        parts.append(part)
    lst = audio_dir / "alist.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    full_wav = audio_dir / "full.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(full_wav)], check=True)

    # ---- 4. Phụ đề từng từ
    from .render.base import brand
    from .audio.subtitles import build_ass, transcribe_words
    words = transcribe_words(full_wav)
    ass = build_ass(words, RENDER / "subs.ass", brand())

    # ---- 5. Đốt phụ đề + trộn tiếng + chuẩn âm lượng phát hành
    OUTPUT.mkdir(exist_ok=True)
    final = OUTPUT / f"final_{args.script_id}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(full_wav),
         "-vf", f"ass={ass.name}", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)],
        check=True, cwd=RENDER)                    # cwd=RENDER: né lỗi escape đường dẫn Windows trong filter ass=

    con = assets_db.init_assets()
    for sc in spec:
        assets_db.record_use(con, sc["template"], final.name)
    log.info("BẢN PHÁT HÀNH: %s (%.1fs)", final, ffprobe_duration(final))
    print(final)


if __name__ == "__main__":
    main()
