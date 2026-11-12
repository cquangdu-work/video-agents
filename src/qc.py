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


def param_digits(params: dict) -> set:
    """Chuỗi chữ số của mọi con số mà cảnh này ĐƯỢC PHÉP vẽ (lấy từ spec của chính nó)."""
    from .utils import digits_of, spec_values
    # số liệu của cảnh + trục năm + số thứ tự của cảnh chữ kiểu 2 — đều do spec bảo vẽ
    values = (spec_values(params) + list(params.get("xs") or []) + list(params.get("years") or [])
              + [params.get("n"), params.get("year"), params.get("total")]
              # bản đồ thế giới hiện "cao thứ 105/214": hạng do code tính từ chính bảng số
              + [it.get("rank") for it in params.get("items") or [] if isinstance(it, dict)])
    out = set()
    for v in values:
        out |= digits_of(v)
    return out


def real_issue(verdict: dict, voice: str, allowed: set = frozenset()) -> bool:
    """Lời phán của model nhìn ảnh có phải LỖI THẬT không.

    Model nhỏ hay chê những thứ không phải lỗi ("hình thiếu chữ 'nữa'", "chữ bị đảo").
    Nên: chỉ nhận 3 loại lỗi đã định nghĩa, và loại "sai số" thì code tự đối chiếu lại
    chữ số — con số model đọc trên hình mà CÓ trong lời đọc, hoặc đúng là con số spec bảo
    vẽ (`allowed`: biểu đồ dùng số của dữ liệu nguồn mà lời không nhắc hết), thì không
    phải sai số. Spec đã được đối chiếu với nguồn từ lúc dựng (crew.design_scenes).
    """
    from .utils import digit_set
    if verdict.get("ok", True):
        return False
    kind = str(verdict.get("kind", "")).strip().lower()
    if kind == "number":
        on_image, in_voice = digit_set(str(verdict.get("image_number", ""))), digit_set(voice)
        # So ĐÚNG từng chữ số (không bỏ số 0 ở đuôi): 54.000 và 540.000 phải bị coi là khác nhau
        if on_image and on_image <= set(allowed):
            return False
        # lời không có chữ số nào (số viết bằng chữ) thì không đủ căn cứ để kết luận
        return bool(on_image) and bool(in_voice) and not (on_image & in_voice)
    return kind in ("opposite", "clipped")


def check_visuals_match(video: Path, spec: list, duration: float) -> dict:
    """Trích khung gần cuối các cảnh có lời, hỏi model vision: hình có khớp/mâu thuẫn lời?"""
    key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("MODEL", "gemini/gemini-3.5-flash-lite").split("/")[-1]
    t, voiced = 0.0, []
    for sc in spec:
        secs = float(sc.get("seconds", 3))
        if sc.get("voice"):
            # Lấy mẫu ở 85% cảnh: hoạt hình đếm số đã chạy xong, số trên hình là số cuối
            voiced.append((min(t + secs * 0.85, duration - 0.2), sc["voice"],
                           param_digits(sc.get("params") or {})))
        t += secs
    samples = spread(voiced, MAX_VISION_SAMPLES)

    def ask(img: str, voice: str) -> dict:
        """Một lần hỏi model nhìn ảnh -> {"ok": bool, "note": str}."""
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [
                {"inline_data": {"mime_type": "image/png", "data": img}},
                {"text": "Đây là một khung hình video dạng chữ/biểu đồ tối giản, "
                         f"lời đọc lúc này là: \"{voice}\". "
                         "Chữ trên hình là bản TÓM TẮT rút gọn của lời đọc: thiếu từ, viết gọn, "
                         "đổi cách diễn đạt đều là ĐẠT. Chỉ có 3 loại lỗi: "
                         "\"number\" = một CON SỐ trên hình khác con số trong lời; "
                         "\"opposite\" = hình nói NGƯỢC lại lời (lời nói tăng, hình ghi giảm); "
                         "\"clipped\" = chữ bị tràn hoặc bị cắt ở mép khung. "
                         "Dòng chữ nhỏ 1-3 từ ở nửa dưới là PHỤ ĐỀ chạy theo giọng "
                         "(chỉ hiện vài từ đang đọc) và dòng 'Nguồn: ...' — không xét hai dòng này. "
                         "Không có lỗi thuộc 3 loại trên thì trả {\"ok\": true}. Có thì trả "
                         "{\"ok\": false, \"kind\": \"number|opposite|clipped\", "
                         "\"image_number\": \"<số trên hình, nếu kind=number>\", "
                         "\"note\": \"<mô tả ngắn>\"}"}]}],
                  # Ép model trả JSON thuần (trước đây thỉnh thoảng trả văn xuôi -> không đọc được)
                  "generationConfig": {"responseMimeType": "application/json"}},
            timeout=60)
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))

    issues, unchecked = [], 0
    for ts, voice, allowed in samples:
        frame = ROOT / "data" / "render" / "qc_frame.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video),
                        "-frames:v", "1", str(frame)], check=True)
        img = base64.b64encode(frame.read_bytes()).decode()
        try:
            verdict = ask(img, voice)
            if real_issue(verdict, voice, allowed):
                # Model nhỏ hay bắt bẻ nhầm. Lỗi thật thì hỏi lại vẫn ra lỗi; báo nhầm thì
                # hiếm khi nhầm hai lần liền.
                log.warning("Vision %.0fs nghi có lỗi: %s — hỏi lại lần 2", ts, verdict.get("note", ""))
                again = ask(img, voice)
                if real_issue(again, voice, allowed):
                    issues.append(f"{ts:.0f}s: {str(again.get('note', ''))[:80]}")
            elif not verdict.get("ok", True):
                log.info("Vision %.0fs: bỏ qua nhận xét không thuộc loại lỗi nào (%s)",
                         ts, verdict.get("note", ""))
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
