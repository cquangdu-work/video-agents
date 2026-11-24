"""Xưởng dựng TỰ HỌC (19/11/2026): agent không chỉ học viết kịch bản (src/learning.py) mà học cả CÁCH
DỰNG video. Cùng nguyên tắc: học chỉ đổi THAM SỐ trong khung an toàn đã định sẵn và lời dặn agent Sản
xuất — không đổi bộ nhận diện kênh (màu, font, logo), không nới cổng Kiểm định nào.

1. THỬ NGHIỆM CÓ KIỂM SOÁT — mỗi video mới được gán một tổ hợp "núm vặn" (tốc độ đọc, mức nhạc nền,
   nhịp đổi cảnh, cỡ phụ đề), mỗi núm 3 mức quanh tâm khung. Chủ nhật agent Phân tích so % thời lượng
   được xem giữa các mức; lần gán sau dùng Thompson sampling: mức tốt được chọn nhiều hơn, mức ít dữ
   liệu vẫn được thử. Gán ngẫu nhiên (không theo nội dung) nên so sánh công bằng giữa các mức.
2. TỰ PHÁT TRIỂN — mức bên cạnh tâm khung thắng rõ (≥ 4 video, hơn ≥ 0,3 độ lệch chuẩn) thì khung dời
   một nấc về phía đó; không bao giờ ra khỏi giới hạn cứng.
3. HỌC TỪ NGƯỜI XEM THEO LOẠI CẢNH — loại cảnh nào làm người xem rời đi nhanh / giữ chân tốt, cảnh mở
   đầu dạng nào giữ người xem qua vài giây đầu -> lời dặn cho agent Sản xuất (production_block).
4. HỌC TỪ DU — /nhac nho, /giong nhanh, /nhip cham, /chu to… dời khung một nấc theo ý Du, và việc tự
   dời khung KHÔNG BAO GIỜ đi ngược lại phía Du đã chê. /kieu: xem đang thử gì; /kieu tat|bat.

(Lỗi dựng — Kiểm định trượt, Remotion lùi về Manim — ghi vào bộ nhớ chung learning_events.)

    python -m src.style              # các núm vặn, khung đang thử, mức nào đang dẫn
    python -m src.style assign 59    # gán (hoặc xem) phong cách của kịch bản #59 — để chạy thử
"""
import json
import logging
import math
import random
import sys
from datetime import datetime, timezone

from .analysis import learned as store

log = logging.getLogger("style")

