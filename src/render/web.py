"""Cầu nối Python -> engine dựng hình Remotion (thư mục render-web/).

Python vẫn làm chủ mọi thứ quan trọng: số liệu (lấy từ bảng gốc), mốc thời gian (từ giọng
đọc thật + Whisper), lời phụ đề (từ kịch bản). File này chỉ đóng gói chúng thành một JSON
"props" rồi gọi `npx remotion render`. Phía Remotion không tự sinh con số nào.

    words = words_from_ass(Path("data/render/subs.ass"))
    render(props, Path("out.mp4"))
"""
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from .base import brand

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "render-web"

_ASS_LINE = re.compile(r"^Dialogue: \d+,(\d+):(\d\d):(\d\d\.\d\d),(\d+):(\d\d):(\d\d\.\d\d),[^,]*,[^,]*,"
                       r"[^,]*,[^,]*,[^,]*,[^,]*,(.*)$")
_TAG = re.compile(r"\{[^}]*\}")


def _secs(h, m, s) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def words_from_ass(path: Path) -> list:
    """Đọc lại phụ đề .ass mà src/audio/subtitles.py đã ghi (mỗi dòng = một cụm, từ đang đọc
    được tô màu) -> [{"w": từ, "s": bắt đầu, "e": kết thúc, "c": số cụm}].
    Dùng cho video đã dựng trước khi assemble lưu sẵn words.json."""
    out, chunk, last_plain = [], -1, None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = _ASS_LINE.match(line)
        if not m:
            continue
        start, end, text = _secs(*m.group(1, 2, 3)), _secs(*m.group(4, 5, 6)), m.group(7)
        plain = _TAG.sub("", text)
        if plain != last_plain:
            chunk, last_plain = chunk + 1, plain
        hit = re.search(r"\{\\c&H0003B7FF&\}([^{]*)\{", text)   # từ được tô = từ đang đọc
        if hit:
            out.append({"w": hit.group(1).strip(), "s": round(start, 3), "e": round(end, 3), "c": chunk})
    return out


def find_word(words: list, pattern: str, after: float = 0.0, before: float = 1e9):
    """Mốc bắt đầu của từ đầu tiên khớp `pattern` (regex, không phân biệt hoa thường) trong khoảng
    [after, before). Dùng để cho hình xuất hiện ĐÚNG lúc lời đọc nói tới."""
    rx = re.compile(pattern, re.I)
    for w in words:
        if after <= w["s"] < before and rx.fullmatch(w["w"].strip(".,?!:;")):
            return w["s"]
    return None


def scene_spans(spec: list) -> list:
    """Spec đã có thời lượng thật (script_<id>_final.yaml) -> [(bắt đầu, kết thúc, cảnh)]."""
    t, out = 0.0, []
    for sc in spec:
        out.append((round(t, 3), round(t + float(sc["seconds"]), 3), sc))
        t += float(sc["seconds"])
    return out


def brand_props() -> dict:
    b = brand()
    return {**b["colors"], "channel": b["intro"]["text"]}


def render(props: dict, out: Path, concurrency: int = 3) -> Path:
    """Ghi props ra JSON rồi gọi Remotion. Lần đầu trên máy mới cần `npm ci` trong render-web/."""
    out.parent.mkdir(parents=True, exist_ok=True)
    props_path = out.with_suffix(".props.json")
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    cmd = [npx, "remotion", "render", "src/index.ts", "Story", str(out.resolve()),
           f"--props={props_path.resolve()}", f"--concurrency={concurrency}", "--log=error"]
    log.info("Remotion render -> %s", out.name)
    subprocess.run(cmd, cwd=WEB, check=True)
    return out
