"""Kiểm chứng nguồn thứ hai cho ý tưởng số liệu World Bank: đối chiếu với Our World in Data (OWID).

Thiết kế (CLAUDE.md) đòi "mỗi thông tin đối chiếu ít nhất 2 nguồn". Tìm kiếm web qua Gemini
cần project trả phí (đo 12/11/2026: gói miễn phí bị chặn, gemini-2.5-flash-lite không mở cho người
dùng mới). Với dạng video chủ lực của kênh — số liệu World Bank — đã có nguồn thứ hai miễn phí,
có cấu trúc: OWID. Chỉ dùng những chuỗi OWID KHÔNG chép lại từ World Bank (Internet, lao động nữ
trên OWID chính là số World Bank -> không tính là độc lập).

Việc làm: lấy các điểm số liệu chính trong tóm tắt ý tưởng (Việt Nam, Hàn Quốc, nơi cao nhất/
thấp nhất) -> tra cùng nước, cùng năm trên OWID -> so lệch. Kết quả để Du xem lúc duyệt; KHÔNG
chặn video (hai cơ quan thống kê có thể ước tính khác nhau chút ít — đó không phải lỗi kịch bản),
nhưng lệch lớn thì nổi bật để Du biết mà soát.
"""
import csv
import io
import logging
import re
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "owid"
CACHE_DAYS = 7
GRAPHER = "https://ourworldindata.org/grapher/{slug}"

# mã chỉ số World Bank -> (chuỗi OWID, hệ số đổi đơn vị OWID về đơn vị World Bank, gốc dữ liệu)
OWID = {
    "SP.DYN.LE00.IN": ("life-expectancy", 1.0, "UN WPP / HMD"),
    "SP.DYN.TFRT.IN": ("children-per-woman-un", 1.0, "UN WPP"),
    "SP.URB.TOTL.IN.ZS": ("share-of-population-urban", 1.0, "UN World Urbanization Prospects"),
    "SP.DYN.IMRT.IN": ("infant-mortality", 10.0, "UN IGME"),          # OWID: trên 100 trẻ; WB: trên 1.000
    "AG.LND.FRST.ZS": ("forest-area-as-share-of-land-area", 1.0, "FAO"),
    "SP.POP.TOTL": ("population", 1.0, "UN WPP"),
}
MATCH, SMALL = 0.03, 0.10          # lệch ≤3%: khớp; ≤10%: lệch nhẹ; hơn nữa: lệch lớn


