"""Vẽ avatar kênh bằng code, dùng đúng bộ nhận diện của video (config/brand.yaml).

    python tools/make_avatar.py            # -> assets/brand/avatar_*.png (800x800)
                                           #    + output/avatar_preview.png (thử ở cỡ nhỏ)
    python tools/make_avatar.py --size 1024  # -> assets/brand/avatar_*_1024.png (icon app TikTok)

Vì sao vẽ bằng code: avatar nhìn cùng "họ" với video (nền xanh đen, vàng hổ phách, Việt Nam
đỏ, Hàn Quốc xanh), nét ở mọi cỡ, và không vướng giấy phép (bản đồ Natural Earth thuộc phạm
vi công cộng, phần còn lại do dự án tự vẽ).

Hai mẫu:
- race: các thanh ngang của "cuộc đua số liệu" — đúng hình ảnh đặc trưng trong video.
- vnkr: hình chữ S của Việt Nam (có Hoàng Sa, Trường Sa) và Hàn Quốc, đường số liệu đi lên.
YouTube khuyên ảnh đại diện 800x800 px; mọi nền tảng tự cắt tròn.
"""
import json
import math
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"
SIZE, SS = 800, 4                      # ảnh ra 800 px, vẽ ở 4 lần cỡ rồi thu nhỏ cho mịn nét


def colors() -> dict:
    return yaml.safe_load((ROOT / "config" / "brand.yaml").read_text(encoding="utf-8"))["colors"]


def canvas():
    n = SIZE * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), n


