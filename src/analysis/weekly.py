"""Agent Phân tích — chạy MỖI TUẦN: đọc số liệu thật của kênh rồi rút kinh nghiệm.

    python -m src.analysis.weekly               # đo, phân tích, ghi data/learned.yaml, báo Telegram
    python -m src.analysis.weekly --dry-run     # không gọi mạng, không ghi learned.yaml: in báo cáo từ số liệu đã lưu
    python -m src.analysis.weekly --no-telegram # chạy thật nhưng in báo cáo ra màn hình

Việc nó làm:
  1. Đo từng video đã đăng. Có quyền OAuth -> YouTube Analytics (% xem trung bình, đường
     giữ chân). Chưa có -> chỉ lấy được số công khai (xem/thích/bình luận) bằng API key.
  2. Tìm điểm người xem rời đi nhiều nhất, quy ra đúng CẢNH nào trong video.
  3. Chỉnh trọng số chấm điểm của agent Biên tập — rất dè dặt (xem propose_weights).
  4. Nhờ LLM rút vài bài học từ bảng số liệu, đưa cho agent Biên kịch đọc.
  5. Cập nhật "sở thích người xem" (src/learning.py): kiểu mở đầu / mảng / dạng video nào giữ chân
     tốt -> daily ưu tiên, máy chọn hook cộng điểm; báo cáo thêm mục "Tự học".
  6. Học cách dựng (src/style.py): so % xem giữa các mức thử nghiệm (tốc độ đọc, nhạc, nhịp cảnh, cỡ phụ
     đề), tự dời khung khi một mức thắng rõ, học loại cảnh nào giữ chân; báo cáo mục "Học cách dựng".
  7. Agent Tăng trưởng (src/growth.py): đo cả kênh + tiến độ YPP, video đột biến -> ưu tiên làm tiếp;
     kèm tóm tắt agent Cộng đồng (bình luận) và các chủ đề được yêu cầu (src/topics.py).
  8. Agent Hiểu YouTube (src/yt_insights.py): YouTube phân phối video của kênh qua đâu, người xem gõ gì để
     tìm ra kênh, mỗi video được đẩy bao lâu; agent Tin YouTube (src/yt_news.py): YouTube vừa đổi gì.
  9. Agent Học kênh lớn (src/analysis/big_channels.py): video đột biến của kênh lớn cùng ngách được làm
     thế nào (Gemini xem video) -> sổ tay cấu trúc cho Biên kịch / Đăng bài; cổng chống chép tiêu đề.

Thành thật về thống kê: vài video đầu KHÔNG đủ để kết luận gì. Vì vậy có ngưỡng tối
thiểu, mỗi tuần chỉ nhích trọng số 0.1, và báo cáo luôn ghi dựa trên bao nhiêu video.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .. import db, lang
from .. import telegram_bot as tg
from . import learned as learned_mod

log = logging.getLogger("weekly")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = lang.config_path()          # kênh đang chạy (CHANNEL_CONFIG; mặc định kênh Việt)
SPEC_DIR = ROOT / "data" / "specs"

CRITERIA = ("curiosity", "novelty", "verifiability", "accessibility", "visualizability")
MIN_AGE_DAYS = 3            # video mới đăng chưa đủ số liệu (Analytics trễ 2-3 ngày)
MIN_VIDEOS_INSIGHT = 3      # dưới mức này không nhờ LLM rút bài học
MIN_VIDEOS_WEIGHTS = 10     # dưới mức này không đụng vào trọng số
RHO_THRESHOLD = 0.5         # tương quan hạng phải mạnh cỡ này mới nhích trọng số
WEIGHT_STEP = 0.1
WEIGHT_MIN, WEIGHT_MAX = 0.5, 2.5
HOOK_SECONDS = 3.0


# ------------------------------------------------------------ Thống kê thuần
def _ranks(values: list) -> list:
    """Hạng của từng giá trị (1 = nhỏ nhất); bằng nhau thì chia đều hạng."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list, ys: list):
    """Tương quan hạng Spearman (-1..1): x tăng thì y có xu hướng tăng theo không?
    Trả None khi không tính được (ít hơn 3 điểm, hoặc một bên toàn giá trị giống nhau)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def pick_metric(rows: list) -> str:
    """Thước đo thành công: ưu tiên % xem trung bình (đúng mục tiêu 'tỷ lệ xem hết'),
    không đủ thì dùng lượt xem."""
    with_pct = sum(1 for r in rows if r.get("avg_view_pct") is not None)
    return "avg_view_pct" if with_pct >= max(MIN_VIDEOS_INSIGHT, len(rows) // 2) else "views"


def propose_weights(rows: list, weights: dict, metric: str) -> tuple:
    """Đề xuất trọng số mới cho agent Biên tập. Trả về (trọng số mới, [giải thích]).

    Ý tưởng: nếu video có điểm 'độ tò mò' cao thường cũng giữ chân tốt (tương quan hạng
    >= 0.5) thì tiêu chí đó đáng tin -> tăng trọng số 0.1; ngược chiều thì giảm 0.1.
    Cố ý chậm: ít video thì tương quan dễ là ngẫu nhiên, nhích từng chút sẽ không lạc xa.
    """
    usable = [r for r in rows if r.get(metric) is not None and r.get("scores")]
    if len(usable) < MIN_VIDEOS_WEIGHTS:
        return dict(weights), [f"Chưa chỉnh trọng số: mới có {len(usable)}/{MIN_VIDEOS_WEIGHTS}"
                               " video đủ số liệu."]
    new, notes = dict(weights), []
    perf = [r[metric] for r in usable]
    for c in CRITERIA:
        if c not in weights:
            continue
        rho = spearman([r["scores"].get(c, 0) for r in usable], perf)
        if rho is None or abs(rho) < RHO_THRESHOLD:
            continue
        step = WEIGHT_STEP if rho > 0 else -WEIGHT_STEP
        value = round(min(WEIGHT_MAX, max(WEIGHT_MIN, weights[c] + step)), 2)
        if value != weights[c]:
            new[c] = value
            notes.append(f"{c}: {weights[c]} → {value} (tương quan {rho:+.2f} trên {len(usable)} video)")
    if notes and "min_total" in weights:
        # Ngưỡng chọn ý tưởng co giãn theo tổng trọng số, để độ khắt khe không đổi
        old_sum = sum(weights[c] for c in CRITERIA if c in weights)
        new_sum = sum(new[c] for c in CRITERIA if c in new)
        new["min_total"] = round(weights["min_total"] * new_sum / old_sum, 1)
    return new, notes or ["Trọng số giữ nguyên: không tiêu chí nào tương quan đủ mạnh."]


# ------------------------------------------------------- Điểm người xem rời đi
def scene_timeline(script_id: int) -> list:
    """[(giây bắt đầu, giây kết thúc, template, lời đọc)] từ spec đã dựng thật."""
    path = SPEC_DIR / f"script_{script_id}_final.yaml"
    if not path.exists():
        return []
    t, out = 0.0, []
    for sc in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        secs = float(sc.get("seconds", 0))
        out.append((t, t + secs, sc.get("template", "?"), sc.get("voice", "")))
        t += secs
    return out


def _watch_at(pts: list, t: float) -> float:
    """Tỷ lệ còn xem ở giây t (nội suy tuyến tính trên đường giữ chân [(giây, tỷ lệ)])."""
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, w0), (t1, w1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return w0 + (w1 - w0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    return pts[-1][1]


def scene_losses(retention: list, timeline: list) -> list:
    """[(template, số giây, tỷ lệ người xem mất đi)] cho từng cảnh, bỏ 3 giây đầu (chuyện của hook).
    Để trả lời bằng số: cảnh CHỮ có đuổi người xem nhiều hơn cảnh biểu đồ không (19/11/2026)."""
    if len(retention) < 5 or not timeline:
        return []
    total = timeline[-1][1]
    pts = sorted((r * total, w) for r, w in retention)
    out = []
    for a, b, tpl, _ in timeline:
        a = max(a, HOOK_SECONDS)
        if b - a >= 0.5:
            out.append((tpl, b - a, _watch_at(pts, a) - _watch_at(pts, b)))
    return out


def loss_by_template(rows: list) -> dict:
    """{template: điểm % người xem mất trung bình mỗi 10 giây cảnh đó chiếu}, gộp mọi video có đường
    giữ chân; loại cảnh tổng cộng dưới 10 giây thì bỏ (quá ít để nói gì)."""
    agg = {}
    for r in rows:
        for tpl, secs, drop in r.get("losses") or []:
            s, d = agg.get(tpl, (0.0, 0.0))
            agg[tpl] = (s + secs, d + drop)
    return {tpl: round(100 * d / s * 10, 1) for tpl, (s, d) in agg.items() if s >= 10}


def retention_findings(retention: list, timeline: list):
    """Từ đường giữ chân -> (a) % người còn xem sau 3 giây đầu (đo câu hook),
    (b) chỗ rớt mạnh nhất SAU đoạn hook và nó rơi vào cảnh nào."""
    if len(retention) < 5 or not timeline:
        return None
    total = timeline[-1][1]
    pts = [(ratio * total, watch) for ratio, watch in retention]
    after_hook = [p for p in pts if p[0] >= HOOK_SECONDS]
    if len(after_hook) < 2:
        return None
    worst, at = 0.0, None
    for (t0, w0), (t1, w1) in zip(after_hook, after_hook[1:]):
        if w0 - w1 > worst:
            worst, at = w0 - w1, t1
    out = {"hook_hold": round(after_hook[0][1] * 100)}
    if at is not None:
        idx = next((i for i, (a, b, _, _) in enumerate(timeline) if a <= at < b), len(timeline) - 1)
        out.update(drop_at=round(at, 1), drop_size=round(worst * 100, 1), drop_scene=idx + 1,
                   drop_template=timeline[idx][2], drop_voice=timeline[idx][3])
    return out


# ---------------------------------------------------------------- Đo số liệu
def published_videos(con) -> list:
    rows = con.execute(
        "SELECT v.id, v.script_id, v.title, v.youtube_id, v.published_at, i.scores"
        " FROM videos v JOIN scripts s ON s.id = v.script_id JOIN ideas i ON i.id = s.idea_id"
        " WHERE v.status = 'published' AND v.youtube_id IS NOT NULL ORDER BY v.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["scores"] = json.loads(d["scores"] or "{}")
        except ValueError:
            d["scores"] = {}
        out.append(d)
    return out


def fetch_and_store(con, videos: list, now: datetime) -> str:
    """Đo mọi video đã đăng, lưu vào bảng video_stats. Trả về nguồn đã dùng."""
    from ..publish import youtube

    if not videos:
        return "none"
    today = now.strftime("%Y-%m-%d")
    if youtube.TOKEN_PATH.exists() and os.getenv("YT_CLIENT_ID"):
        try:
            token = youtube.access_token()
            got = set()
            for v in videos:
                start = (v["published_at"] or today)[:10]
                raw = youtube.analytics_video(v["youtube_id"], start, today, token)
                # Analytics trễ 2-3 ngày: video mới trả rỗng hoặc toàn 0 (đo 16/11: video #6 có 717
                # lượt xem công khai mà Analytics báo 0) -> để số công khai bên dưới điền thay
                if not raw or not raw.get("views"):
                    continue
                got.add(v["id"])
                stats = {"views": raw.get("views"), "likes": raw.get("likes"),
                         "comments": raw.get("comments"), "shares": raw.get("shares"),
                         "subs_gained": raw.get("subscribersGained"),
                         "avg_view_sec": raw.get("averageViewDuration"),
                         "avg_view_pct": raw.get("averageViewPercentage"),
                         # Shorts: lượt xem qua được vài giây đầu — phần còn lại là lướt đi ngay
                         "engaged_views": raw.get("engagedViews")}
                try:
                    retention = youtube.analytics_retention(v["youtube_id"], start, today, token)
                except Exception as exc:
                    log.warning("Không lấy được đường giữ chân video #%s: %s", v["id"], exc)
                    retention = []
                db.save_video_stats(con, v["id"], "analytics", stats, retention)
            key = os.getenv("YOUTUBE_API_KEY")
            late = [v for v in videos if v["id"] not in got]
            if late and key:
                try:
                    pub = youtube.public_stats([v["youtube_id"] for v in late], key)
                    for v in late:
                        if v["youtube_id"] in pub:
                            db.save_video_stats(con, v["id"], "public", pub[v["youtube_id"]])
                except Exception as exc:
                    log.warning("Không lấy được số công khai cho video Analytics chưa có số: %s", exc)
            return "analytics"
        except Exception as exc:       # token hỏng v.v. -> lùi về số công khai
            log.warning("YouTube Analytics lỗi (%s) — lùi về số liệu công khai", exc)
    key = os.getenv("YOUTUBE_API_KEY")
    if key:
        pub = youtube.public_stats([v["youtube_id"] for v in videos], key)
        for v in videos:
            if v["youtube_id"] in pub:
                db.save_video_stats(con, v["id"], "public", pub[v["youtube_id"]])
        return "public"
    return "none"


def build_rows(con, videos: list, now: datetime) -> list:
    """Ghép mỗi video với lần đo mới nhất + phát hiện về giữ chân. Bỏ video còn quá mới."""
    rows = []
    for v in videos:
        st = con.execute("SELECT * FROM video_stats WHERE video_id=? ORDER BY id DESC LIMIT 1",
                         (v["id"],)).fetchone()
        if not st:
            continue
        try:
            age = (now - datetime.fromisoformat(v["published_at"])).days
        except (TypeError, ValueError):
            age = MIN_AGE_DAYS
        if age < MIN_AGE_DAYS:
            continue
        row = dict(v, age_days=age, source=st["source"], views=st["views"], likes=st["likes"],
                   avg_view_pct=st["avg_view_pct"], avg_view_sec=st["avg_view_sec"],
                   subs_gained=st["subs_gained"])          # agent Tăng trưởng: video nào kéo người đăng ký
        engaged = st["engaged_views"] if "engaged_views" in st.keys() else None
        row["engaged_pct"] = (round(100 * engaged / st["views"]) if engaged is not None and st["views"]
                              else None)
        retention = json.loads(st["retention"]) if st["retention"] else []
        timeline = scene_timeline(v["script_id"])
        row["retention"] = retention_findings(retention, timeline)
        row["losses"] = scene_losses(retention, timeline)
        # dạng cảnh MỞ ĐẦU (bỏ thẻ intro của video đời cũ) — học cách dựng (src/style.py)
        row["opening"] = next((tpl for _, _, tpl, _ in timeline if tpl != "intro"), None)
        rows.append(row)
    return rows


# ------------------------------------------------------------------ Bài học
def _row_line(r: dict) -> str:
    bits = [f"{r['views']:,} xem".replace(",", ".") if r.get("views") is not None else "? xem"]
    if r.get("engaged_pct") is not None:
        bits.append(f"qua vài giây đầu {r['engaged_pct']}%")
    if r.get("avg_view_pct") is not None:
        bits.append(f"xem TB {r['avg_view_pct']:.0f}%")
    f = r.get("retention")
    if f:
        bits.append(f"còn {f['hook_hold']}% sau {HOOK_SECONDS:.0f}s")
        if "drop_scene" in f:
            bits.append(f"rớt mạnh nhất ở giây {f['drop_at']} (cảnh {f['drop_scene']}, {f['drop_template']})")
    return f"#{r['id']} {r['title'][:60]} — " + " · ".join(bits)


def synthesize_insights(rows: list, rejected_notes: list, cfg: dict) -> list:
    """Nhờ LLM rút tối đa 5 bài học từ bảng số liệu. Dữ liệu thô đưa nguyên vào prompt,
    dặn rõ chỉ kết luận trong phạm vi dữ liệu."""
    from ..crew import _run_single_task
    from ..utils import extract_json

    listing = []
    for r in rows:
        line = _row_line(r)
        f = r.get("retention") or {}
        if f.get("drop_voice"):
            line += f"\n    lời ở chỗ rớt: \"{f['drop_voice'][:120]}\""
        listing.append("- " + line)
    notes = "\n".join(f"- {n}" for n in rejected_notes) or "(không có)"
    losses = loss_by_template(rows)
    if losses:
        listing.append("- Người xem mất đi theo loại cảnh (điểm % mỗi 10 giây): " + ", ".join(
            f"{tpl} {v}" for tpl, v in sorted(losses.items(), key=lambda kv: -kv[1])))
    out = _run_single_task(
        role="Nhà phân tích số liệu kênh video ngắn",
        goal="Rút bài học dùng được ngay cho người viết kịch bản, không suy diễn quá dữ liệu",
        description=f"""Kênh "{cfg['channel']['name']}" vừa có số liệu của {len(rows)} video:

