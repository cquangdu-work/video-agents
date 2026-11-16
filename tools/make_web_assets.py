"""Tạo chất liệu tĩnh cho engine Remotion (render-web/public/) — chạy lại được, kết quả giống hệt.

    python tools/make_web_assets.py

- grain.png: hạt nhiễu kiểu phim (numpy, hạt giống cố định).
- sfx/*.wav: âm thanh hiệu ứng TỰ TỔNG HỢP bằng ffmpeg (sóng sin, nhiễu hồng) -> chất liệu
  của kênh, không vướng giấy phép của ai.
- flags/*.svg: cờ chép từ gói flag-icons (giấy phép MIT, kèm file LICENSE).
"""
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

PUBLIC = Path(__file__).resolve().parent.parent / "render-web" / "public"

# tên -> (nguồn ffmpeg, bộ lọc thêm). aevalsrc: biểu thức theo thời gian t (giây).
SFX = {
    # bật nhẹ: sin trượt 600->1500 Hz, tắt nhanh
    "pop": ("aevalsrc='0.55*sin(2*PI*(600+900*t)*t)*exp(-t*32)':s=48000:d=0.16", None),
    # tích: tiếng gõ rất ngắn
    "tick": ("aevalsrc='0.45*sin(2*PI*2400*t)*exp(-t*140)':s=48000:d=0.05", None),
    # thụp: âm trầm rơi 120->60 Hz cho con số chốt
    "thump": ("aevalsrc='0.9*sin(2*PI*(120-55*t)*t)*exp(-t*8)':s=48000:d=0.5", None),
    # vút: nhiễu hồng lọc dải, to dần rồi nhỏ dần — chuyển cảnh
    "whoosh": ("anoisesrc=d=0.55:c=pink:a=0.6:r=48000:seed=7",
               "highpass=f=350,lowpass=f=4200,afade=t=in:d=0.3:curve=exp,afade=t=out:st=0.3:d=0.25"),
    # vọt lên: sin trượt lên 220->820 Hz khi đường biểu đồ bứt lên
    "rise": ("aevalsrc='0.3*sin(2*PI*(220*t+250*t*t))*min(1\\,t*5)*(1-t/1.2)':s=48000:d=1.2", None),
}


def make_grain(path: Path, size: int = 256):
    rng = np.random.default_rng(20261116)
    a = (rng.random((size, size)) * 255).astype(np.uint8)
    Image.fromarray(a, mode="L").convert("RGB").save(path, optimize=True)


def make_sfx(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (src, filt) in SFX.items():
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src]
        if filt:
            cmd += ["-af", filt]
        cmd += ["-ac", "1", "-ar", "48000", str(out_dir / f"{name}.wav")]
        subprocess.run(cmd, check=True)


def copy_flags(out_dir: Path, codes=("vn", "kr")):
    src = PUBLIC.parent / "node_modules" / "flag-icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    for c in codes:
        shutil.copy(src / "flags" / "4x3" / f"{c}.svg", out_dir / f"{c}.svg")
    shutil.copy(src / "LICENSE", out_dir / "LICENSE-flag-icons.txt")


if __name__ == "__main__":
    PUBLIC.mkdir(parents=True, exist_ok=True)
    make_grain(PUBLIC / "grain.png")
    make_sfx(PUBLIC / "sfx")
    copy_flags(PUBLIC / "flags")
    print("OK:", sorted(p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob("*") if p.is_file()))
