"""Ảnh bìa trang kênh: YouTube (2560x1440) và Trang Facebook (1702x630). Du xin 21/11/2026: "hoàn thành các kênh và
mạng xã hội một cách chuyên nghiệp".

Vẽ bằng chính engine Remotion của video (render-web/src/BrandArt.tsx), nên cùng bộ nhận diện: nền xanh đen, lưới
chấm, chữ Be Vietnam Pro, Việt Nam đỏ / Hàn Quốc xanh / số liệu vàng. Chữ lấy từ cấu hình kênh (`profile.banner`).

Bản đồ theo GÓC NHÌN của kênh (geo.load_map đọc file theo src/lang.py):
- kênh Việt nhấn Việt Nam + Hàn Quốc và LUÔN vẽ Hoàng Sa, Trường Sa cùng màu Việt Nam, có tên (luật bản đồ, CLAUDE.md);
- kênh Hàn nhấn Hàn Quốc, có 독도 (cùng màu Hàn Quốc, có tên) và tên biển 동해.
Python tính hết phần địa lý (phép chiếu Equal Earth như bản đồ thế giới trong video); Remotion chỉ tô màu.

Vùng an toàn (tra 21/11/2026, nguồn thứ cấp): YouTube hiện đủ 2560x1440 trên TV, máy tính chỉ dải giữa cao 423 điểm
ảnh, điện thoại khung giữa 1546x423 -> chữ và vùng được nhấn nằm trong khung giữa đó. Facebook: máy tính ~820x312,
điện thoại 640x360 (cắt bớt hai bên) -> chữ và vùng nhấn nằm trong ~2/3 giữa bề ngang (kiểm bằng test).

Chạy:  python -m src.brand_kit              -> assets/brand/<mã ngôn ngữ>/youtube_banner.png, facebook_cover.png
       python -m src.brand_kit --guides     -> vẽ thêm khung vùng an toàn để soát (không dùng bản này để đăng)
Kênh Hàn: đặt CHANNEL_CONFIG=config/channel_ko.yaml.
"""
import argparse
import json
import logging
import subprocess
from pathlib import Path

import yaml

from . import lang
from .render import geo

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "brand"

# size: kích thước ảnh · safe: (x0, y0, x1, y1) vùng mọi thiết bị đều thấy · box: khối chữ (x, y, rộng, cao, cỡ tên kênh)
SPECS = {
    "banner": {"size": (2560, 1440), "safe": (507, 509, 2053, 931), "file": "youtube_banner.png",
               "box": {"x": 560, "y": 509, "w": 1080, "h": 422, "title": 100}},
    "cover": {"size": (1702, 630), "safe": (291, 0, 1411, 630), "file": "facebook_cover.png",
              "box": {"x": 330, "y": 40, "w": 640, "h": 550, "title": 84}},
}
# Bản đồ theo ngôn ngữ kênh và loại ảnh: điểm `center` (kinh độ, vĩ độ) đặt ở `at` (điểm ảnh), `ppd` điểm ảnh mỗi độ
# kinh ở xích đạo. Kênh Việt: Việt Nam + Hàn Quốc + Hoàng Sa + Trường Sa (vĩ độ 7,7-38,6) phải lọt CẢ vào dải
# máy tính thấy được (bản đầu 13,5 điểm ảnh/độ: mũi Cà Mau và Trường Sa rơi ra ngoài dải) — test_brand_kit kiểm.
VIEWS = {
    ("vi", "banner"): {"center": (116.0, 22.4), "at": (1860, 720), "ppd": 9.6},
    ("vi", "cover"): {"center": (116.0, 23.2), "at": (1190, 315), "ppd": 12.0},
    ("ko", "banner"): {"center": (128.5, 36.6), "at": (1780, 720), "ppd": 22.0},
    ("ko", "cover"): {"center": (128.5, 36.6), "at": (1190, 315), "ppd": 20.0},
}
LAND_MIX = 0.3        # màu đất liền = nền phụ pha 30% màu chữ phụ (bản đầu dùng nguyên nền phụ: lẫn vào nền, biển
                      # trông như đất)


def focus() -> dict:
    """{mã nước: khoá màu} các nước được nhấn: Việt Nam + Hàn Quốc (kênh Việt) | Hàn Quốc (kênh Hàn — không nhấn Nhật
    Bản trên ảnh bìa: nước so sánh trong video, không phải nhận diện của kênh)."""
    return {"KOR": "korea"} if lang.code() == "ko" else {"VNM": "vietnam", "KOR": "korea"}


def projector(center: tuple, at: tuple, ppd: float):
    """(kinh độ, vĩ độ) -> (x, y) điểm ảnh: Equal Earth, điểm `center` nằm ở `at`, `ppd` điểm ảnh mỗi độ ở xích đạo."""
    unit = geo.equal_earth(1.0, 0.0)[0] - geo.equal_earth(0.0, 0.0)[0]
    s = ppd / unit
    x0, y0 = geo.equal_earth(*center)

    def to_px(lon: float, lat: float) -> tuple:
        x, y = geo.equal_earth(lon, lat)
        return round(at[0] + (x - x0) * s, 1), round(at[1] - (y - y0) * s, 1)
    return to_px


def _path(rings: list, to_px, size: tuple, min_step: float = 0.7) -> str:
    """Đường SVG của các vòng ranh giới; bỏ vòng nằm hẳn ngoài ảnh và điểm sát điểm trước (< min_step điểm ảnh)."""
    w, h = size
    out = []
    for ring in rings:
        pts = [to_px(lon, lat) for lon, lat in ring]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) < -20 or min(xs) > w + 20 or max(ys) < -20 or min(ys) > h + 20 or len(pts) < 3:
            continue
        keep = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - keep[-1][0]) + abs(p[1] - keep[-1][1]) >= min_step:
                keep.append(p)
        if len(keep) >= 3:
            out.append("M" + " L".join(f"{x},{y}" for x, y in keep) + " Z")
    return " ".join(out)