def disc(draw, n, c, ring=True):
    """Nền tròn xanh đen + viền hổ phách mảnh (viền làm avatar nổi trên giao diện tối)."""
    draw.ellipse([0, 0, n - 1, n - 1], fill=c["background"])
    if ring:
        w = int(n * 0.022)
        draw.ellipse([w // 2, w // 2, n - 1 - w // 2, n - 1 - w // 2], outline=c["accent"], width=w)


def finish(img) -> Image.Image:
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def rounded_bar(draw, x0, y0, x1, y1, fill):
    r = (y1 - y0) / 2
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)


def make_race(c: dict) -> Image.Image:
    """Bốn thanh ngang dài ngắn khác nhau như khung cuối của cuộc đua số liệu."""
    img, d, n = canvas()
    disc(d, n, c)
    x0 = n * 0.22
    rows = [(0.62, c["accent"]), (0.47, c["korea"]), (0.36, c["vietnam"]), (0.22, c["muted"])]
    h, gap = n * 0.105, n * 0.052
    top = n / 2 - (len(rows) * h + (len(rows) - 1) * gap) / 2
    for k, (length, col) in enumerate(rows):
        y = top + k * (h + gap)
        rounded_bar(d, x0, y, x0 + n * length, y + h, col)
    # trục dọc mảnh bên trái — gợi "biểu đồ", không phải chỉ là mấy vạch màu
    w = n * 0.012
    d.rounded_rectangle([x0 - n * 0.045, top - n * 0.02, x0 - n * 0.045 + w,
                         top + len(rows) * h + (len(rows) - 1) * gap + n * 0.02],
                        radius=w / 2, fill=c["text"])
    return finish(img)


def make_vnkr(c: dict) -> Image.Image:
    """Hình chữ S Việt Nam (đỏ, có Hoàng Sa – Trường Sa) và Hàn Quốc (xanh) cùng tỷ lệ,
    một đường số liệu hổ phách đi lên phía sau."""
    sys.path.insert(0, str(ROOT))
    from src.render.geo import VN_ISLANDS
    geo = json.loads((ROOT / "assets" / "geo" / "asia.json").read_text(encoding="utf-8"))
    img, d, n = canvas()
    disc(d, n, c)

    # đường số liệu đi lên (vẽ trước để nằm dưới hai nước); các điểm được chọn để đi qua
    # khe trống giữa bờ biển Việt Nam, Hoàng Sa, Trường Sa và Hàn Quốc
    pts = [(0.26, 0.86), (0.44, 0.88), (0.62, 0.74), (0.66, 0.60), (0.76, 0.50), (0.88, 0.42)]
    line = [(x * n, y * n) for x, y in pts]
    d.line(line, fill=c["accent"], width=int(n * 0.03), joint="curve")
    for x, y in line[1:-1]:
        r = n * 0.022
        d.ellipse([x - r, y - r, x + r, y + r], fill=c["accent"])
    tip = line[-1]
    r = n * 0.034
    d.ellipse([tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r], fill=c["accent"])

    # Việt Nam: chiếu kinh-vĩ độ, cao ~62% khung, đặt lệch trái
    k = math.cos(math.radians(16))
    vn = geo["countries"]["VNM"]["rings"]
    lat_lo, lat_hi = 8.4, 23.5
    scale = n * 0.62 / (lat_hi - lat_lo)
    ox, oy = n * 0.40, n * 0.19            # vị trí điểm (kinh độ 105, vĩ độ lat_hi)

    def at(lon, lat, dx=0.0, dy=0.0):
        return (ox + (lon - 105) * k * scale + dx, oy + (lat_hi - lat) * scale + dy)

    for ring in vn:
        d.polygon([at(lon, lat) for lon, lat in ring], fill=c["vietnam"])
    for _, spots, _, _ in VN_ISLANDS:      # Hoàng Sa, Trường Sa: cùng phép chiếu, cùng màu
        for lon, lat in spots:
            x, y = at(lon, lat)
            r = n * 0.011
            d.ellipse([x - r, y - r, x + r, y + r], fill=c["vietnam"])

    # Hàn Quốc: CÙNG tỷ lệ với Việt Nam (so sánh công bằng), dời về góc trên bên phải theo
    # khung bao của chính nó (vị trí địa lý thật nằm ngoài khung ảnh)
    kr = geo["countries"]["KOR"]["rings"]
    raw = [at(lon, lat) for ring in kr for lon, lat in ring]
    cx = (min(p[0] for p in raw) + max(p[0] for p in raw)) / 2
    cy = (min(p[1] for p in raw) + max(p[1] for p in raw)) / 2
    dx, dy = n * 0.72 - cx, n * 0.25 - cy
    for ring in kr:
        d.polygon([at(lon, lat, dx, dy) for lon, lat in ring], fill=c["korea"])
    return finish(img)


def preview(images: dict, path: Path):
    """Bảng thử: mỗi mẫu ở 176/98/48/32/24 px, cắt tròn, trên nền sáng và tối của YouTube."""
    sizes, pad = [176, 98, 48, 32, 24], 20
    row_h = max(sizes) + 2 * pad
    w = sum(sizes) + pad * (len(sizes) + 1)
    sheet = Image.new("RGB", (w * 2, row_h * len(images)), "#FFFFFF")
    dr = ImageDraw.Draw(sheet)
    for col, bg in enumerate(("#FFFFFF", "#0F0F0F")):
        dr.rectangle([col * w, 0, col * w + w, sheet.height], fill=bg)
        for r, im in enumerate(images.values()):
            x = col * w + pad
            for s in sizes:
                small = im.resize((s, s), Image.LANCZOS)
                mask = Image.new("L", (s, s), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, s - 1, s - 1], fill=255)
                sheet.paste(small, (x, r * row_h + pad + (max(sizes) - s) // 2), mask)
                x += s + pad
    sheet.save(path)


def main():
    c = colors()
    OUT.mkdir(parents=True, exist_ok=True)
    made = {"race": make_race(c), "vnkr": make_vnkr(c)}
    for name, im in made.items():
        im.save(OUT / (f"avatar_{name}.png" if SIZE == 800 else f"avatar_{name}_{SIZE}.png"))
    (ROOT / "output").mkdir(exist_ok=True)              # bảng thử là file tạm, không vào git
    preview(made, ROOT / "output" / "avatar_preview.png")
    print("Đã tạo:", ", ".join(f"assets/brand/avatar_{k}.png" for k in made),
          "+ bảng thử output/avatar_preview.png")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--size" in sys.argv:              # TikTok đòi icon ứng dụng 1024x1024
        SIZE = int(sys.argv[sys.argv.index("--size") + 1])
    main()
