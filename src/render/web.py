"""Cầu nối Python -> engine dựng hình Remotion (thư mục render-web/).

Python vẫn làm chủ mọi thứ quan trọng: số liệu (lấy từ bảng gốc), mốc thời gian (từ giọng
đọc thật + Whisper), lời phụ đề (từ kịch bản). File này chỉ đóng gói chúng thành một JSON
"props" rồi gọi `npx remotion render`. Phía Remotion không tự sinh con số nào.

    words = words_from_ass(Path("data/render/subs.ass"))
    render(props, Path("out.mp4"))
"""
import json
import logging
import os
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


def node_env() -> tuple:
    """(lệnh npx, biến môi trường) để chạy Remotion.

    REMOTION_NODE_DIR (trong .env, ví dụ ~/.local/node24/bin) = dùng bộ Node RIÊNG của dự án, đặt
    lên đầu PATH. Lý do (19/11/2026): Node 20 hệ thống trên VM đã hết hạn hỗ trợ từ 4/2026, nhưng
    máy còn chạy dịch vụ khác của Du — nâng Node hệ thống có thể làm hỏng dịch vụ đó. Không đặt
    biến (hoặc thư mục không tồn tại) thì dùng Node trên PATH như trước."""
    env = dict(os.environ)
    node_dir = Path(os.getenv("REMOTION_NODE_DIR", "") or "~/__none__").expanduser()
    if os.getenv("REMOTION_NODE_DIR") and node_dir.is_dir():
        env["PATH"] = str(node_dir) + os.pathsep + env.get("PATH", "")
    path = env.get("PATH")
    npx = shutil.which("npx", path=path) or shutil.which("npx.cmd", path=path) or "npx"
    return npx, env


def render(props: dict, out: Path, concurrency: int = 3, crf: int = 23, composition: str = "Story") -> Path:
    """Ghi props ra JSON rồi gọi Remotion. Lần đầu trên máy mới cần `npm ci` trong render-web/.
    crf 23: video 72 giây ở mức mặc định (18) nặng 36 MB — sát trần 50 MB của bot Telegram."""
    out.parent.mkdir(parents=True, exist_ok=True)
    props_path = out.with_suffix(".props.json")
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx, env = node_env()
    cmd = [npx, "remotion", "render", "src/index.ts", composition, str(out.resolve()),
           f"--props={props_path.resolve()}", f"--concurrency={concurrency}", f"--crf={crf}",
           "--enforce-audio-track", "--log=error"]
    log.info("Remotion render -> %s", out.name)
    subprocess.run(cmd, cwd=WEB, check=True, env=env)
    return out


# =====================================================================================
# Dịch SPEC (đúng khuôn engine Manim, src/produce.py) -> props của engine Remotion.
# Không đổi gì phía Biên kịch/Sản xuất: cùng spec, chỉ đổi cách vẽ.
# =====================================================================================

WEB_KINDS = {"intro", "statement", "big_number", "versus", "bar_chart", "percent", "line_chart",
             "map", "bar_race"}
CLIPS = WEB / "public" / "clips"
FLAGS = WEB / "public" / "flags"
FLAG_SRC = WEB / "node_modules" / "flag-icons" / "flags" / "4x3"
ISO2_PATH = ROOT / "assets" / "geo" / "iso3_to_iso2.json"
# Không cắm cờ riêng: đi theo cách gọi tên/ranh giới của Việt Nam trong src/render/geo.py
# (Đài Loan, Hồng Kông, Ma Cao ghi "(Trung Quốc)"; Kosovo, Tây Sahara không công nhận là nước).
NO_FLAG = {"TWN", "HKG", "MAC", "XKX", "KOS", "ESH"}