def map_layer(kind: str, colors: dict) -> dict:
    """Bản đồ của ảnh bìa: mọi nước màu nền phụ, nước được nhấn có màu riêng + quầng sáng, đảo tự vẽ + tên theo góc
    nhìn của kênh. -> {"paths", "dots", "labels", "glowAt", "boxes"} (boxes: khung bao từng nước được nhấn + đảo,
    để test kiểm chúng nằm trong vùng an toàn)."""
    from .render.web_map import _mix
    spec, view = SPECS[kind], VIEWS[(lang.code(), kind)]
    size = spec["size"]
    to_px = projector(view["center"], view["at"], view["ppd"])
    hi = focus()
    land = _mix(colors["surface"], colors["muted"], LAND_MIX)
    paths, boxes = [], {}
    for code, c in geo.load_map("world")["countries"].items():
        d = _path(c["rings"], to_px, size)
        if not d:
            continue
        if code in hi:
            paths.append({"d": d, "fill": colors[hi[code]], "glow": True})
            pts = [to_px(lon, lat) for ring in c["rings"] for lon, lat in ring]
            boxes[code] = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        else:
            paths.append({"d": d, "fill": land})
    anchor = colors[next(iter(hi.values()))]               # màu của nước "ta": đảo tự vẽ cùng màu
    ppd = view["ppd"]
    size_lbl = round(max(20.0, 1.5 * ppd))
    dots, labels = [], []
    for name, spots, (lab_lon, lab_lat), align in geo.islands():
        pts = [to_px(lon, lat) for lon, lat in spots]
        dots += [[x, y, round(max(2.6, 0.26 * ppd), 1), anchor] for x, y in pts]
        x, y = to_px(lab_lon, lab_lat)
        labels.append({"text": name, "x": x, "y": y, "size": size_lbl, "color": anchor,
                       "anchor": "start" if align == "left" else "middle"})
        boxes[name] = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    for name, (lon, lat) in geo.sea_labels():
        x, y = to_px(lon, lat)
        labels.append({"text": name, "x": x, "y": y, "size": size_lbl, "color": colors["muted"], "anchor": "middle"})
    cx = sum((b[0] + b[2]) / 2 for b in boxes.values()) / len(boxes)
    cy = sum((b[1] + b[3]) / 2 for b in boxes.values()) / len(boxes)
    return {"paths": paths, "dots": dots, "labels": labels, "glowAt": [round(cx), round(cy)], "boxes": boxes}


def load_profile(cfg: dict = None) -> dict:
    if cfg is None:
        cfg = yaml.safe_load(lang.config_path().read_text(encoding="utf-8")) or {}
    return cfg.get("profile") or {}


def props(kind: str, cfg: dict = None, guides: bool = False) -> dict:
    from .render import web
    colors = web.brand_props()
    banner = load_profile(cfg).get("banner") or {}
    spec = SPECS[kind]
    layer = map_layer(kind, colors)
    layer.pop("boxes")
    w, h = spec["size"]
    out = {"width": w, "height": h, "brand": colors,
           "title": list(banner.get("title") or [colors["channel"]]), "accent": banner.get("accent", ""),
           "tagline": banner.get("tagline", ""),
           "chip": banner.get("chip", ""), "sources": banner.get("sources", ""),
           "box": spec["box"], "map": layer, "shade": spec["box"]["x"] + spec["box"]["w"]}
    if lang.code() != "vi":
        out["lang"] = lang.code()
    if guides:
        out["guides"] = [list(spec["safe"])]
    return out


def render(kind: str, out: Path = None, cfg: dict = None, guides: bool = False) -> Path:
    """Vẽ một ảnh (PNG: chữ và mảng màu phẳng nét hơn JPEG — Meta cũng khuyên PNG cho ảnh bìa có chữ)."""
    from .render import web
    out = out or OUT_DIR / lang.code() / SPECS[kind]["file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    pf = out.with_suffix(".props.json")
    pf.write_text(json.dumps(props(kind, cfg, guides), ensure_ascii=False), encoding="utf-8")
    npx, env = web.node_env()
    try:
        subprocess.run([npx, "remotion", "still", "src/index.ts", "BrandArt", str(out.resolve()), f"--props={pf.resolve()}",
                        "--image-format=png", "--log=error"], cwd=web.WEB, env=env, check=True, timeout=600,
                       capture_output=True, shell=str(npx).endswith(".cmd"))
    finally:
        pf.unlink(missing_ok=True)
    log.info("Ảnh bìa %s -> %s", kind, out)
    return out


def main():
    ap = argparse.ArgumentParser(description="Vẽ ảnh bìa YouTube + Facebook của kênh")
    ap.add_argument("--only", choices=sorted(SPECS))
    ap.add_argument("--guides", action="store_true", help="vẽ khung vùng an toàn (bản soát, không đăng)")
    ap.add_argument("--out-dir", type=Path)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for kind in [a.only] if a.only else list(SPECS):
        name = SPECS[kind]["file"].replace(".png", "_guides.png" if a.guides else ".png")
        out = (a.out_dir / name) if a.out_dir else OUT_DIR / lang.code() / name
        print(render(kind, out, guides=a.guides))


if __name__ == "__main__":
    main()