def fetch_table(slug: str, now: float = None) -> dict:
    """{(mã ISO3, năm): giá trị} của một chuỗi OWID; lưu đệm CACHE_DAYS ngày."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{slug}.csv"
    if not path.exists() or (now or time.time()) - path.stat().st_mtime > CACHE_DAYS * 86400:
        r = requests.get(GRAPHER.format(slug=slug) + ".csv", timeout=60,
                         params={"v": 1, "csvType": "full", "useColumnShortNames": "true"},
                         headers={"User-Agent": "video-agents-pipeline/0.1"})
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    out = {}
    for row in csv.reader(io.StringIO(path.read_text(encoding="utf-8"))):
        if len(row) < 4 or not row[1] or not row[2].lstrip("-").isdigit():
            continue                         # dòng tiêu đề, hoặc vùng không có mã (châu lục...)
        try:
            out[(row[1], int(row[2]))] = float(row[3])
        except ValueError:
            continue
    return out


def data_points(summary: str, limit: int = 6) -> list:
    """Các điểm số liệu chính trong tóm tắt -> [(nhãn, mã ISO3, năm, giá trị)]: năm đầu + năm cuối
    của mỗi chuỗi theo năm, và (ý tưởng bản đồ thế giới) nơi cao nhất/thấp nhất."""
    from .render.geo import code_of
    from .sources.datatable import parse_series, parse_world_table
    pts = []
    for s in parse_series(summary):
        code = code_of(s["label"])
        if code and s["xs"]:
            for i in sorted({0, len(s["xs"]) - 1}):
                pts.append((s["label"], code, s["xs"][i], s["ys"][i]))
    world = parse_world_table(summary)
    if world:
        items = sorted(world["items"], key=lambda it: it["value"])
        for it in (items[-1], items[0]):
            code = code_of(it["label"])
            if code:
                pts.append((it["label"], code, world["year"], it["value"]))
    seen, out = set(), []
    for p in pts:                            # bỏ trùng, giữ thứ tự
        if (p[1], p[2]) not in seen:
            seen.add((p[1], p[2]))
            out.append(p)
    return out[:limit]


def indicator_code(summary: str):
    m = re.search(r"mã ([A-Z]{2}\.[A-Z0-9.]+[A-Z0-9])", summary or "")
    return m.group(1) if m else None


def scale_for(summary: str, cfg: dict) -> float:
    """Hệ số chia của chỉ số trong config (vd dân số: 1.000.000 -> tóm tắt ghi "triệu người")."""
    code = indicator_code(summary)
    for ind in ((cfg.get("sources") or {}).get("worldbank") or {}).get("indicators") or []:
        if ind.get("code") == code:
            return float(ind.get("scale", 1) or 1)
    return 1.0


def review_line(result: dict) -> str:
    """Một dòng cho tin nhắn duyệt trên Telegram."""
    icon = {"ok": "✅", "warn": "⚠️"}.get(result.get("status"), "ℹ️")
    return f"{icon} Nguồn 2: {result.get('summary', 'chưa đối chiếu')}"


def check(idea: dict, scale: float = 1.0, fetch=fetch_table) -> dict:
    """Đối chiếu ý tưởng số liệu với OWID. -> {"status", "summary", "source", "url", "checks"}.
    status: "ok" (mọi điểm khớp), "warn" (có điểm lệch), "none" (không đối chiếu được)."""
    from .sources.datatable import OWID_SOURCE, is_data_source
    if not is_data_source(idea.get("source_name")):
        return {"status": "none", "summary": "bài báo — chưa có nguồn thứ hai tự động (cần tìm kiếm web)"}
    if idea.get("source_name") == OWID_SOURCE:
        # Số lấy thẳng từ OWID, mà OWID chỉ tổng hợp lại từ cơ quan gốc ghi trong tóm tắt
        # (FAO, IEA, Global Carbon Budget...) -> chưa có nguồn thứ hai độc lập để đối chiếu tự động
        m = re.search(r"số liệu gốc: (.+?)\)\.", idea.get("summary") or "")   # owid.source_line
        origin = f" (gốc: {m.group(1)})" if m else ""
        return {"status": "none", "summary": f"số lấy thẳng từ Our World in Data{origin} — chưa có nguồn"
                                             " thứ hai độc lập"}
    code = indicator_code(idea.get("summary"))
    if code not in OWID:
        return {"status": "none", "summary": f"chỉ số {code or '?'} chưa có nguồn thứ hai độc lập trên OWID"}
    slug, factor, origin = OWID[code]
    try:
        table = fetch(slug)
    except Exception as exc:                  # mạng lỗi không được chặn kịch bản
        log.warning("Không tải được OWID %s: %s", slug, exc)
        return {"status": "none", "summary": f"không tải được Our World in Data ({type(exc).__name__})"}
    checks = []
    for label, iso, year, ours in data_points(idea.get("summary")):
        # Chuỗi Liên Hợp Quốc thường chậm hơn World Bank một năm (đo 12/11: tuổi thọ OWID tới 2023,
        # World Bank đã có 2024) -> thiếu đúng năm thì so với năm liền trước/sau, ghi rõ năm đã so
        their_year = next((y for y in (year, year - 1, year + 1) if (iso, y) in table), None)
        if their_year is None:
            continue
        theirs = table[(iso, their_year)] * factor / (scale or 1.0)
        diff = abs(theirs - ours) / max(abs(ours), 1e-9)
        status = "khớp" if diff <= MATCH else "lệch nhẹ" if diff <= SMALL else "lệch lớn"
        checks.append({"label": label, "year": year, "their_year": their_year, "ours": ours,
                       "theirs": round(theirs, 3), "diff_pct": round(100 * diff, 1), "status": status})
    if not checks:
        return {"status": "none", "summary": "OWID chưa có số cùng nước, cùng năm để đối chiếu"}
    ok = sum(c["status"] == "khớp" for c in checks)
    big = [c for c in checks if c["status"] == "lệch lớn"]
    summary = f"{ok}/{len(checks)} điểm khớp với Our World in Data (gốc: {origin})"
    if big:
        summary += "; LỆCH LỚN: " + ", ".join(f"{c['label']} {c['year']} ({c['diff_pct']}%)" for c in big)
    return {"status": "ok" if ok == len(checks) else "warn", "summary": summary,
            "source": f"Our World in Data — {origin}", "url": GRAPHER.format(slug=slug), "checks": checks}
