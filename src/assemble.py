"""Lắp ráp bản PHÁT HÀNH: spec (có lời đọc) -> giọng + hình + phụ đề + chuẩn âm lượng.

    python -m src.assemble 6                 # từ data/specs/script_6.yaml

Luồng:
1. TTS (Gemini): đọc CẢ BÀI một lần gọi rồi cắt theo câu (src/audio/batch.py); câu
   nào cắt không chắc thì đọc lẻ. Các cảnh liền nhau ghi cùng một câu lời = một nhóm:
   dùng chung một đoạn giọng, thời lượng chia cho các cảnh trong nhóm (hình khớp lời)
2. Render từng cảnh Manim theo thời lượng đó, nối thành video câm
3. Ghép audio các cảnh (đệm im lặng cho khớp từng cảnh video)
4. Whisper lấy mốc từng từ -> phụ đề .ass kiểu cụm 3 từ
5. ffmpeg: đốt phụ đề + trộn tiếng + loudnorm chuẩn -16 LUFS -> output/final_<id>.mp4
   (chỗ cắm nhạc nền để sẵn: thêm input nhạc + sidechaincompress khi Du có nhạc)
"""
import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

log = logging.getLogger("assemble")

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "data" / "render"
OUTPUT = ROOT / "output"

EXIT_RETRY_LATER = 75    # mã thoát "lỗi tạm thời" (hết quota TTS) — src/daily.py đọc mã này
MIN_SCENE = 2.0          # giây — cảnh ngắn hơn thế thì mắt không kịp đọc
LONG_SCENE = 9.0         # giây — cảnh đứng yên lâu hơn thế thì cảnh báo (nhịp chậm)
VOICE_TAIL = 0.35        # giây — khoảng lặng sau mỗi câu cho giọng khỏi dính nhau


def _voice(sc: dict) -> str:
    """Lời đọc của cảnh, đã gọt khoảng trắng thừa (để so trùng không bị lệch vì dấu cách)."""
    return " ".join(str(sc.get("voice") or "").split())


