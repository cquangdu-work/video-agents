"""Lắp ráp bản PHÁT HÀNH: spec (có lời đọc) -> giọng + hình + phụ đề + chuẩn âm lượng.

    python -m src.assemble 6                 # từ data/specs/script_6.yaml

Luồng:
1. TTS (Gemini): đọc CẢ BÀI một lần gọi rồi cắt theo câu (src/audio/batch.py); câu
   nào cắt không chắc thì đọc lẻ. Các cảnh liền nhau ghi cùng một câu lời = một nhóm:
   dùng chung một đoạn giọng, thời lượng chia cho các cảnh trong nhóm (hình khớp lời)
2. Render từng cảnh Manim theo thời lượng đó, nối thành video câm
3. Ghép audio các cảnh (đệm im lặng cho khớp từng cảnh video)
4. Whisper lấy mốc từng từ -> phụ đề .ass kiểu cụm 3 từ
5. ffmpeg: đốt phụ đề + trộn tiếng + nhạc nền (tự hạ khi có giọng) + loudnorm -16 LUFS
   -> output/final_<id>.mp4

Engine "web" (Remotion, mặc định từ 16/11/2026 — config/channel.yaml render.engine) đổi thứ tự:
tiếng (3) và mốc từng từ (4) làm TRƯỚC, rồi src/render/web.py dịch spec thành props và Remotion
vẽ cả video một lượt (phụ đề lớn vẽ luôn trong hình), cuối cùng chỉ trộn tiếng. Cảnh chưa có bản
Remotion (bản đồ, cuộc đua) vẫn dựng bằng Manim rồi lồng vào. Remotion lỗi -> tự lùi về Manim.
"""
import argparse
import hashlib
import json
import logging
import math
import shutil
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
    """Chia thời lượng một đoạn giọng cho từng cảnh theo trọng số."""
    weights = [max(float(w or 0), 0.1) for w in weights]
    return [total * w / sum(weights) for w in weights]


def audio_runs(groups: list, joined: dict) -> list:
    """Gộp tiếp các nhóm có giọng nằm chung một file (câu đọc liền hơi — xem
    src/audio/batch.py) -> [[chỉ số cảnh, ...], ...], mỗi phần tử ứng với MỘT file giọng.
    joined: {cảnh đầu của nhóm sau: cảnh đầu của nhóm chứa giọng}."""
    runs = []
    for g in groups:
        if runs and joined.get(g[0]) == runs[-1][0]:
            runs[-1].extend(g)
        else:
            runs.append(list(g))
    return runs


def scene_weights(spec: list, run: list) -> list:
    """Mỗi cảnh trong một run chiếm bao nhiêu phần đoạn giọng: theo độ dài câu của nó.
    Câu trải trên nhiều cảnh (cùng 'voice') thì chia đều phần của câu cho các cảnh đó."""
    voices = [_voice(spec[i]) for i in run]
    return [len(v) / voices.count(v) for v in voices]


MAX_TEMPO = 1.12         # đọc nhanh lên tối đa 12%: 3,2 -> 3,6 từ/giây, vẫn chậm hơn video #45
                         # đọc tự nhiên 3,79 từ/giây — tai người nghe không thấy khác


def run_seconds(voice_seconds: float, n_scenes: int, tempo: float = 1.0) -> float:
    """Thời lượng hình của một run (nhóm cảnh dùng chung một file giọng): dài đúng bằng giọng
    (đã đọc nhanh theo tempo) + khoảng lặng cuối câu, nhưng mỗi cảnh không ngắn hơn MIN_SCENE."""
    return max(voice_seconds / tempo + VOICE_TAIL, MIN_SCENE * n_scenes)


