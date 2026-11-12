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
from .utils import spec_values

log = logging.getLogger("produce")

SPEC_DIR = Path(__file__).resolve().parent.parent / "data" / "specs"

# Tham số BẮT BUỘC của từng template — spec LLM sinh ra phải qua cửa này
REQUIRED = {
    "statement": ["text"],
    "big_number": ["title", "value"],
    "versus": ["title", "left", "right"],
    "bar_chart": ["title", "items"],
    "line_chart": ["title", "xs"],          # + "ys" (một đường) hoặc "series" (nhiều đường)
    "percent": ["title", "value"],
    "bar_race": ["title", "years", "items"],
    "map": ["title", "items"],
}
STATEMENT_STYLES = 3      # số kiểu bố cục của cảnh chữ (src/render/templates.py)


def _decimals_for(value) -> int:
    """Số chữ số thập phân cần hiện để KHÔNG làm tròn mất số liệu: 38.4 -> 1, 0.25 -> 2."""
    try:
        frac = f"{float(value):.6f}".rstrip("0").split(".")[1]
    except (TypeError, ValueError, IndexError):
        return 0
    return min(len(frac), 2)


def validate_spec(raw: list, cfg: dict) -> list:
    """Loại cảnh hỏng, kẹp thời lượng về nhịp 2-4s, tự thêm intro đầu video.
    Tự sửa những thứ LLM hay quên: số lẻ thiếu 'decimals' (38.4 hiện thành 38),
    'percent' ngoài 0-100, và xoay vòng kiểu bố cục của các cảnh chữ."""
    pacing = cfg.get("pacing", {"scene_seconds_min": 2, "scene_seconds_max": 4})
    lo, hi = pacing["scene_seconds_min"], pacing["scene_seconds_max"]
    ok = [{"template": "intro", "seconds": 1.2, "params": {}}]
    statements = 0
    for i, sc in enumerate(raw):
        tpl, params = sc.get("template"), sc.get("params", {})
        if tpl not in REQUIRED:
            log.warning("Cảnh %d: template lạ '%s' — bỏ", i + 1, tpl)
            continue
        missing = [k for k in REQUIRED[tpl] if k not in params]
        if missing:
            log.warning("Cảnh %d (%s): thiếu %s — bỏ", i + 1, tpl, missing)
            continue
        if tpl == "percent":
            try:
                in_range = 0 <= float(params["value"]) <= 100
            except (TypeError, ValueError):
                in_range = False
            if not in_range:      # "tăng 250%" không vẽ được bằng vòng tròn -> số lớn
                log.warning("Cảnh %d: percent=%s ngoài 0-100 — đổi sang big_number",
                            i + 1, params["value"])
                tpl = sc["template"] = "big_number"
                params.setdefault("suffix", "%")
        if tpl in ("big_number", "percent", "versus", "line_chart", "bar_chart", "bar_race", "map"):
            values = spec_values(params)
            need = max((_decimals_for(v) for v in values), default=0)
            if need > int(params.get("decimals") or 0):
                params["decimals"] = need       # tỷ suất sinh 0,75 từng hiện thành "1"
        if tpl == "statement":
            # xoay vòng 3 kiểu bố cục để hai cảnh chữ liền nhau không giống hệt nhau
            params["style"] = statements % STATEMENT_STYLES
            params["n"] = statements + 1
            statements += 1
        if tpl == "map":
            from .render.geo import code_of
            good = []
            for it in params["items"]:
                try:
                    if isinstance(it, dict) and code_of(it.get("label")):
                        good.append({"label": it["label"], "value": float(it["value"])})
                except (KeyError, TypeError, ValueError):
                    pass
            if len(good) < 3:
                log.warning("Cảnh %d: bản đồ cần >= 3 nước châu Á có số — bỏ", i + 1)
                continue
            params["items"] = good
        if tpl == "bar_race":
            years = params["years"]
            good = [it for it in params["items"] if isinstance(it, dict) and it.get("label")
                    and isinstance(it.get("values"), list) and len(it["values"]) == len(years)]
            if len(good) < 3 or len(years) < 2 or any(b <= a for a, b in zip(years, years[1:])):
                log.warning("Cảnh %d: cuộc đua cần >= 3 nước đủ số liệu và năm tăng dần — bỏ", i + 1)
                continue
            params["items"] = good[:10]                     # khung dọc vừa tối đa 10 thanh
        if tpl == "line_chart":
            xs = params["xs"]
            if params.get("series"):
                # Đường nào thiếu/thừa điểm so với trục năm (của chính nó, hoặc trục chung)
                # thì bỏ đường đó, không bỏ cả cảnh
                good = [s for s in params["series"] if isinstance(s, dict)
                        and isinstance(s.get("ys"), list)
                        and len(s["ys"]) == len(s.get("xs") or xs) >= 2]
                if len(good) < len(params["series"]):
                    log.warning("Cảnh %d: bỏ %d đường lệch độ dài với xs", i + 1,
                                len(params["series"]) - len(good))
                if not good:
                    continue
                params["series"] = good
                params.pop("ys", None)
            elif not isinstance(params.get("ys"), list) or len(xs) != len(params["ys"]):
                log.warning("Cảnh %d: xs/ys lệch độ dài — bỏ", i + 1)
                continue
            if len(xs) < 2 and not params.get("series"):
                log.warning("Cảnh %d: biểu đồ đường cần ít nhất 2 mốc — bỏ", i + 1)
                continue
            if any(any(b <= a for a, b in zip(s["xs"], s["xs"][1:]))
                   for s in params.get("series") or [] if s.get("xs")):
                log.warning("Cảnh %d: trục năm riêng của một đường không tăng dần — bỏ", i + 1)
                continue
            if any(b <= a for a, b in zip(xs, xs[1:])):
                # LLM hay dùng số tháng vắt qua năm (12,1,2...) -> trục x loạn.
                # Đổi thành chỉ số mốc 1..n cho đường vẽ đúng chiều thời gian.
                params["xs"] = list(range(1, len(xs) + 1))
                log.warning("Cảnh %d: xs không tăng dần — thay bằng mốc 1..%d", i + 1, len(xs))
        sc["seconds"] = max(lo, min(hi, float(sc.get("seconds", 3))))
        ok.append(sc)
    return ok


def fetch_script(con, script_id: int = None):
    q = ("SELECT s.id, s.idea_id, s.body, s.hooks, i.title, i.angle, i.source_url,"
         " i.summary, i.source_name FROM scripts s JOIN ideas i ON i.id=s.idea_id")
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
    # summary: dữ liệu nguồn của ý tưởng (bảng số World Bank, tóm tắt bài báo) — agent Sản
    # xuất được lấy số ở đó để vẽ biểu đồ
    idea = {"title": s["title"], "angle": s["angle"], "source_url": s["source_url"],
            "summary": s["summary"], "source_name": s["source_name"]}
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