# (mẫu tìm trong câu viết thường, tên icon ở render-web/src/components/Icons.tsx).
# Thứ tự = ưu tiên: cụm cụ thể đứng trước cụm chung ("điện mặt trời" trước "điện").
ICON_KEYWORDS = [
    (r"điện mặt trời|năng lượng mặt trời", "sun"),
    (r"điện thoại|di động|thuê bao|smartphone", "smartphone"),
    (r"internet|mạng xã hội|trực tuyến|online|wifi", "wifi"),
    (r"xăng|dầu mỏ|nhiên liệu|than đá", "fuel"),
    (r"điện năng|tiêu thụ điện|\bđiện\b|năng lượng|kwh", "zap"),
    (r"khí thải|co2|ô nhiễm|nhà máy|công nghiệp|sản xuất|chế tạo", "factory"),
    (r"rừng|cây xanh|che phủ", "trees"),
    (r"nông nghiệp|lúa|gạo|lương thực|nông dân", "wheat"),
    (r"nhiệt độ|nắng nóng|khí hậu|ấm lên", "thermometer"),
    (r"nước sạch|nguồn nước", "droplets"),
    (r"giáo dục|học sinh|sinh viên|trường học|đại học|biết chữ", "graduation-cap"),
    (r"bệnh viện|bác sĩ|y tế", "hospital"),
    (r"sức khỏe|sức khoẻ|tuổi thọ|bệnh|tử vong", "heart-pulse"),
    (r"mức sinh|sinh con|trẻ em|em bé|sơ sinh", "baby"),
    (r"thành thị|đô thị|thành phố", "building"),
    (r"nhà ở|căn hộ|bất động sản", "house"),
    (r"xuất khẩu|nhập khẩu|thương mại|hàng hóa|hàng hoá|cảng biển", "ship"),
    (r"\bfdi\b|đầu tư|nguồn vốn|dòng vốn", "landmark"),
    (r"ngân hàng|tài chính|thanh toán", "wallet"),
    (r"du lịch|máy bay|hàng không|sân bay", "plane"),
    (r"ô tô|xe máy|giao thông|xe hơi", "car"),
    (r"đường sắt|tàu hỏa|tàu hoả|metro", "train"),
    (r"công nghệ|máy tính|\bchip\b|bán dẫn", "cpu"),
    (r"trí tuệ nhân tạo|robot|chatgpt", "bot"),
    (r"mua sắm|bán lẻ|cửa hàng|tiêu dùng", "shopping-cart"),
    (r"dân số|người dân|cư dân|lao động|việc làm", "users"),
    (r"hạ tầng|mạng lưới", "network"),
    (r"bùng nổ|cất cánh|bứt phá|vươn lên", "rocket"),
    (r"\bgdp\b|kinh tế|tăng trưởng|thu nhập|giàu", "trending-up"),
    (r"giảm mạnh|sụt giảm|lao dốc|tụt", "trending-down"),
    (r"tiền lương|\busd\b|đô la|chi tiêu|giá cả", "coins"),
    (r"thế giới|toàn cầu|quốc tế", "globe"),
    (r"khoảng cách|chênh lệch|so với|gấp", "arrow-left-right"),
    (r"thập kỷ|thời gian|kéo dài|năm qua", "hourglass"),
    (r"mục tiêu|cột mốc", "target"),
    (r"ý tưởng|phát minh|sáng tạo", "lightbulb"),
]
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def pick_icon(*texts):
    """Icon minh hoạ cho một câu, chọn theo từ khoá (không có từ khoá nào thì không icon)."""
    raw = " ".join(str(t or "") for t in texts)
    if re.search(r"\bAI\b", raw):              # "AI" viết hoa; "ai" thường là đại từ "ai"
        return "bot"
    low = raw.lower()
    for rx, icon in ICON_KEYWORDS:
        if re.search(rx, low):
            return icon
    return None


def _clean_label(label) -> tuple:
    """'Việt Nam (2024)' -> ('Việt Nam', 2024); 'Hàn Quốc' -> ('Hàn Quốc', None)."""
    s = " ".join(str(label or "").split())
    m = re.search(r"\s*\((\d{4})\)\s*$", s)
    return (s[:m.start()].strip(), int(m.group(1))) if m else (s, None)