def fit_tempo(voice_seconds: list, scene_counts: list, fixed: float, target: float,
              max_tempo: float = MAX_TEMPO) -> float:
    """Hệ số đọc nhanh NHỎ NHẤT (>= 1) để cả video vừa `target` giây; không cần thì 1.0.

    Vì sao (ca thật 18/11/2026): tốc độ giọng TTS mỗi hôm một khác — 3,20 từ/giây ở #37 và #38,
    3,79 ở #45 — nên kịch bản đúng ngân sách từ vẫn ra video 95,3 giây, rớt Kiểm định (trần 95)
    SAU KHI đã tốn quota giọng đọc và 7 phút dựng. `fixed`: các cảnh không lời (intro).
    Cần nhanh hơn max_tempo mới vừa thì dừng ở max_tempo (để Kiểm định quyết)."""
    total = lambda t: fixed + sum(run_seconds(d, n, t) for d, n in zip(voice_seconds, scene_counts))
    if total(1.0) <= target:
        return 1.0
    if total(max_tempo) > target:
        return max_tempo
    lo, hi = 1.0, max_tempo
    for _ in range(40):                       # chia đôi: tổng thời lượng giảm dần theo tempo
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if total(mid) <= target else (mid, hi)
    return math.ceil(hi * 1000) / 1000        # làm tròn LÊN để chắc chắn vừa


def speed_up(src: Path, dst: Path, tempo: float) -> Path:
    """Đọc nhanh lên `tempo` lần mà giữ nguyên cao độ giọng (bộ lọc atempo của ffmpeg)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={tempo:.3f}",
                    "-ar", "24000", "-ac", "1", str(dst)], check=True)
    return dst


def drop_stale_voice(audio_dir: Path, voices: list) -> bool:
    """Giọng đã đọc được giữ lại theo SỐ THỨ TỰ cảnh. Nếu spec được sinh lại (lời hoặc
    thứ tự cảnh đổi) mà giọng cũ còn đó thì hình một đằng, tiếng một nẻo. Hàm này ghi
    "dấu vân tay" của toàn bộ lời đọc vào voice.sha1; lần sau thấy khác thì xoá giọng cũ.
    Trả về True nếu đã xoá. Thư mục giọng đời cũ (chưa có dấu) được giữ nguyên."""
    mark = audio_dir / "voice.sha1"
    now = hashlib.sha1("\n".join(voices).encode("utf-8")).hexdigest()
    try:
        old = mark.read_text(encoding="utf-8").strip()
    except OSError:
        old = None
    stale = old is not None and old != now
    if stale:
        log.warning("Spec đã đổi so với giọng đọc đang lưu — xoá giọng cũ, đọc lại từ đầu")
        for f in audio_dir.iterdir():
            if f.suffix in (".wav", ".json") or f.name == "alist.txt":
                f.unlink()
    mark.write_text(now, encoding="utf-8")
    return stale


def load_joined(path: Path, audio_dir: Path) -> dict:
    """Đọc joined.json, bỏ mục nào mà file giọng chứa nó không còn."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {int(k): int(v) for k, v in raw.items()
            if (audio_dir / f"v_{int(v):02d}.wav").exists()}


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def build_audio(runs: list, wavs: dict, durations: list, audio_dir: Path) -> Path:
    """Ghép giọng: mỗi run (nhóm cảnh dùng chung một file giọng) một đoạn, đệm im lặng cho dài
    ĐÚNG bằng tổng thời lượng hình của các cảnh trong run. `durations`: thời lượng từng cảnh —
    engine Manim đo từ file đã render, engine Remotion lấy thẳng từ spec (hình vẽ theo spec)."""
    parts = []
    for g in runs:
        vdur = sum(durations[i] for i in g)
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
    return full_wav


def narration_words(full_wav: Path, spec: list, todo: list, audio_dir: Path) -> list:
    """Mốc thời gian từng từ: chữ của KỊCH BẢN (đúng chính tả, đúng cách viết số), mốc giờ của
    Whisper -> [(từ, bắt đầu, kết thúc)]. Ghi kèm meta.json cho agent Kiểm định."""
    from .audio.batch import tokens
    from .audio.subtitles import script_words_timed, transcribe_words
    words = transcribe_words(full_wav)
    script_words = " ".join(_voice(spec[g[0]]) for g in todo).split()
    # Hai con số cho agent Kiểm định (qc.check_narration): đưa TTS đọc bao nhiêu từ,
    # Whisper nghe lại được bao nhiêu -> lệch nhiều là giọng đọc lặp/cụt
    (audio_dir / "meta.json").write_text(json.dumps({
        "spoken_words": sum(len(tokens(_voice(spec[g[0]]))) for g in todo),
        "heard_words": sum(len(tokens(w[0])) for w in words)}), encoding="utf-8")
    return script_words_timed(script_words, words)


