"""Agent Sản xuất: kịch bản đã kiểm chứng trong DB -> scene spec -> video MP4.

    python -m src.produce              # lấy kịch bản mới nhất đã verified
    python -m src.produce 2            # kịch bản id=2
    python -m src.produce 2 --spec-only  # chỉ sinh + in spec, không render

Spec được LƯU ra data/specs/script_<id>.yaml trước khi render — Du có thể sửa
tay rồi render lại bằng: python -m src.render.engine data/specs/script_2.yaml ten_video
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import db
from .main import load_config

log = logging.getLogger("produce")

SPEC_DIR = Path(__file__).resolve().parent.parent / "data" / "specs"

# Tham số BẮT BUỘC của từng template — spec LLM sinh ra phải qua cửa này
REQUIRED = {
    "big_number": ["title", "value"],
    "versus": ["title", "left", "right"],
    "bar_chart": ["title", "items"],
    "line_chart": ["title", "xs", "ys"],
}


def validate_spec(raw: list, cfg: dict) -> list:
    """Loại cảnh hỏng, kẹp thời lượng về nhịp 2-4s, tự thêm intro đầu video."""
    pacing = cfg.get("pacing", {"scene_seconds_min": 2, "scene_seconds_max": 4})
    lo, hi = pacing["scene_seconds_min"], pacing["scene_seconds_max"]
    ok = [{"template": "intro", "seconds": 1.2, "params": {}}]
    for i, sc in enumerate(raw):
        tpl, params = sc.get("template"), sc.get("params", {})
        if tpl not in REQUIRED:
            log.warning("Cảnh %d: template lạ '%s' — bỏ", i + 1, tpl)
            continue
        missing = [k for k in REQUIRED[tpl] if k not in params]
        if missing:
            log.warning("Cảnh %d (%s): thiếu %s — bỏ", i + 1, tpl, missing)
            continue
        if tpl == "line_chart":
            if len(params["xs"]) != len(params["ys"]):
                log.warning("Cảnh %d: xs/ys lệch độ dài — bỏ", i + 1)
                continue
            xs = params["xs"]
            if any(b <= a for a, b in zip(xs, xs[1:])):
                # LLM hay dùng số tháng vắt qua năm (12,1,2...) -> trục x loạn.
                # Đổi thành chỉ số mốc 1..n cho đường vẽ đúng chiều thời gian.
                params["xs"] = list(range(1, len(xs) + 1))
                log.warning("Cảnh %d: xs không tăng dần — thay bằng mốc 1..%d", i + 1, len(xs))
        sc["seconds"] = max(lo, min(hi, float(sc.get("seconds", 3))))
        ok.append(sc)
    return ok


def fetch_script(con, script_id: int = None):
    q = ("SELECT s.id, s.idea_id, s.body, s.hooks, i.title, i.angle, i.source_url"
         " FROM scripts s JOIN ideas i ON i.id=s.idea_id")
    if script_id:
        row = con.execute(q + " WHERE s.id=?", (script_id,)).fetchone()
    else:
        row = con.execute(q + " WHERE s.status='verified' ORDER BY s.id DESC").fetchone()
    if not row:
        sys.exit("Không tìm thấy kịch bản phù hợp trong DB.")
    return dict(row)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id", nargs="?", type=int, default=None)
    ap.add_argument("--spec-only", action="store_true", help="Chỉ sinh spec, không render")
    args = ap.parse_args()

    cfg = load_config()
    con = db.connect()
    s = fetch_script(con, args.script_id)
    scenes = yaml.safe_load(s["body"])
    log.info("Kịch bản #%d: %s (%d cảnh)", s["id"], s["title"][:60], len(scenes))

    from .crew import design_scenes
    idea = {"title": s["title"], "angle": s["angle"], "source_url": s["source_url"]}
    spec = validate_spec(design_scenes(idea, scenes, cfg), cfg)

    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec_path = SPEC_DIR / f"script_{s['id']}.yaml"
    spec_path.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    total = sum(sc["seconds"] for sc in spec)
    log.info("Spec: %d cảnh, ~%.0fs -> %s", len(spec), total, spec_path)

    if args.spec_only:
        print(spec_path.read_text(encoding="utf-8"))
        return

    from .render.engine import build_video
    out = build_video(spec, f"script_{s['id']}")
    print(f"\nVideo: {out}")


if __name__ == "__main__":
    main()
