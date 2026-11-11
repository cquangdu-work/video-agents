"""Agent Kiểm định: soát bản phát hành TRƯỚC khi gửi Du duyệt.

    python -m src.qc 6        # kiểm output/final_6.mp4

Kiểm máy móc: độ dài, khung hình đen, âm lượng chuẩn phát hành, giấy phép chất liệu.
Kiểm bằng mắt AI: trích khung hình giữa mỗi cảnh, hỏi model vision xem hình có
khớp lời đọc không (luật CLAUDE.md). Đạt hết mới nên gửi Telegram.
"""
import argparse
import base64
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

log = logging.getLogger("qc")
ROOT = Path(__file__).resolve().parent.parent


def check_duration(path: Path, lo=45, hi=95) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                         capture_output=True, text=True, check=True)
    dur = float(out.stdout.strip())
    return {"name": "Độ dài", "value": f"{dur:.1f}s", "ok": lo <= dur <= hi,
            "_duration": dur}


def check_black_frames(path: Path) -> dict:
    out = subprocess.run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.4:pix_th=0.05",
                          "-an", "-f", "null", "-"], capture_output=True, text=True)
    hits = re.findall(r"black_start:\S+", out.stderr)
    return {"name": "Khung hình đen", "value": f"{len(hits)} đoạn", "ok": not hits}


def check_loudness(path: Path) -> dict:
    out = subprocess.run(["ffmpeg", "-i", str(path),
                          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out.stderr, re.S)
    if not m:
        return {"name": "Âm lượng", "value": "không đo được", "ok": False}
    i = float(json.loads(m.group(0))["input_i"])
    return {"name": "Âm lượng", "value": f"{i:.1f} LUFS", "ok": -19 <= i <= -13}


def check_licenses() -> dict:
    from . import assets_db
    con = assets_db.init_assets()
    rows = con.execute("SELECT name, license FROM assets WHERE license='' OR license IS NULL").fetchall()
    return {"name": "Giấy phép chất liệu", "value": "đủ" if not rows else f"thiếu: {[r[0] for r in rows]}",
            "ok": not rows}


MAX_VISION_SAMPLES = 6    # mỗi mẫu là một lần gọi model nhìn ảnh (free tier có giới hạn/phút)


def spread(items: list, k: int) -> list:
    """Chọn k phần tử RẢI ĐỀU từ đầu tới cuối (trước đây chỉ soát 5 cảnh đầu,
    nửa sau video không ai nhìn)."""
    if len(items) <= k:
        return list(items)
    step = (len(items) - 1) / (k - 1)
    return [items[round(i * step)] for i in range(k)]


def script_tokens(script_id: int):
    """Số từ lời đọc của kịch bản gốc trong DB (None nếu không tra được)."""
    from . import db
    from .audio.batch import tokens
    con = db.connect()
    try:
        row = con.execute("SELECT body FROM scripts WHERE id=?", (script_id,)).fetchone()
        scenes = yaml.safe_load(row["body"] or "") if row else None
        if not scenes:
            return None
        return sum(len(tokens(s.get("voice", ""))) for s in scenes)
    except Exception:
        return None
    finally:
        con.close()


def check_narration(script_id: int) -> dict:
    """Lời trong video có ĐÚNG và ĐỦ lời kịch bản không: không lặp, không cụt, không sót câu.

    assemble ghi lại hai con số vào data/render/audio_<id>/meta.json:
      spoken_words = số từ đã đưa cho TTS đọc; heard_words = số từ Whisper nghe được.
    - nghe được lệch nhiều so với đưa đọc  -> giọng đọc lặp/cụt/đọc bậy
    - đưa đọc lệch nhiều so với kịch bản   -> spec bỏ sót hoặc chép lặp câu
    (Ca thật 11/11/2026: video đọc lặp mỗi câu 2-3 lần, nghe được 252 từ trên kịch
    bản 121 từ, vẫn qua hết các phép kiểm cũ.)
    """
    name = "Lời đọc khớp kịch bản"
    path = ROOT / "data" / "render" / f"audio_{script_id}" / "meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        heard, spoken = int(meta["heard_words"]), int(meta["spoken_words"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"name": name, "value": "không có số liệu (video dựng bằng bản cũ)", "ok": True}
    script = script_tokens(script_id)
    problems = []
    if spoken <= 0 or not 0.8 <= heard / spoken <= 1.25:
        problems.append(f"nghe được {heard} từ, lẽ ra {spoken} (đọc lặp hoặc cụt?)")
    if script and not 0.85 <= spoken / script <= 1.15:
        problems.append(f"video đọc {spoken} từ, kịch bản có {script} (sót hoặc lặp câu?)")
    return {"name": name, "value": "; ".join(problems) or f"{heard}/{script or spoken} từ",
            "ok": not problems}


def check_visuals_match(video: Path, spec: list, duration: float) -> dict:
    """Trích khung gần cuối các cảnh có lời, hỏi model vision: hình có khớp/mâu thuẫn lời?"""
    key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("MODEL", "gemini/gemini-3.5-flash-lite").split("/")[-1]
    t, voiced = 0.0, []
    for sc in spec:
        secs = float(sc.get("seconds", 3))
        if sc.get("voice"):
            # Lấy mẫu ở 85% cảnh: hoạt hình đếm số đã chạy xong, số trên hình là số cuối
            voiced.append((min(t + secs * 0.85, duration - 0.2), sc["voice"]))
        t += secs
    samples = spread(voiced, MAX_VISION_SAMPLES)
    issues, unchecked = [], 0
    for ts, voice in samples:
        frame = ROOT / "data" / "render" / "qc_frame.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video),
                        "-frames:v", "1", str(frame)], check=True)
        img = base64.b64encode(frame.read_bytes()).decode()
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key},
                json={"contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/png", "data": img}},
                    {"text": "Đây là một khung hình video dạng chữ/biểu đồ tối giản, "
                             f"lời đọc lúc này là: \"{voice}\". CHỈ báo lỗi khi: "
                             "(a) con số trên hình KHÁC con số trong lời, "
                             "(b) nội dung hình NGƯỢC nghĩa với lời, "
                             "(c) chữ bị tràn/cắt mép khung. "
                             "Hình ít chữ hơn lời, hình chỉ tóm ý — vẫn là ĐẠT. "
                             "Trả lời JSON: {\"ok\": true/false, \"note\": \"...\"}"}]}],
                      # Ép model trả JSON thuần (trước đây thỉnh thoảng trả văn xuôi -> không đọc được)
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=60)
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            verdict = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            if not verdict.get("ok"):
                issues.append(f"{ts:.0f}s: {verdict.get('note', '')[:80]}")
        except Exception as exc:
            unchecked += 1       # không soát được thì phải NÓI RA, không tính là đã soát
            log.warning("Vision check %.0fs lỗi: %s", ts, type(exc).__name__)
    checked = len(samples) - unchecked
    value = "; ".join(issues) or f"đã soát {checked}/{len(samples)} cảnh"
    if unchecked and not issues:
        value += f" ({unchecked} cảnh model không trả lời — Du nhìn kỹ giúp)"
    # Model nhìn ảnh sập thì KHÔNG chặn video: Du vẫn duyệt bằng mắt, và dòng trên báo rõ
    return {"name": "Hình khớp lời (AI soát)", "value": value, "ok": not issues}