{chr(10).join(listing)}

Ghi chú của chủ kênh khi loại/nhận xét video:
{notes}

Rút ra TỐI ĐA 5 bài học cụ thể cho người viết kịch bản và dựng cảnh (câu mở đầu, độ dài,
loại cảnh nào giữ/đuổi người xem, đề tài). Luật:
- Mỗi bài học phải nêu dựa trên video số mấy.
- Chỉ {len(rows)} video là rất ít: thấy gì nói nấy, KHÔNG khái quát thành quy luật chắc chắn.
- Không có gì rõ ràng thì trả mảng rỗng.""",
        expected_output='JSON object: {"insights": ["...", "..."]}')
    insights = extract_json(out).get("insights", [])
    return [str(i)[:300] for i in insights][:5]


def format_report(rows: list, total_published: int, source: str, weight_notes: list,
                  insights: list) -> str:
    src = {"analytics": "YouTube Analytics", "public": "số công khai (chưa có % xem — cần cấp quyền OAuth)",
           "none": "KHÔNG đo được (thiếu cả OAuth lẫn YOUTUBE_API_KEY)", "stored": "số liệu đã lưu"}[source]
    lines = [f"📊 Báo cáo tuần — {total_published} video đã đăng, {len(rows)} video đủ {MIN_AGE_DAYS} ngày tuổi",
             f"Nguồn: {src}", ""]
    metric = pick_metric(rows) if rows else "views"
    for r in sorted(rows, key=lambda r: -(r.get(metric) or 0)):
        lines.append(_row_line(r))
    if not rows:
        lines.append("Chưa có video nào đủ số liệu để phân tích.")
    losses = loss_by_template(rows)
    if losses:
        lines += ["", "📉 Người xem mất đi theo loại cảnh (điểm % mỗi 10 giây cảnh chiếu, cao = đuổi người xem):",
                  "  " + " · ".join(f"{tpl} {v:.1f}".replace(".", ",")
                                    for tpl, v in sorted(losses.items(), key=lambda kv: -kv[1]))]
    lines += ["", "⚖️ Trọng số Biên tập:"] + [f"  {n}" for n in weight_notes]
    if insights:
        lines += ["", "💡 Bài học (đã đưa cho agent Biên kịch):"] + [f"  • {i}" for i in insights]
    elif len(rows) < MIN_VIDEOS_INSIGHT:
        lines += ["", f"💡 Cần ít nhất {MIN_VIDEOS_INSIGHT} video đủ số liệu mới rút bài học."]
    return "\n".join(lines)


def run_weekly(dry_run: bool = False, use_telegram: bool = True, now: datetime = None) -> str:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    learned_mod.apply_learned(cfg)                  # bắt đầu từ trọng số đang dùng thật
    if not dry_run and use_telegram:
        try:
            from .. import gemini_key               # khoá Gemini chính bị Google chặn -> chạy bằng khoá dự phòng
            gemini_key.ensure()
        except Exception as exc:
            log.warning("Không kiểm được khoá Gemini: %s", exc)
    con = db.connect()
    try:
        return _run_weekly(cfg, con, dry_run, use_telegram, now)
    finally:
        con.close()      # Windows: kết nối mở giữ khóa file DB


def _run_weekly(cfg, con, dry_run, use_telegram, now) -> str:
    now = now or datetime.now(timezone.utc)
    videos = published_videos(con)
    source = "stored" if dry_run else fetch_and_store(con, videos, now)
    rows = build_rows(con, videos, now)

    metric = pick_metric(rows) if rows else "views"
    weights = cfg["scoring_weights"]
    new_weights, weight_notes = propose_weights(rows, weights, metric)

    insights = []
    if len(rows) >= MIN_VIDEOS_INSIGHT and not dry_run:
        notes = [f"video #{r['id']} ({r['status']}): {r['review_note']}" for r in con.execute(
            "SELECT id, status, review_note FROM videos WHERE review_note IS NOT NULL"
            " ORDER BY id DESC LIMIT 10")]
        try:
            insights = synthesize_insights(rows, notes, cfg)
        except Exception as exc:
            log.warning("LLM rút bài học lỗi: %s", exc)

    from .. import community, fb_insights, growth, ig_insights, learning, style, topics, yt_insights, yt_news
    from . import big_channels
    style_notes, growth_lines, insight_lines, big_lines, fb_lines = [], [], [], [], []
    if not dry_run:
        from ..publish import youtube
        try:
            token = youtube.access_token()
        except Exception:
            token = None
        try:
            # AGENT TĂNG TRƯỞNG: đo cả kênh, tiến độ YPP, video đột biến -> ưu tiên + xếp hàng làm tiếp
            growth_lines = growth.update(con, cfg, rows, now, token)
        except Exception as exc:
            log.warning("Agent Tăng trưởng lỗi: %s", exc)
        try:
            # AGENT HIỂU YOUTUBE: nguồn lượt xem, từ khoá tìm kiếm, vòng đời video, kênh hàng xóm
            insight_lines = yt_insights.update(con, cfg, token, now)
        except Exception as exc:
            log.warning("Agent Hiểu YouTube lỗi: %s", exc)
        try:
            yt_news.run(con, now)              # AGENT TIN YOUTUBE: tin ảnh hưởng lớn báo Du ngay
        except Exception as exc:
            log.warning("Agent Tin YouTube lỗi: %s", exc)
        try:
            # AGENT HỌC KÊNH LỚN: video đột biến của kênh lớn cùng ngách -> sổ tay cấu trúc (không chép)
            big_lines = big_channels.update(con, cfg, now)
        except Exception as exc:
            log.warning("Agent Học kênh lớn lỗi: %s", exc)
        try:
            # AGENT FACEBOOK (src/fb_insights.py): số liệu Reels + Trang, sở thích người xem Facebook,
            # thử giờ đăng. Chưa kết nối Trang thì không làm gì.
            fb_lines = fb_insights.update(con, cfg, now)
        except Exception as exc:
            log.warning("Agent Facebook lỗi: %s", exc)
        try:
            fb_lines += ig_insights.update(con, cfg, now)      # AGENT INSTAGRAM (kênh Hàn, src/ig_insights.py)
        except Exception as exc:
            log.warning("Agent Instagram lỗi: %s", exc)
        try:
            from ..publish import playlists        # video đăng tay / lỗi lúc đăng: bổ sung vào danh sách phát
            playlists.backfill(con, cfg, token)
        except Exception as exc:
            log.warning("Danh sách phát lỗi: %s", exc)
        if use_telegram:
            try:
                from .. import backup              # SAO LƯU ra ngoài VM: DB + learned.yaml vào Telegram của Du
                backup.send_weekly(now)
            except Exception as exc:
                log.warning("Sao lưu tuần lỗi: %s", exc)
        # Hai bước dưới PHẢI nằm trong nhánh chạy thật (không phải dry_run) — 20/11 từng lọt vào nhánh
        # else khi thêm agent Hiểu YouTube nên lượt Chủ nhật thật không cập nhật gì (test chốt chặn)
        try:
            # TỰ HỌC từ người xem: kiểu mở đầu / mảng / dạng video nào giữ chân tốt -> learned.yaml,
            # daily và máy chọn hook đọc lại. Gọi TRƯỚC load_learned bên dưới để không ghi đè mất.
            learning.update_preferences(con, rows, now)
        except Exception as exc:
            log.warning("Cập nhật sở thích người xem lỗi: %s", exc)
        try:
            # HỌC CÁCH DỰNG: so % xem giữa các mức thử nghiệm, tự dời khung, học theo loại cảnh
            style_notes = style.update(con, rows, now)
        except Exception as exc:
            log.warning("Cập nhật học cách dựng lỗi: %s", exc)
    else:
        insight_lines = yt_insights.report_lines(yt_insights._data().get("latest") or {})
        big_lines = big_channels.report_lines(big_channels._data(), [], [])
        fb_lines = fb_insights.report_lines(fb_insights._data().get("latest") or {})             + ig_insights.report_lines(ig_insights._data().get("latest") or {})

    report =format_report(rows, len(videos), source, weight_notes, insights)
    for part, what in ((lambda: growth_lines, "tăng trưởng"),
                       (lambda: insight_lines, "hiểu YouTube"),
                       (lambda: big_lines, "học kênh lớn"),
                       (lambda: fb_lines, "Facebook"),
                       (lambda: yt_news.report_lines(con, now), "tin YouTube"),
                       (lambda: learning.weekly_lines(con, now), "tự học"),
                       (lambda: style.weekly_lines(con, now, style_notes), "học cách dựng"),
                       (lambda: community.weekly_lines(con, now), "cộng đồng"),
                       (lambda: topics.weekly_lines(con, now), "chủ đề được yêu cầu")):
        try:
            report = "\n".join([report] + part())
        except Exception as exc:
            log.warning("Tóm tắt %s lỗi: %s", what, exc)
    if dry_run:
        print(report)
        return report

    data = learned_mod.load_learned()
    changed = new_weights != weights
    if changed:
        data["scoring_weights"] = {k: new_weights[k] for k in new_weights
                                   if k in CRITERIA or k == "min_total"}
    if insights:
        data["insights"] = insights
    if changed or insights:
        data["updated_at"] = now.isoformat(timespec="seconds")
        data["based_on_videos"] = len(rows)
        history = data.get("history", [])
        history.append({"date": now.strftime("%Y-%m-%d"), "videos": len(rows),
                        "weights": weight_notes if changed else []})
        data["history"] = history[-12:]
        learned_mod.save_learned(data)

    if not (use_telegram and tg.send_message(report)):
        print(report)
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Agent Phân tích hằng tuần")
    ap.add_argument("--dry-run", action="store_true", help="Không gọi mạng, không ghi gì")
    ap.add_argument("--no-telegram", action="store_true", help="In báo cáo ra màn hình")
    args = ap.parse_args()
    run_weekly(dry_run=args.dry_run, use_telegram=not args.no_telegram)


if __name__ == "__main__":
    main()
