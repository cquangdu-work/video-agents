"""Bản demo: dựng lại ~31 giây đầu video #30 (thuê bao di động) bằng engine Remotion mới,
GIỮ NGUYÊN tiếng (giọng + nhạc của bản đã đăng) để Du so sánh riêng phần hình.

    python tools/demo_web30.py --spec data/specs/script_30_final.yaml --ass data/render/subs.ass \
        --video output/final_30.mp4 --out data/tmp/demo30 [--telegram]

Cách ghép cảnh ở đây viết tay cho riêng kịch bản #30 (đây là bản thử hướng đi). Nhưng mọi con số
và mốc thời gian vẫn lấy từ spec / phụ đề / bảng dữ liệu bằng code, không gõ tay.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.render import web  # noqa: E402

FLAGS = {"Việt Nam": "vn", "Hàn Quốc": "kr"}


def fmt(v: float) -> str:
    """Số kiểu Việt Nam, giống fmtVi phía Remotion."""
    a = abs(v)
    dec = 0 if a == 0 or a >= 10 else (1 if a >= 0.1 else 2)
    s = f"{v:,.{dec}f}"
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


def flat_until(series: list, y_max: float) -> int:
    """Năm cuối cùng mà MỌI chuỗi còn <= 1% đỉnh — đoạn "gần như bằng 0" của biểu đồ."""
    years = sorted({x for s in series for x in s["xs"]})
    last = years[0]
    for x in years:
        vals = [s["ys"][s["xs"].index(x)] for s in series if x in s["xs"]]
        if any(v > 0.01 * y_max for v in vals):
            break
        last = x
    return last


def build_props(spec: list, words: list, brand: dict, until_scene: int = 7) -> dict:
    spans = web.scene_spans(spec)
    until = spans[until_scene][1]
    chart = next(sc for _, _, sc in spans if sc["template"] == "line_chart")["params"]
    series = []
    for s in chart["series"]:
        vn = s["label"] == "Việt Nam"
        series.append({"label": s["label"], "color": brand["vietnam" if vn else "korea"],
                       "flag": FLAGS.get(s["label"]), "xs": s["xs"], "ys": s["ys"], "emphasis": vn})
    vn = next(s for s in series if s["emphasis"])
    vn_i = series.index(vn)
    min_x = min(min(s["xs"]) for s in series)
    max_x = max(max(s["xs"]) for s in series)
    y_max = max(max(s["ys"]) for s in series)
    fu = flat_until(series, y_max)
    last_val, last_year = vn["ys"][-1], vn["xs"][-1]

    title_src = spans[4][2]["params"]["title"]                 # "Thuê bao di động trên 100 dân năm 1960"
    title = re.sub(r"\s*(năm \d{4}|\(.*\))\s*$", "", title_src)
    per = re.search(r"trên (\d+) dân", title)
    people = int(per.group(1)) if per else 100
    unit = "thuê bao"

    (s0, e0, _), (s1, e1, _), (s2, e2, sc2), (s3, e3, sc3) = spans[0], spans[1], spans[2], spans[3]
    items_at = web.find_word(words, re.escape(fmt(last_val)), after=s1, before=e1) or s1 + 2
    work = web.find_word(words, "làm", after=s3, before=e3) or s3 + 1.2
    connect = web.find_word(words, "kết", after=s3, before=e3) or work + 1.0
    early = [s3 + 0.25 + k * max((work - s3 - 0.45) / 4, 0.12) for k in range(4)]
    orbit_items = [
        {"icon": "briefcase", "label": "Làm việc", "at": work},
        {"icon": "video", "label": "Giải trí", "at": early[0]},
        {"icon": "message", "label": "Kết nối", "at": connect},
        {"icon": "cart", "label": "Mua sắm", "at": early[1]},
        {"icon": "wallet", "label": "Thanh toán", "at": early[2]},
        {"icon": "pin", "label": "Đi lại", "at": early[3]},
    ]

    h_start, h_end = spans[4][0], until
    beats = {"startLine": spans[5][0], "flat": spans[6][0], "rise": spans[7][0]}
    beats["callout"] = web.find_word(words, re.escape(fmt(last_val)), after=beats["rise"], before=until) \
        or beats["rise"] + 1.5
    at_min = [s["ys"][s["xs"].index(min_x)] for s in series if min_x in s["xs"]]

    scenes = [
        {"kind": "intro", "start": s0, "end": e0},
        {"kind": "isotype", "start": s1, "end": e1, "flag": "vn", "caption": f"Việt Nam · {last_year}",
         "people": people, "peopleLabel": "người", "items": round(last_val), "itemsLabel": unit,
         "itemsAt": items_at},
        {"kind": "network", "start": s2, "end": e2, "title": sc2["params"]["text"]},
        {"kind": "orbit", "start": s3, "end": e3, "title": sc3["params"]["text"], "items": orbit_items},
        {"kind": "heroline", "start": h_start, "end": h_end, "title": title, "series": series,
         "minX": min_x, "maxX": max_x, "yMax": y_max, "flatUntil": fu, "beats": beats,
         "startLabel": f"VẠCH XUẤT PHÁT · {min_x}",
         "zeroLabel": f"{fmt(max(at_min))} {unit}" if at_min else "",
         "gapLabel": f"{fu - min_x} năm gần như bằng 0",
         "reference": {"y": people, "label": f"{people} = mỗi người 1 {unit}"} if per else None,
         "callout": {"series": vn_i, "value": fmt(last_val), "label": f"{unit} / {people} dân · {last_year}"}},
    ]
    sfx = [{"name": "whoosh", "at": max(t - 0.15, 0), "volume": 0.35} for t in (s1, s2, s3, h_start)]
    sfx += [{"name": "pop", "at": items_at, "volume": 0.4}, {"name": "pop", "at": items_at + 0.6, "volume": 0.3}]
    sfx += [{"name": "pop", "at": it["at"], "volume": 0.3} for it in orbit_items]
    sfx += [{"name": "tick", "at": beats["startLine"], "volume": 0.4},
            {"name": "rise", "at": beats["rise"], "volume": 0.35},
            {"name": "thump", "at": beats["callout"], "volume": 0.55}]
    return {"brand": brand, "duration": until, "scenes": scenes,
            "words": [w for w in words if w["s"] < until], "source": spans[1][2]["params"].get("source", ""),
            "sfx": sfx}


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--ass", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True, help="bản đã phát hành, lấy tiếng + làm bản so sánh")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()

    spec = yaml.safe_load(a.spec.read_text(encoding="utf-8"))
    props = build_props(spec, web.words_from_ass(a.ass), web.brand_props())
    until = props["duration"]
    a.out.mkdir(parents=True, exist_ok=True)
    raw = web.render(props, a.out / "web_raw.mp4", a.concurrency)

    new, old, both = a.out / "demo30_moi.mp4", a.out / "demo30_cu.mp4", a.out / "demo30_so_sanh.mp4"
    # tiếng của bản đã đăng (giọng + nhạc) + hiệu ứng âm thanh của bản mới
    ff("-i", raw, "-i", a.video, "-filter_complex",
       f"[1:a]atrim=0:{until},asetpts=N/SR/TB,afade=t=out:st={until - 0.4:.2f}:d=0.4[v];"
       f"[v][0:a]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]",
       "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", new)
    ff("-i", a.video, "-t", f"{until}", "-c:v", "libx264", "-crf", "18", "-c:a", "aac",
       "-af", f"afade=t=out:st={until - 0.4:.2f}:d=0.4", old)
    ff("-i", old, "-i", new, "-filter_complex",
       "[0:v]scale=540:960[l];[1:v]scale=540:960[r];[l][r]hstack=inputs=2[v]",
       "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-crf", "20", "-c:a", "aac", both)
    print(new, both, sep="\n")

    if a.telegram:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from src import telegram_bot as tg
        tg.send_video(new, "🧪 DEMO hình mới (Remotion) — 31 giây đầu video #7 (thuê bao di động). "
                           "Cùng giọng + nhạc với bản đã đăng, chỉ thay phần hình. Không đăng đi đâu.")
        tg.send_video(both, "So sánh: TRÁI = bản cũ (Manim), PHẢI = bản mới (Remotion).")


if __name__ == "__main__":
    main()