_iso2 = None


def flag_of(label):
    """Mã cờ (ISO 2 chữ, viết thường) của một nhãn nước; chép file cờ vào public/flags nếu thiếu."""
    global _iso2
    from .geo import code_of
    if _iso2 is None:
        try:
            _iso2 = json.loads(ISO2_PATH.read_text(encoding="utf-8"))
        except OSError:
            _iso2 = {}
    name = _clean_label(label)[0]
    code = code_of(name) if name else None
    iso = _iso2.get(code) if code and code not in NO_FLAG else None
    if not iso:
        return None
    dst = FLAGS / f"{iso}.svg"
    if not dst.exists():
        src = FLAG_SRC / f"{iso}.svg"
        if not src.exists():
            return None
        FLAGS.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
    return iso


def _color(label, colors: dict, fallback: str) -> str:
    from .templates import country_color_key
    key = country_color_key(_clean_label(label)[0])
    return colors[key] if key else colors[fallback]


def _valued(side: dict, decimals: int, colors: dict, fallback: str) -> dict:
    from .templates import label_decimals
    v = float(side["value"])
    return {"label": str(side.get("label", "")), "value": v, "dec": label_decimals(v, decimals),
            "color": _color(side.get("label"), colors, fallback), "flag": flag_of(side.get("label"))}


def caption_words(timed: list) -> list:
    """[(từ, bắt đầu, kết thúc)] -> [{"w","s","e","c"}], chia cụm ĐÚNG như phụ đề .ass cũ."""
    from ..audio.subtitles import chunk_words
    out = []
    for c, chunk in enumerate(chunk_words(timed)):
        for w, s, e in chunk:
            out.append({"w": w, "s": round(float(s), 3), "e": round(float(e), 3), "c": c})
    return out


def _significant(text) -> set:
    stop = {"của", "trên", "người", "năm", "và", "với", "các", "những", "mỗi", "dân", "lần"}
    return {w for w in re.findall(r"\w+", str(text or "").lower()) if len(w) >= 3 and w not in stop}


def build_world(spec: list, colors: dict):
    """Biểu đồ chính của video = cảnh line_chart ĐẦU TIÊN (số do crew.fill_series_from_data chép
    từ bảng gốc). Không có line_chart thì video không có biểu đồ chính."""
    from .templates import chart_series
    first = next((sc for sc in spec if sc.get("template") == "line_chart"), None)
    if not first:
        return None
    p = first.get("params") or {}
    lines = chart_series(p, colors)
    if not lines or not all(len(xs) == len(ys) and len(xs) >= 2 for _, xs, ys, _ in lines):
        return None
    labels = [lbl for lbl, *_ in lines]
    emph = next((i for i, l in enumerate(labels) if l.strip().lower() == "việt nam"), 0)
    dec = int(p.get("decimals", 2) or 0)
    series = [{"label": lbl or str(p.get("title", "")), "color": color, "flag": flag_of(lbl) if lbl else None,
               "xs": [int(x) if float(x).is_integer() else float(x) for x in xs],
               "ys": [float(y) for y in ys], "emphasis": i == emph, "dec": dec}
              for i, (lbl, xs, ys, color) in enumerate(lines)]
    y_max = max(max(s["ys"]) for s in series)
    if y_max <= 0:
        return None
    unit = str(p.get("unit") or "")
    world = {"series": series, "title": str(p.get("title", "")), "minX": min(s["xs"][0] for s in series),
             "maxX": max(s["xs"][-1] for s in series), "yMax": y_max, "unit": unit}
    per = re.search(r"(?:/|trên)\s*100\s*(?:dân|người)", unit + " " + str(p.get("title", "")))
    noun = re.split(r"\s*(?:/|trên)\s*100", unit)[0].strip() if per else ""
    if per and noun and y_max > 105:
        world["reference"] = {"y": 100, "label": f"100 = mỗi người 1 {noun}"}
    return world