def voice_groups(spec: list) -> list:
    """Gom các cảnh LIỀN NHAU có cùng lời đọc thành nhóm -> [[chỉ số cảnh, ...], ...].

    Một câu lời dài 10-15 giây cần 3-4 cảnh hình (luật đổi cảnh mỗi 2-4 giây), nên
    spec ghi cùng một 'voice' ở các cảnh đó. Câu ấy chỉ được ĐỌC MỘT LẦN và phát
    xuyên suốt cả nhóm. (Trước đây mỗi cảnh tự gọi TTS: câu bị đọc lặp 3 lần và
    tốn gấp 3 quota.) Cảnh không lời (intro) luôn đứng riêng.
    """
    groups = []
    for i, sc in enumerate(spec):
        v = _voice(sc)
        if groups and v and v == _voice(spec[groups[-1][0]]):
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def share_seconds(total: float, weights: list) -> list:
    """Chia thời lượng giọng của một nhóm cho từng cảnh, theo tỷ lệ 'seconds' trong spec."""
    weights = [max(float(w or 0), 0.1) for w in weights]
    return [total * w / sum(weights) for w in weights]


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
    from .audio.batch import batch_words, synth_batch, tokens
    from .audio.tts import QuotaExhausted, synth, wav_duration
    from .render.engine import concat, render_scene

    # ---- 1. TTS từng câu lời (nhóm cảnh), chỉnh thời lượng cảnh theo giọng
    groups = voice_groups(spec)
    todo = [g for g in groups if _voice(spec[g[0]])]
    if not todo:
        sys.exit(f"Spec {spec_path.name} không có trường 'voice' ở cảnh nào (spec đời cũ)."
                 f" Sinh lại: python -m src.produce {args.script_id} --spec-only")
    audio_dir = RENDER / f"audio_{args.script_id}"
    audio_dir.mkdir(parents=True, exist_ok=True)   # cảnh không lời vẫn cần ghi file đệm
    wav_of = lambda g: audio_dir / f"v_{g[0]:02d}.wav"

    def pause_for_quota(exc, have: int):
        # Không phải lỗi của kịch bản: giọng đã đọc xong vẫn nằm trong cache,
        # chạy lại sau khi quota hồi là làm tiếp từ câu còn thiếu.
        log.error("%s", exc)
        log.error("TẠM DỪNG: đã có giọng cho %d/%d câu. Chạy lại lệnh này sau"
                  " (quota ngày của Gemini hồi khoảng 16-17h giờ Hàn).", have, len(todo))
        sys.exit(EXIT_RETRY_LATER)

    # Đọc CẢ BÀI bằng một lần gọi rồi cắt theo câu (src/audio/batch.py) — tiết kiệm
    # quota gấp ~10 lần. Câu nào cắt không chắc ăn thì vòng lặp bên dưới đọc lẻ.
    missing = [g for g in todo if not wav_of(g).exists()]
    if len(missing) >= 2 and batch_words() > 0:
        try:
            got = synth_batch([_voice(spec[g[0]]) for g in missing],
                              [wav_of(g) for g in missing], audio_dir)
            log.info("Đọc gộp: có giọng cho %d/%d câu còn thiếu", got, len(missing))
        except QuotaExhausted as exc:
            pause_for_quota(exc, len(todo) - len(missing))

    wavs = {}                                      # cảnh đầu nhóm -> file giọng của cả nhóm
    for n, g in enumerate(todo, 1):
        voice = _voice(spec[g[0]])
        wav = wav_of(g)
        if not wav.exists():                      # chạy lại không tốn TTS lần nữa
            log.info("TTS câu %d/%d (cảnh %d-%d): %s...", n, len(todo), g[0] + 1, g[-1] + 1,
                     voice[:40])
            try:
                synth(voice, wav)
            except QuotaExhausted as exc:
                pause_for_quota(exc, sum(1 for x in todo if wav_of(x).exists()))
            if n < len(todo):
                time.sleep(30)                    # free tier TTS giới hạn số lần/phút
        wavs[g[0]] = wav
        # KHÔNG cắt lời: nhóm dài đúng bằng giọng (trước đây kẹp 9s -> câu dài bị cụt)
        total = max(wav_duration(wav) + VOICE_TAIL, MIN_SCENE * len(g))
        for i, secs in zip(g, share_seconds(total, [spec[i].get("seconds", 3) for i in g])):
            spec[i]["seconds"] = round(secs, 3)
        if total / len(g) > LONG_SCENE:
            log.warning("Câu %d dài %.1fs mà chỉ có %d cảnh hình — cảnh đứng yên hơi lâu",
                        n, total, len(g))

    # Lưu spec với thời lượng THẬT theo giọng — agent Kiểm định đối chiếu mốc này
    (spec_path.parent / f"script_{args.script_id}_final.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ---- 2. Render hình theo thời lượng giọng
    files = []
    for i, sc in enumerate(spec):
        log.info("Render cảnh %d/%d: %s (%.1fs)", i + 1, len(spec), sc["template"], sc["seconds"])
        files.append(render_scene(sc, i))
    silent = concat(files, RENDER / f"silent_{args.script_id}.mp4")

    # ---- 3. Ghép audio: mỗi nhóm một đoạn, dài đúng bằng tổng các cảnh video của nhóm
    parts = []
    for g in groups:
        vdur = sum(ffprobe_duration(files[i]) for i in g)
        part = audio_dir / f"pad_{g[0]:02d}.wav"
        if g[0] in wavs:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wavs[g[0]]),
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
    # Hai con số cho agent Kiểm định (qc.check_narration): đưa TTS đọc bao nhiêu từ,
    # Whisper nghe lại được bao nhiêu -> lệch nhiều là giọng đọc lặp/cụt
    (audio_dir / "meta.json").write_text(json.dumps({
        "spoken_words": sum(len(tokens(_voice(spec[g[0]]))) for g in todo),
        "heard_words": sum(len(tokens(w[0])) for w in words)}), encoding="utf-8")

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