def mix_web(raw: Path, full_wav: Path, track, final: Path) -> Path:
    """Video Remotion (hình + phụ đề + track âm hiệu ứng) + giọng (+ nhạc) -> bản phát hành.
    Hình giữ nguyên (copy), chỉ trộn tiếng và chuẩn âm lượng -16 LUFS như engine cũ."""
    from .audio import music
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-i", str(full_wav)]
    if track:
        cmd += ["-stream_loop", "-1", "-i", str(track["path"]), "-filter_complex",
                music.mix_filter(ffprobe_duration(raw), track["gain_db"], sfx=True)]
    else:
        same = music.SAME_FMT
        cmd += ["-filter_complex",
                f"[1:a]{same}[v];[0:a]{same}[fx];[v][fx]amix=inputs=2:duration=first:dropout_transition=0:"
                f"normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]"]
    cmd += ["-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(final)]
    subprocess.run(cmd, check=True)
    return final


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id", type=int)
    ap.add_argument("--engine", choices=["web", "manim"], default=None,
                    help="engine dựng hình (mặc định theo config/channel.yaml render.engine)")
    ap.add_argument("--out", type=Path, default=None,
                    help="CHẠY THỬ: ghi video ra file này (không đè output/final_<id>.mp4) và "
                         "không ghi nhật ký kho chất liệu")
    args = ap.parse_args()

    spec_path = ROOT / "data" / "specs" / f"script_{args.script_id}.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    from .main import load_config
    cfg = load_config()
    # Intro do produce quyết lúc sinh spec (render.intro). KHÔNG bỏ intro của spec cũ ở đây: giọng
    # trong bộ đệm gắn với SỐ THỨ TỰ cảnh (v_01.wav...) -> bỏ một cảnh là câu sau dùng nhầm giọng câu trước.

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

    drop_stale_voice(audio_dir, [_voice(spec[g[0]]) for g in todo])

    # joined: {cảnh đầu của câu B: cảnh đầu của câu A} = câu B được đọc liền hơi với câu A
    # nên giọng của B nằm trong file của A. Lưu ra đĩa để lần chạy lại còn biết.
    joined_path = audio_dir / "joined.json"
    joined = load_joined(joined_path, audio_dir)
    covered = lambda g: wav_of(g).exists() or g[0] in joined

    # Đọc CẢ BÀI bằng một lần gọi rồi cắt theo câu (src/audio/batch.py) — tiết kiệm
    # quota gấp ~10 lần. Câu nào cắt không chắc ăn thì vòng lặp bên dưới đọc lẻ.
    missing = [g for g in todo if not covered(g)]
    if len(missing) >= 2 and batch_words() > 0:
        # hai câu chỉ được chung một đoạn giọng nếu cảnh của chúng nằm sát nhau
        adjacent = [a[-1] + 1 == b[0] for a, b in zip(missing, missing[1:])]
        try:
            owner = synth_batch([_voice(spec[g[0]]) for g in missing],
                                [wav_of(g) for g in missing], audio_dir, adjacent)
        except QuotaExhausted as exc:
            pause_for_quota(exc, len(todo) - len(missing))
        for i, o in enumerate(owner):
            if o is not None and o != i:
                joined[missing[i][0]] = missing[o][0]
        joined_path.write_text(json.dumps(joined), encoding="utf-8")
        log.info("Đọc gộp: có giọng cho %d/%d câu còn thiếu",
                 sum(o is not None for o in owner), len(missing))

    runs = audio_runs(groups, joined)              # mỗi run = các cảnh dùng chung MỘT file giọng
    voiced = [r for r in runs if _voice(spec[r[0]])]
    wavs = {}                                      # cảnh đầu run -> file giọng của cả run
    for n, r in enumerate(voiced, 1):
        voice = _voice(spec[r[0]])
        wav = wav_of(r)
        if not wav.exists():                      # chạy lại không tốn TTS lần nữa
            log.info("TTS câu %d/%d (cảnh %d-%d): %s...", n, len(voiced), r[0] + 1, r[-1] + 1,
                     voice[:40])
            try:
                synth(voice, wav)
            except QuotaExhausted as exc:
                pause_for_quota(exc, sum(1 for g in todo if covered(g)))
            if n < len(voiced):
                time.sleep(30)                    # free tier TTS giới hạn số lần/phút
        wavs[r[0]] = wav

    # ---- 1b. Vừa khung thời lượng (channel.video_seconds_max): giọng hôm nay chậm thì đọc nhanh
    # lên chút ít (fit_tempo). File giọng gốc giữ nguyên trong cache; bản đọc nhanh là fit_XX.wav
    fixed =sum(float(spec[i].get("seconds") or 0) for r in runs if not _voice(spec[r[0]]) for i in r)
    raw_secs = [wav_duration(wavs[r[0]]) for r in voiced]
    tempo = fit_tempo(raw_secs, [len(r) for r in voiced], fixed,
                      float(cfg["channel"].get("video_seconds_max", 90)))
    if tempo > 1.0:
        planned = fixed + sum(run_seconds(d, len(r)) for d, r in zip(raw_secs, voiced))
        log.info("Video sẽ dài %.1fs — đọc nhanh lên %.3f lần để vừa %ss", planned, tempo,
                 cfg["channel"].get("video_seconds_max", 90))
        for r in voiced:
            wavs[r[0]] = speed_up(wavs[r[0]], audio_dir / f"fit_{r[0]:02d}.wav", tempo)

    for n, r in enumerate(voiced, 1):
        # KHÔNG cắt lời: run dài đúng bằng giọng (trước đây kẹp 9s -> câu dài bị cụt)
        total = run_seconds(wav_duration(wavs[r[0]]), len(r))
        for i, secs in zip(r, share_seconds(total, scene_weights(spec, r))):
            spec[i]["seconds"] = round(secs, 3)
        if total / len(r) > LONG_SCENE:
            log.warning("Câu %d dài %.1fs mà chỉ có %d cảnh hình — cảnh đứng yên hơi lâu",
                        n, total, len(r))

    # Lưu spec với thời lượng THẬT theo giọng — agent Kiểm định đối chiếu mốc này
    final_spec_path = spec_path.parent / f"script_{args.script_id}_final.yaml"
    final_spec_path.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")

    from .audio import music
    rcfg = cfg.get("render") or {}
    engine = args.engine or rcfg.get("engine", "manim")
    OUTPUT.mkdir(exist_ok=True)
    final = args.out or OUTPUT / f"final_{args.script_id}.mp4"
    con = assets_db.init_assets()
    narration = " ".join(_voice(spec[g[0]]) for g in todo)
    track = music.select(con, narration, f"script_{args.script_id}", cfg)
    if track:
        log.info("Nhạc nền: %s (nhóm %s, lời đọc nghiêng về %s, chỉnh %+.1f dB)", track["name"],
                 track["mood"], track["mood_wanted"], track["gain_db"])

    used = None
    if engine == "web":
        # ---- Engine mới (Remotion): tiếng trước, hình sau — phụ đề lớn và hình "bắt" đúng từ đang
        # đọc cần mốc thời gian của từng từ TRƯỚC khi vẽ. Lỗi gì cũng lùi về Manim: thà hình cũ
        # còn hơn sáng ra không có video.
        try:
            durations = [float(sc["seconds"]) for sc in spec]
            full_wav = build_audio(runs, wavs, durations, audio_dir)
            timed = narration_words(full_wav, spec, todo, audio_dir)
            from .render import web
            props = web.build_story(spec, timed, args.script_id,
                                    render_clip=lambda sc, i: render_scene(sc, i))
            final_spec_path.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
            raw = web.render(props, RENDER / f"web_{args.script_id}.mp4",
                             concurrency=int(rcfg.get("web_concurrency", 3)))
            mix_web(raw, full_wav, track, final)
            shutil.rmtree(web.CLIPS / str(args.script_id), ignore_errors=True)
            used = ["remotion_engine", "be_vietnam_pro", "lucide_icons", "flag_icons", "sfx_synth"]
            if props.get("world"):
                used.append("chart_world")
        except Exception as exc:
            log.error("Engine Remotion lỗi (%s: %s) — lùi về Manim", type(exc).__name__, exc)
            engine = "manim"

    if engine != "web":
        # ---- 2. Render hình theo thời lượng giọng
        files = []
        for i, sc in enumerate(spec):
            log.info("Render cảnh %d/%d: %s (%.1fs)", i + 1, len(spec), sc["template"], sc["seconds"])
            files.append(render_scene(sc, i))
        silent = concat(files, RENDER / f"silent_{args.script_id}.mp4")

        # ---- 3. Ghép audio: mỗi run một đoạn, dài đúng bằng tổng các cảnh video của run
        full_wav = build_audio(runs, wavs, [ffprobe_duration(f) for f in files], audio_dir)

        # ---- 4. Phụ đề từng từ
        from .render.base import brand
        from .audio.subtitles import build_ass
        ass = build_ass(narration_words(full_wav, spec, todo, audio_dir), RENDER / "subs.ass", brand())

        # ---- 5. Đốt phụ đề + trộn tiếng (+ nhạc nền nếu kho có nhạc) + chuẩn âm lượng phát hành
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(full_wav)]
        if track:
            # nhạc lặp lại nếu ngắn hơn video; [0:v] đốt phụ đề, [aout] = giọng + nhạc đã trộn
            cmd += ["-stream_loop", "-1", "-i", str(track["path"]),
                    "-filter_complex", f"[0:v]ass={ass.name}[vout];"
                    + music.mix_filter(ffprobe_duration(silent), track["gain_db"]),
                    "-map", "[vout]", "-map", "[aout]"]
        else:
            cmd += ["-vf", f"ass={ass.name}", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)]
        subprocess.run(cmd, check=True, cwd=RENDER)   # cwd=RENDER: né lỗi escape đường dẫn Windows trong filter ass=

    if args.out:
        # chạy thử: không tính là đã dùng chất liệu, KHÔNG ghi bài nhạc vào meta.json (mô tả video
        # thật ghi công theo file này — bản thử có thể chọn bài khác; ca thật 16/11 với #30, #18)
        log.info("BẢN CHẠY THỬ: %s (%.1fs, engine %s)", final, ffprobe_duration(final), engine)
        print(final)
        return
    meta_path = audio_dir / "meta.json"            # ghi bài nhạc đã dùng (agent Phân tích có thể đối chiếu)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["music"] = track["name"] if track else None
    meta["music_credit"] = track["credit"] if track else None   # mô tả video ghi công bài nhạc
    meta["engine"] = engine
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if track:
        assets_db.record_use(con, track["name"], final.name)
    for name in used or []:
        assets_db.record_use(con, name, final.name)
    for sc in spec:
        assets_db.record_use(con, sc["template"], final.name)
        if sc["template"] == "map":                # dữ liệu ranh giới (Natural Earth) cũng là chất liệu
            region = (sc.get("params") or {}).get("region") or "asia"
            assets_db.record_use(con, f"{region}_map", final.name)
            if region == "world":                  # ô phóng to Biển Đông vẽ từ bản đồ châu Á
                assets_db.record_use(con, "asia_map", final.name)
    log.info("BẢN PHÁT HÀNH: %s (%.1fs)", final, ffprobe_duration(final))
    print(final)


if __name__ == "__main__":
    main()