def _same_series(p: dict, world: dict, colors: dict) -> bool:
    from .templates import chart_series
    lines = chart_series(p, colors)
    return [(lbl or str(p.get("title", "")), [float(y) for y in ys]) for lbl, _, ys, _ in lines] == \
        [(s["label"], s["ys"]) for s in world["series"]]


def _match_points(world: dict, label, value: float, decimals: int, hints: set) -> list:
    """Điểm số liệu THẬT (chuỗi, năm) có giá trị bằng `value` (làm tròn như trên hình).
    Chỉ trả về khi xác định được DUY NHẤT một điểm — không chắc thì thôi, không đoán."""
    name, year = _clean_label(label)
    cands = [i for i, s in enumerate(world["series"]) if name and s["label"].lower() == name.lower()]
    if not cands and not name:
        cands = list(range(len(world["series"])))
    pts = [(i, x) for i in cands for x, y in zip(world["series"][i]["xs"], world["series"][i]["ys"])
           if round(y, decimals) == round(float(value), decimals)]
    if year:
        pts = [p for p in pts if p[1] == year]
    elif len(pts) > 1 and hints:
        pts = [p for p in pts if p[1] in hints] or pts
    return pts if len(pts) == 1 else []


def _nice_ticks(y_max: float) -> list:
    """Mọi vạch chia trục y mà ChartWorld có thể vẽ (để Kiểm định không coi là số lạ)."""
    out = set()
    for step in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        n = int(y_max * 1.25 / step)
        if 1 <= n <= 60:
            out |= {round(k * step, 6) for k in range(n + 1)}
    return sorted(out)


