"""Engine dựng video: danh sách cảnh (scene spec) -> file MP4 dọc 1080x1920.

Scene spec là list dict — sau này agent Sản xuất sinh ra nó từ kịch bản:
    [{"template": "big_number", "seconds": 3, "params": {...}}, ...]

Chạy demo:  python -m src.render.engine          (render output/demo.mp4)
Từ file:    python -m src.render.engine spec.yaml tên_video
"""
import logging
import subprocess
import sys
from pathlib import Path

import yaml
from manim import config, tempconfig

from .. import assets_db
from .base import brand
from .templates import TEMPLATES

log = logging.getLogger("engine")

ROOT = Path(__file__).resolve().parent.parent.parent
RENDER_DIR = ROOT / "data" / "render"
OUTPUT_DIR = ROOT / "output"


def _portrait_config(out_name: str) -> dict:
    f = brand()["frame"]
    return {
        "pixel_width": f["pixel_width"], "pixel_height": f["pixel_height"],
        "frame_width": f["frame_width"], "frame_height": f["frame_height"],
        "frame_rate": f["fps"],
        "media_dir": str(RENDER_DIR),
        "output_file": out_name,
        "disable_caching": True,
        "verbosity": "WARNING",
        "progress_bar": "none",
    }


def render_scene(spec: dict, index: int) -> Path:
    cls = TEMPLATES[spec["template"]]
    with tempconfig(_portrait_config(f"scene_{index:02d}")):
        scene = cls(params=spec.get("params", {}), seconds=spec.get("seconds", 3))
        scene.render()
        return Path(scene.renderer.file_writer.movie_file_path)


def concat(files: list, out_path: Path) -> Path:
    """Nối các cảnh bằng ffmpeg (cùng codec nên copy thẳng, không re-encode)."""
    lst = RENDER_DIR / "concat.txt"
    lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out_path)],
                   check=True, capture_output=True)
    return out_path


def build_video(scene_specs: list, name: str) -> Path:
    """Render từng cảnh rồi nối; ghi nhật ký dùng chất liệu + cảnh báo lặp."""
    con = assets_db.init_assets()
    names = [s["template"] for s in scene_specs]
    for w in assets_db.check_rotation(con, names):
        log.warning("CHỐNG LẶP: %s", w)

    files = []
    for i, spec in enumerate(scene_specs):
        log.info("Render cảnh %d/%d: %s", i + 1, len(scene_specs), spec["template"])
        files.append(render_scene(spec, i))
    out = concat(files, OUTPUT_DIR / f"{name}.mp4")
    for n in names:
        assets_db.record_use(con, n, name)
    log.info("Xong: %s", out)
    return out


# ------------------------------------------------------------------ demo
DEMO_SPEC = [
    {"template": "intro", "seconds": 1.2, "params": {}},
    {"template": "big_number", "seconds": 3, "params": {
        "title": "Mỗi năm cơ thể loài người\nthải ra lượng CO₂",
        "value": 2_000_000_000, "suffix": "tấn CO₂ — chỉ nhờ việc thở",
        "source": "ScienceDaily, 2026"}},
    {"template": "versus", "seconds": 3.5, "params": {
        "title": "Tuổi kết hôn lần đầu\ncủa nam giới (2024)",
        "left": {"label": "Việt Nam", "value": 29.3},
        "right": {"label": "Hàn Quốc", "value": 33.9},
        "suffix": "tuổi — trung bình", "decimals": 1,
        "source": "GSO Việt Nam · KOSIS Hàn Quốc"}},
    {"template": "bar_chart", "seconds": 3.5, "params": {
        "title": "Quốc gia uống cà phê\nnhiều nhất (kg/người/năm)",
        "items": [
            {"label": "Phần Lan", "value": 12.0},
            {"label": "Na Uy", "value": 9.9},
            {"label": "Hà Lan", "value": 8.3},
            {"label": "Hàn Quốc", "value": 2.6, "color": "korea"},
            {"label": "Việt Nam", "value": 2.2, "color": "vietnam"},
        ], "decimals": 1, "unit": "kg cà phê / người / năm",
        "source": "International Coffee Organization"}},
    {"template": "line_chart", "seconds": 3.5, "params": {
        "title": "Giá trị 1 Bitcoin (nghìn USD)",
        "xs": [2016, 2018, 2020, 2022, 2024, 2026],
        "ys": [0.9, 13.0, 29.0, 16.5, 73.0, 95.0],
        "unit": "nghìn USD", "source": "CoinGecko"}},
]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) >= 2:
        spec = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
        name = sys.argv[2] if len(sys.argv) > 2 else "video"
    else:
        spec, name = DEMO_SPEC, "demo"
    build_video(spec, name)


if __name__ == "__main__":
    main()