# Khung AN TOÀN của từng núm: tâm mặc định, bước, giới hạn cứng. Tâm mặc định đặt sao cho mức đang dùng
# trước 19/11 (đọc ×1,00, nhạc 0 dB, tối đa 4 giây/hình, phụ đề 80 px) vẫn là một mức được thử, còn hai
# mức kia nghiêng về hướng số liệu giữ chân 19/11 gợi ý (đọc nhanh hơn, đổi cảnh nhanh hơn, chữ to hơn).
KNOBS = {
    "tempo": {"label": "Tốc độ đọc", "center": 1.05, "step": 0.05, "lo": 1.0, "hi": 1.12},
    "music": {"label": "Nhạc nền", "center": 0.0, "step": 3.0, "lo": -9.0, "hi": 6.0},
    # Du xin 20/11 "thử video ngắn hơn và đổi hình nhanh hơn" (kênh lớn cùng ngách: video đột biến ~31 giây,
    # đổi hình ~1,4 giây/lần): nhịp từ 3/3,5/4 xuống 2/2,5/3 giây mỗi hình (sàn 2 giây = assemble.MIN_SCENE)
    "pace": {"label": "Nhịp đổi cảnh", "center": 2.5, "step": 0.5, "lo": 2.0, "hi": 5.0},
    "captions": {"label": "Cỡ phụ đề", "center": 88.0, "step": 8.0, "lo": 72.0, "hi": 96.0},
    # độ dài TỐI ĐA của video (giây); Biên kịch viết cho khoảng 0,75×..1× mức này. Gán lúc viết kịch bản (main)
    "length": {"label": "Độ dài video", "center": 40.0, "step": 10.0, "lo": 30.0, "hi": 60.0},
    # THẺ MỞ ĐẦU (24/11/2026, Du duyệt đề xuất "giây đầu tiên"): số giây thẻ phát hiện (con số chính + câu mở đầu) phủ
    # khung đầu video trước khi mở ra cảnh — 0 = không thẻ. Đo 24/11: chỉ 37-62% lượt xem qua được vài giây đầu.
    "opening": {"label": "Thẻ mở đầu", "center": 1.2, "step": 1.2, "lo": 0.0, "hi": 2.4},
}
METRIC = "avg_view_pct"     # mục tiêu của kênh là tỷ lệ xem hết -> % thời lượng được xem
SHRINK = 3.0                # mỗi mức như có sẵn 3 video "trung bình": ít video thì không kết luận mạnh
MIN_SAMPLES = 3             # dưới số video này không cập nhật gì
SHIFT_MIN_N = 4             # mức mới phải có ít nhất chừng này video mới được dời khung về nó
SHIFT_MARGIN = 0.3          # ... và hơn tâm khung ít nhất chừng này độ lệch chuẩn
MIN_TEMPLATE_SECONDS = 20   # loại cảnh chiếu tổng cộng dưới chừng này giây thì chưa nói gì về nó


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fmt(knob: str, v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if knob == "tempo":
        return f"×{v:.2f}".replace(".", ",")
    if knob == "music":
        return "0 dB" if abs(v) < 1e-9 else f"{v:+.0f} dB"
    if knob in ("pace", "length", "opening"):
        return f"{v:g} giây".replace(".", ",")
    return f"{v:.0f} px"


def _key(v) -> str:
    return f"{round(float(v), 3):g}"


def _data() -> dict:
    """Phần "style" của data/learned.yaml ({} nếu chưa có hoặc file hỏng)."""
    try:
        d = store.load_learned()
    except Exception as exc:
        log.warning("Phong cách dựng: không đọc được learned.yaml (%s) — dùng mặc định", exc)
        return {}
    st = d.get("style") if isinstance(d, dict) else None
    return st if isinstance(st, dict) else {}


def _save(style_data: dict) -> None:
    # đọc lại file KHÔNG qua lớp chịu lỗi: file hỏng thì báo lỗi chứ không ghi đè mất những thứ đã học
    d = store.load_learned()
    d["style"] = style_data
    store.save_learned(d)


# ------------------------------------------------------------------ khung và mức
def window(knob: str, data: dict = None) -> dict:
    """Khung đang thử của một núm: {"center", "min_center"?, "max_center"?} (min/max do Du đặt)."""
    data = _data() if data is None else data
    w = dict((data.get("windows") or {}).get(knob) or {})
    w.setdefault("center", KNOBS[knob]["center"])
    return w


def arms(knob: str, data: dict = None) -> list:
    """Các mức đang thử: tâm khung và hai mức hai bên (kẹp trong giới hạn cứng)."""
    k = KNOBS[knob]
    c = float(window(knob, data)["center"])
    return sorted({round(min(k["hi"], max(k["lo"], c + d * k["step"])), 3) for d in (-1, 0, 1)})


def posterior(knob: str, value, stats: dict) -> tuple:
    """(trung bình, độ lệch chuẩn) ước lượng cho một mức — co về trung bình chung khi ít video."""
    mu, sd = float(stats["mean"]), float(stats.get("sd") or 1.0)
    st = ((stats.get("knobs") or {}).get(knob) or {}).get(_key(value)) or {"n": 0, "mean": mu}
    n = st["n"]
    return (n * st["mean"] + SHRINK * mu) / (n + SHRINK), sd / math.sqrt(n + SHRINK)


def choose(knob: str, data: dict, rng: random.Random) -> float:
    """Thompson sampling: rút một giá trị "có thể đúng" cho mỗi mức rồi chọn mức cao nhất. Chưa có số
    liệu thì chọn đều ngẫu nhiên — một thử nghiệm ngẫu nhiên đúng nghĩa."""
    vals = arms(knob, data)
    stats = data.get("stats") or {}
    if not stats.get("based_on"):
        return rng.choice(vals)
    draws = []
    for v in vals:
        m, s = posterior(knob, v, stats)
        draws.append((m + s * rng.gauss(0.0, 1.0), v))
    return max(draws)[1]


# ------------------------------------------------------------- gán cho từng video
def get(con, script_id: int):
    r = con.execute("SELECT assigned, applied FROM video_styles WHERE script_id=?", (script_id,)).fetchone()
    if not r:
        return None
    return {"assigned": json.loads(r["assigned"] or "{}"), "applied": json.loads(r["applied"] or "{}")}


def assign(con, script_id: int, cfg: dict = None, legacy_spec: bool = False) -> dict:
    """Phong cách của video dựng từ kịch bản này: gán MỘT lần (lần sau trả lại đúng như cũ, kể cả khi
    dựng lại). legacy_spec: spec cảnh đã sinh trước khi có thử nghiệm -> không thử nhịp đổi cảnh.
    Lỗi gì cũng trả {} (= dựng như mặc định) — thử nghiệm không được làm hỏng việc dựng."""
    try:
        row = get(con, script_id)
        if row and all(k in row["assigned"] for k in KNOBS):
            return row["assigned"]
        data = _data()
        on = ((cfg or {}).get("style") or {}).get("experiments", True) and not data.get("paused")
        rng = random.Random(int(script_id) * 7919 + 17)        # cố định theo kịch bản: chạy lại vẫn vậy
        out = dict(row["assigned"]) if row else {}             # main đã gán sẵn độ dài lúc viết kịch bản
        for knob in KNOBS:
            if knob in out:
                continue
            if knob == "length" or (knob == "pace" and legacy_spec):
                out[knob] = None        # độ dài chỉ gán được TRƯỚC khi viết (main); kịch bản cũ: không thử
            elif on:
                out[knob] = choose(knob, data, rng)
            else:                                                  # tạm dừng thử: dùng tâm khung
                out[knob] = round(float(window(knob, data)["center"]), 3)
        if row:
            con.execute("UPDATE video_styles SET assigned = ? WHERE script_id = ?", (json.dumps(out), script_id))
        else:
            con.execute("INSERT OR IGNORE INTO video_styles (script_id, assigned, applied, at) VALUES (?,?,?,?)",
                        (script_id, json.dumps(out), "{}", _now()))
        con.commit()
        log.info("Phong cách dựng #%s: %s", script_id,
                 ", ".join(f"{KNOBS[k]['label'].lower()} {fmt(k, v)}" for k, v in out.items() if v is not None))
        return get(con, script_id)["assigned"]
    except Exception as exc:
        log.warning("Phong cách dựng: không gán được cho #%s (%s) — dựng như mặc định", script_id, exc)
        return {}


def record_applied(con, script_id: int, **values) -> None:
    """Ghi giá trị THẬT đã dùng (vd giọng hôm đó chậm, assemble phải đọc nhanh hơn mức được gán ->
    video đó không tính cho núm tốc độ đọc)."""
    try:
        row = get(con, script_id)
        if not row:
            return
        applied = dict(row["applied"])
        applied.update(values)
        con.execute("UPDATE video_styles SET applied=? WHERE script_id=?", (json.dumps(applied), script_id))
        con.commit()
    except Exception as exc:
        log.warning("Phong cách dựng: không ghi được giá trị đã dùng của #%s: %s", script_id, exc)


def choose_length(cfg: dict, seed: int):
    """Độ dài tối đa (giây) cho kịch bản sắp viết — Thompson sampling như các núm khác; None nếu tắt thử."""
    try:
        data = _data()
        if not ((cfg or {}).get("style") or {}).get("experiments", True) or data.get("paused"):
            return None
        return choose("length", data, random.Random(int(seed) * 104729 + 3))
    except Exception as exc:
        log.warning("Không chọn được độ dài thử nghiệm: %s", exc)
        return None


def length_bounds(length) -> tuple:
    """(ngắn nhất, dài nhất) giây cho một mức độ dài: 30 -> 22,5-30; 40 -> 30-40; 50 -> 37,5-50."""
    return round(0.75 * float(length), 1), float(length)


def with_length(cfg: dict, length) -> dict:
    """Bản sao cấu hình mà Biên kịch / cổng chuẩn đọc (channel.video_seconds_*) theo độ dài đang thử."""
    if not length:
        return cfg
    lo, hi = length_bounds(length)
    return {**cfg, "channel": {**cfg["channel"], "video_seconds_min": lo, "video_seconds_max": hi}}


def preassign(con, script_id: int, **values) -> None:
    """Ghi các mức đã quyết TRƯỚC khi dựng (độ dài, lúc viết kịch bản); các núm còn lại gán ở produce."""
    try:
        con.execute("INSERT OR IGNORE INTO video_styles (script_id, assigned, applied, at) VALUES (?,?,?,?)",
                    (script_id, json.dumps(values), json.dumps(values), _now()))
        con.commit()
    except Exception as exc:
        log.warning("Không ghi được độ dài thử nghiệm của #%s: %s", script_id, exc)


def with_pacing(cfg: dict, st: dict) -> dict:
    """Bản sao cấu hình với nhịp đổi cảnh của phong cách (agent Sản xuất, cổng cảnh đứng yên, tách câu dài
    đều đọc pacing.scene_seconds_max)."""
    pace = (st or {}).get("pace")
    if not pace:
        return cfg
    pacing = dict(cfg.get("pacing") or {})
    pacing["scene_seconds_max"] = float(pace)
    pacing["scene_seconds_min"] = min(float(pacing.get("scene_seconds_min", 2)), float(pace))
    return {**cfg, "pacing": pacing}


# ------------------------------------------------------------- học mỗi tuần
def _samples(con, rows: list) -> list:
    """[(các núm đã dùng ĐÚNG mức được gán, % xem)] của các video đã đo."""
    out = []
    for r in rows:
        v = r.get(METRIC)
        if v is None or not r.get("script_id"):
            continue
        st = get(con, r["script_id"])
        if not st:
            continue
        used = {}
        for knob in KNOBS:
            a, b = st["assigned"].get(knob), st["applied"].get(knob)
            if a is not None and b is not None and abs(float(a) - float(b)) < 1e-6:
                used[knob] = float(b)
        if used:
            out.append((used, float(v)))
    return out


def _bounds(knob: str, w: dict) -> tuple:
    k = KNOBS[knob]
    lo = k["lo"] if w.get("min_center") is None else max(k["lo"], float(w["min_center"]))
    hi = k["hi"] if w.get("max_center") is None else min(k["hi"], float(w["max_center"]))
    return lo, hi


def evolve(data: dict, now: datetime = None) -> list:
    """Dời khung một nấc về mức bên cạnh khi nó thắng rõ — trong giới hạn cứng và giới hạn Du đặt."""
    stats, notes = data.get("stats") or {}, []
    if not stats.get("based_on"):
        return notes
    sd = float(stats.get("sd") or 1.0)
    for knob, k in KNOBS.items():
        w = window(knob, data)
        c = round(float(w["center"]), 3)
        vals = arms(knob, data)
        if c not in vals:
            continue
        post = {v: posterior(knob, v, stats) for v in vals}
        best = max(vals, key=lambda v: post[v][0])
        group = (stats.get("knobs") or {}).get(knob) or {}
        n_best = (group.get(_key(best)) or {}).get("n", 0)
        if best == c or n_best < SHIFT_MIN_N or post[best][0] - post[c][0] < SHIFT_MARGIN * sd:
            continue
        lo, hi = _bounds(knob, w)
        new = round(min(hi, max(lo, best)), 3)
        if new == c:
            continue                                         # Du đã chặn hướng này
        data.setdefault("windows", {})[knob] = {**w, "center": new}
        raw = lambda v: (group.get(_key(v)) or {})
        note = (f"{k['label']}: tự dời khung về {fmt(knob, new)} — {fmt(knob, best)} được xem"
                f" {raw(best).get('mean', 0):.0f}% ({n_best} video), {fmt(knob, c)} {raw(c).get('mean', 0):.0f}%"
                f" ({raw(c).get('n', 0)} video)")
        notes.append(note)
        _history(data, knob, c, new, "tự học", now)
    return notes


def _history(data: dict, knob: str, old, new, by: str, now: datetime = None) -> None:
    h = data.setdefault("history", [])
    h.append({"at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "knob": knob,
              "from": old, "to": new, "by": by})
    data["history"] = h[-30:]


def production_prefs(rows: list) -> dict:
    """Từ đường giữ chân (weekly.build_rows: "losses", "opening", "engaged_pct"): loại cảnh nào làm người
    xem rời đi nhanh, cảnh mở đầu dạng nào giữ người xem qua vài giây đầu."""
    agg, videos = {}, 0
    for r in rows:
        losses = r.get("losses") or []
        if not losses:
            continue
        videos += 1
        seen = set()
        for tpl, secs, drop in losses:
            a = agg.setdefault(tpl, {"seconds": 0.0, "drop": 0.0, "videos": 0})
            a["seconds"] += secs
            a["drop"] += drop
            if tpl not in seen:
                a["videos"] += 1
                seen.add(tpl)
    loss = {tpl: {"loss10": round(100 * a["drop"] / a["seconds"] * 10, 1), "seconds": round(a["seconds"], 1),
                  "videos": a["videos"]}
            for tpl, a in agg.items() if a["seconds"] >= MIN_TEMPLATE_SECONDS and a["videos"] >= 2}
    opening = {}
    for r in rows:
        if r.get("opening") and r.get("engaged_pct") is not None:
            opening.setdefault(r["opening"], []).append(float(r["engaged_pct"]))
    opening = {k: {"n": len(v), "engaged": round(sum(v) / len(v), 1)} for k, v in opening.items()}
    if videos < MIN_SAMPLES and sum(o["n"] for o in opening.values()) < MIN_SAMPLES:
        return {}
    return {"based_on": videos, "template_loss": loss, "opening": opening}


def update(con, rows: list, now: datetime = None) -> list:
    """Agent Phân tích gọi mỗi Chủ nhật: cập nhật số liệu từng mức, tự dời khung, học theo loại cảnh.
    Trả về các dòng mô tả khung đã tự dời (để đưa vào báo cáo)."""
    now = now or datetime.now(timezone.utc)
    data, notes, changed = _data(), [], False
    samples = _samples(con, rows)
    if len(samples) >= MIN_SAMPLES:
        vals = [v for _, v in samples]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        groups = {}
        for used, v in samples:
            for knob, x in used.items():
                groups.setdefault(knob, {}).setdefault(_key(x), []).append(v)
        data["stats"] = {"metric": METRIC, "based_on": len(samples), "mean": round(mean, 3), "sd": round(sd, 3),
                         "knobs": {k: {x: {"n": len(vs), "mean": round(sum(vs) / len(vs), 3)}
                                       for x, vs in g.items()} for k, g in groups.items()},
                         "updated_at": now.isoformat(timespec="seconds")}
        notes = evolve(data, now)
        changed = True
    prod = production_prefs(rows)
    if prod:
        data["production"] = prod
        changed = True
    if changed:
        _save(data)
    return notes


# ------------------------------------------------------------- lời dặn agent Sản xuất
def production_block(data: dict = None) -> str:
    prod = (_data() if data is None else data).get("production") or {}
    lines = []
    loss = prod.get("template_loss") or {}
    if prod.get("based_on", 0) >= MIN_SAMPLES and len(loss) >= 2:
        worst = max(loss, key=lambda t: loss[t]["loss10"])
        best = min(loss, key=lambda t: loss[t]["loss10"])
        lines.append(f"- Loại cảnh làm người xem rời đi nhanh nhất: \"{worst}\" (mất {loss[worst]['loss10']:g} điểm %"
                     f" mỗi 10 giây); giữ chân tốt nhất: \"{best}\" ({loss[best]['loss10']:g}). Ưu tiên \"{best}\""
                     f" khi số liệu hợp; \"{worst}\" chỉ dùng khi câu không có gì để vẽ.")
    opening = {k: v for k, v in (prod.get("opening") or {}).items() if v["n"] >= 2}
    if len(opening) >= 2:
        ranked = sorted(opening.items(), key=lambda kv: -kv[1]["engaged"])
        lines.append("- Cảnh MỞ ĐẦU: " + ", ".join(f"\"{k}\" giữ {v['engaged']:g}% người xem qua vài giây đầu"
                                                    f" ({v['n']} video)" for k, v in ranked)
                     + " — chọn dạng mở đầu tốt nếu hợp với câu hook.")
    if not lines:
        return ""
    return (f"\nNGƯỜI XEM KÊNH NÀY ĐÃ CHO THẤY ({prod.get('based_on', 0)} video có đường giữ chân):\n"
            + "\n".join(lines) + "\n")


# ------------------------------------------------------------- Du chỉnh qua Telegram
def shift(knob: str, direction: int, by: str = "du", now: datetime = None) -> tuple:
    """Dời khung một nấc (direction +1/-1). by="du": hướng ngược lại bị chặn với việc tự dời khung
    (Du chê nhạc to -> hệ thống không tự tăng nhạc lại). Trả về (các mức trước, các mức sau)."""
    data = _data()
    k = KNOBS[knob]
    w = window(knob, data)
    before = arms(knob, data)
    c = float(w["center"])
    new = round(min(k["hi"], max(k["lo"], c + direction * k["step"])), 3)
    w = {**w, "center": new}
    if by == "du":
        if direction > 0:
            w["min_center"] = new
            w.pop("max_center", None)
        else:
            w["max_center"] = new
            w.pop("min_center", None)
    data.setdefault("windows", {})[knob] = w
    _history(data, knob, c, new, by, now)
    _save(data)
    return before, arms(knob, data)


def set_paused(paused: bool) -> None:
    data = _data()
    data["paused"] = bool(paused)
    _save(data)


def _leader(knob: str, data: dict) -> str:
    stats = data.get("stats") or {}
    group = (stats.get("knobs") or {}).get(knob) or {}
    vals = [v for v in arms(knob, data) if (group.get(_key(v)) or {}).get("n", 0) >= 2]
    if not stats.get("based_on") or len(vals) < 2:
        return ""
    best = max(vals, key=lambda v: posterior(knob, v, stats)[0])
    g = group[_key(best)]
    return f"{fmt(knob, best)} ({g['mean']:.0f}% thời lượng được xem, {g['n']} video)"


def status_text(data: dict = None) -> str:
    data = _data() if data is None else data
    head = ("⏸ Đang TẠM DỪNG thử — mọi video dùng tâm khung (/kieu bat để thử tiếp)" if data.get("paused") else
            "🎛 Phong cách dựng đang thử (mỗi video một tổ hợp, Chủ nhật so % thời lượng được xem):")
    lines = [head]
    for knob, k in KNOBS.items():
        lead = _leader(knob, data)
        lines.append(f"• {k['label']}: " + " · ".join(fmt(knob, v) for v in arms(knob, data))
                     + (f" — dẫn: {lead}" if lead else ""))
    if not (data.get("stats") or {}).get("based_on"):
        lines.append(f"(Chưa đủ số liệu: cần ≥ {MIN_SAMPLES} video dựng theo cách này có % xem.)")
    lines.append("Chỉnh: /giong nhanh|cham · /nhac to|nho · /nhip nhanh|cham · /chu to|nho · /video ngan|dai"
                 " · /kieu tat|bat")
    return "\n".join(lines)


def latest_applied(con, knob: str):
    """Giá trị núm này ở video gửi duyệt gần nhất (để trả lời Du "video vừa rồi dùng mức nào")."""
    r = con.execute("SELECT st.applied FROM videos v JOIN video_styles st ON st.script_id = v.script_id"
                    " WHERE v.tg_message_id IS NOT NULL ORDER BY v.id DESC LIMIT 1").fetchone()
    return json.loads(r["applied"] or "{}").get(knob) if r else None


def weekly_lines(con, now: datetime = None, notes=()) -> list:
    """Mục "🎬 Học cách dựng" của báo cáo tuần."""
    data = _data()
    lines = ["", "🎬 Học cách dựng:"]
    stats = data.get("stats") or {}
    if stats.get("based_on"):
        for knob, k in KNOBS.items():
            g = (stats.get("knobs") or {}).get(knob) or {}
            if g:
                lines.append(f"  {k['label']}: " + " · ".join(
                    f"{fmt(knob, float(x))} {v['mean']:.0f}% (n={v['n']})"
                    for x, v in sorted(g.items(), key=lambda kv: float(kv[0]))))
    else:
        lines.append("  Đang thử: " + "; ".join(
            f"{k['label'].lower()} {' / '.join(fmt(knob, v) for v in arms(knob, data))}" for knob, k in KNOBS.items()))
        lines.append(f"  (cần ≥ {MIN_SAMPLES} video dựng theo cách này có % xem mới so được)")
    lines += [f"  ↪ {n}" for n in notes]
    loss = (data.get("production") or {}).get("template_loss") or {}
    if len(loss) >= 2:
        ranked = sorted(loss.items(), key=lambda kv: -kv[1]["loss10"])
        lines.append("  Loại cảnh (điểm % người xem mất mỗi 10 giây, cao = đuổi người xem): "
                     + " · ".join(f"{t} {v['loss10']:g}" for t, v in ranked) + " — đã đưa vào lời dặn Sản xuất")
    return lines


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from . import db
    from .main import load_config
    con = db.connect()
    if len(sys.argv) >= 3 and sys.argv[1] == "assign":
        sid = int(sys.argv[2])
        st = assign(con, sid, load_config(), legacy_spec=True)
        print(f"Kịch bản #{sid}:", ", ".join(f"{KNOBS[k]['label']} {fmt(k, v)}" for k, v in st.items()))
        return
    print(status_text())
    print(production_block() or "(chưa đủ số liệu giữ chân theo loại cảnh)")


if __name__ == "__main__":
    main()