def build_story(spec: list, timed_words: list, script_id, render_clip=None) -> dict:
    """Spec đã có thời lượng thật + từ có mốc thời gian -> props cho Remotion.

    render_clip(scene, index) -> Path: dựng một cảnh bằng Manim (bản đồ, cuộc đua...) để lồng vào;
    không truyền thì cảnh chưa có bản Remotion sẽ báo lỗi (assemble lùi về Manim cả video).
    Mỗi cảnh trong spec được gắn thêm "shown": các con số engine này có thể hiện (Kiểm định đọc)."""
    from .base import fmt_num
    from .templates import highlights, label_decimals
    colors = brand()["colors"]
    words = caption_words(timed_words)
    world = build_world(spec, colors)

    def numbers_of(w) -> list:
        """Mọi con số một biểu đồ có thể hiện (số liệu, năm, vạch chia) — cho Kiểm định."""
        if not w:
            return []
        out = []
        for s in w["series"]:
            out += s["xs"] + [round(y, s["dec"]) for y in s["ys"]]
        return out + _nice_ticks(w["yMax"]) + ([100] if w.get("reference") else [])

    def callout_for(w, start, end):
        """Con số chốt: giá trị cuối của một đường mà lời đọc cảnh này nói ra -> chú thích lớn
        đúng mốc của từ đó (chuỗi nhấn mạnh — Việt Nam — được xét trước)."""
        for k in sorted(range(len(w["series"])), key=lambda k: not w["series"][k]["emphasis"]):
            s = w["series"][k]
            last = fmt_num(s["ys"][-1], label_decimals(s["ys"][-1], s["dec"]))
            at = find_word(words, re.escape(last), after=start, before=end)
            if at is not None:
                add_sfx("thump", at, 0.45)
                return {"s": k, "value": last, "at": at, "label": f"{w['unit']} · {s['xs'][-1]}".strip(" ·")}
        return None

    world_numbers = numbers_of(world)
    scenes, sfx, t = [], [], 0.0
    drawn = world["minX"] if world else 0
    clip_dir = CLIPS / str(script_id)
    if clip_dir.exists():
        shutil.rmtree(clip_dir)

    def add_sfx(name, at, vol):
        if all(abs(at - x["at"]) > 0.45 for x in sfx):     # không dồn tiếng hiệu ứng sát nhau
            sfx.append({"name": name, "at": round(max(at, 0), 3), "volume": vol})

    prev_family, bar_charts = None, 0
    for i, sc in enumerate(spec):
        tpl, p = sc.get("template"), dict(sc.get("params") or {})
        start, end = round(t, 3), round(t + float(sc["seconds"]), 3)
        t, dur = end, end - start
        voice = str(sc.get("voice") or "")
        hints = {int(y) for y in _YEAR.findall(" ".join([str(p.get("title", "")), voice]))}
        dec = int(p.get("decimals", 0) or 0)
        kind = tpl if tpl in WEB_KINDS else "clip"
        out = {"start": start, "end": end, "source": str(p.get("source") or ""), "kind": kind}
        extra_shown = []
        if tpl == "line_chart" and (not world or not _same_series(p, world, colors)):
            # line_chart thứ hai mang số liệu khác biểu đồ chính: biểu đồ riêng chỉ trong cảnh này;
            # số liệu hỏng (không dựng được) thì mới lùi về Manim
            solo = build_world([sc], colors)
            if solo:
                kind = out["kind"] = "line_solo"
                chart = {"mode": "full", "drawTo": solo["maxX"]}
                co = callout_for(solo, start, end)
                if co:
                    chart["callout"] = co
                out.update(title=str(p.get("title", "")), world=solo, chart=chart)
                extra_shown = numbers_of(solo)
                add_sfx("rise", start + 0.08 * dur, 0.28)
            else:
                kind = out["kind"] = "clip"
        if kind in ("map", "bar_race"):
            from .web_map import map_props, race_props
            try:
                if kind == "map":
                    out.update(map_props(p, colors))
                    extra_shown = out.pop("ranksShown", [])
                    add_sfx("rise", start + 0.35, 0.22)
                else:
                    out.update(race_props(p, colors, flag_of))
                    add_sfx("rise", start + 0.5, 0.22)
            except Exception as exc:          # số liệu lạ: dựng cảnh đó bằng Manim như trước
                log.warning("Cảnh %d (%s) không dựng được bằng Remotion (%s) — dùng Manim", i + 1, tpl, exc)
                kind = out["kind"] = "clip"

        if kind == "statement":
            text = str(p.get("text") or voice)
            out.update(text=text, style=int(p.get("style") or 0), n=p.get("n"),
                       icon=pick_icon(text, voice), highlights=highlights(text))
            if world and drawn > world["minX"]:
                # Biểu đồ chính đã vẽ: GIỮ nó ở nửa dưới, chữ gọn ở nửa trên (19/11/2026 — cảnh chữ nền
                # trống chiếm 1/3 thời lượng và là chỗ người xem bỏ đi, số đo video #6, #7)
                out.update(chart={"mode": "panel", "drawTo": drawn}, compact=True, icon=None)
            if out["icon"]:
                add_sfx("pop", start + 0.05, 0.28)
        elif kind == "big_number":
            v = float(p["value"])
            title, suffix = str(p.get("title", "")), str(p.get("suffix") or "")
            out.update(title=title, value=v, dec=label_decimals(v, dec), suffix=suffix,
                       color=colors.get(p.get("color", "accent"), colors["accent"]))
            named = [s for s in (world or {}).get("series", []) if s["label"].lower() in title.lower()]
            if len(named) == 1:
                out["flag"] = named[0]["flag"]
            # chỉ gắn vào biểu đồ chính khi đơn vị/tiêu đề cùng chủ đề (tránh "6 năm" trùng số 6)
            if world and _significant(suffix + " " + title) & _significant(world["unit"] + " " + world["title"]):
                pts = _match_points(world, named[0]["label"] if len(named) == 1 else "", v, out["dec"], hints)
                if pts:
                    drawn = max(drawn, pts[0][1])
                    out["chart"] = {"mode": "panel", "drawTo": drawn, "focus": [{"s": pts[0][0], "x": pts[0][1]}]}
            if "chart" not in out:
                low = (title + " " + suffix).lower()
                share = "%" in suffix and 1 <= v <= 100 and re.search(
                    r"dân số|người|lao động|hộ gia đình|trẻ em|phụ nữ|học sinh", low)
                per100 = re.search(r"(?:/|trên)\s*100\s*(?:dân|người)", low) and 1 <= v <= 160
                icon = pick_icon(title, suffix)
                if share:
                    out["isotype"] = {"mode": "share", "count": round(v), "noun": "người"}
                elif per100 and icon:
                    out["isotype"] = {"mode": "per100", "count": round(v), "icon": icon, "noun": suffix}
            add_sfx("tick", start + 0.05 * dur, 0.3)
        elif kind == "versus":
            left, right = _valued(p["left"], dec, colors, "accent"), _valued(p["right"], dec, colors, "text")
            out.update(title=str(p.get("title", "")), left=left, right=right, suffix=str(p.get("suffix") or ""))
            if world:
                pl = _match_points(world, left["label"], left["value"], left["dec"], hints)
                pr = _match_points(world, right["label"], right["value"], right["dec"], hints)
                if pl and pr:
                    drawn = max(drawn, pl[0][1], pr[0][1])
                    out["chart"] = {"mode": "panel", "drawTo": drawn,
                                    "focus": [{"s": pl[0][0], "x": pl[0][1]}, {"s": pr[0][0], "x": pr[0][1]}]}
            add_sfx("tick", start + 0.05 * dur, 0.3)
        elif kind == "bar_chart":
            items = sorted(p.get("items") or [], key=lambda it: -float(it["value"]))[:6]
            # xen kẽ thanh ngang / cột đứng (video #18 có 6 cảnh xếp hạng cùng một khuôn)
            out.update(title=str(p.get("title", "")), unit=str(p.get("unit") or ""), style=bar_charts % 2,
                       items=[_valued(it, dec, colors, "accent" if k == 0 else "muted") for k, it in enumerate(items)])
            bar_charts += 1
            add_sfx("tick", start + 0.05 * dur, 0.3)
        elif kind == "percent":
            v = max(0.0, min(float(p["value"]), 100.0))
            out.update(title=str(p.get("title", "")), value=v, dec=label_decimals(v, dec),
                       label=str(p.get("label") or ""))
            add_sfx("tick", start + 0.05 * dur, 0.3)
        elif kind == "line_chart":
            to = max(s["xs"][-1] for s in world["series"])
            new_draw = to > drawn
            drawn = max(drawn, to)
            state = {"mode": "full", "drawTo": drawn}
            co = callout_for(world, start, end)
            if co:
                state["callout"] = co
            out.update(title=str(p.get("title", "")), chart=state)
            if new_draw:
                add_sfx("rise", start + 0.08 * dur, 0.28)
        elif kind == "clip":
            out = {k: v for k, v in out.items() if k in ("start", "end", "source", "kind")}
            if render_clip is None:
                raise ValueError(f"cảnh {i + 1}: template '{tpl}' chưa có bản Remotion")
            clip_dir.mkdir(parents=True, exist_ok=True)
            dst = clip_dir / f"scene_{i:02d}.mp4"
            shutil.copy(render_clip(sc, i), dst)
            out["src"] = f"clips/{script_id}/{dst.name}"

        family = "text" if kind in ("statement", "intro") else kind
        if prev_family and family != prev_family:
            add_sfx("whoosh", start - 0.15, 0.25)
        prev_family = family
        if voice.strip() and not any(s.get("hook") for s in scenes):
            out["hook"] = True          # cảnh mở đầu: chữ hiện đủ ngay khung đầu (render-web HookContext)
        scenes.append(out)
        sc["shown"] = world_numbers + extra_shown

    sources = [s["source"] for s in scenes if s.get("source")]
    return {"brand": brand_props(), "duration": round(t, 3), "scenes": scenes, "words": words,
            "source": max(set(sources), key=sources.count) if sources else "", "sfx": sfx, "world": world}
