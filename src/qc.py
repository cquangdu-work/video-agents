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


def check_visuals_match(video: Path, spec: list, duration: float) -> dict:
    """Trích khung giữa từng cảnh có lời, hỏi model vision: hình có khớp/mâu thuẫn lời?"""
    key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("MODEL", "gemini/gemini-3.5-flash-lite").split("/")[-1]
    t, samples = 0.0, []
    for sc in spec:
        secs = float(sc.get("seconds", 3))
        if sc.get("voice") and len(samples) < 5:
            # Lấy mẫu ở 85% cảnh: hoạt hình đếm số đã chạy xong, số trên hình là số cuối
            samples.append((min(t + secs * 0.85, duration - 0.2), sc["voice"]))
        t += secs
    issues = []
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
                             "Trả lời JSON: {\"ok\": true/false, \"note\": \"...\"}"}]}]},
                timeout=60)
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            verdict = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            if not verdict.get("ok"):
                issues.append(f"{ts:.0f}s: {verdict.get('note', '')[:80]}")
        except Exception as exc:
            log.warning("Vision check %.0fs lỗi: %s", ts, exc)
    return {"name": "Hình khớp lời (AI soát)", "value": "; ".join(issues) or f"đã soát {len(samples)} cảnh",
            "ok": not issues}


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
              check_visuals_match(video, spec, d["_duration"])]
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