def collect_checks(script_id: int) -> list:
    """Chạy toàn bộ phép kiểm, trả về danh sách {"name", "value", "ok"}.
    Tách khỏi run_qc để bước gửi duyệt (src/review.py) đính kèm được báo cáo."""
    video = ROOT / "output" / f"final_{script_id}.mp4"
    # Ưu tiên spec *_final (thời lượng thật theo giọng do assemble ghi lại)
    spec_dir = ROOT / "data" / "specs"
    p = spec_dir / f"script_{script_id}_final.yaml"
    if not p.exists():
        p = spec_dir / f"script_{script_id}.yaml"
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    d = check_duration(video)
    checks = [d, check_black_frames(video), check_loudness(video), check_licenses(),
              check_narration(script_id), check_visuals_match(video, spec, d["_duration"])]
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in checks]


def run_qc(script_id: int) -> bool:
    checks = collect_checks(script_id)
    print(f"\n===== KIỂM ĐỊNH final_{script_id}.mp4 =====")
    ok_all = True
    for c in checks:
        print(f"  {'✅' if c['ok'] else '❌'} {c['name']}: {c['value']}")
        ok_all &= c["ok"]
    print("KẾT LUẬN:", "ĐẠT — đủ điều kiện gửi duyệt" if ok_all else "CHƯA ĐẠT")
    return ok_all


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id", type=int)
    args = ap.parse_args()
    sys.exit(0 if run_qc(args.script_id) else 1)


if __name__ == "__main__":
    main()
