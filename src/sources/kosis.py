"""Ý tưởng từ KOSIS — cổng thống kê quốc gia Hàn Quốc (cần KOSIS_API_KEY trong .env).

Góc "người Việt ở Hàn" mà ít kênh Việt có số liệu gốc. Hai dạng ý tưởng (config
sources.kosis.tables), tóm tắt viết theo khuôn chung của datatable.py nên biểu đồ đường,
cuộc đua, bản đồ đều lấy số thẳng từ bảng:
- nationality_race: cộng đồng người nước ngoài ở Hàn Quốc xếp hạng theo quốc tịch qua các năm.
- vietnam_by_category: người Việt ở Hàn Quốc chia theo một phân loại (ví dụ loại visa).

Không mã hoá cứng mã phân loại: đọc "metadata" của bảng rồi tự tìm chiều quốc tịch (chiều
có mục "베트남"), chiều phân loại (theo tên chiều) và các mục tổng ("계", "합계", "총계").
Không có key thì trả về danh sách rỗng — dây chuyền vẫn chạy với các nguồn khác.
"""
import logging
import os
import re
import time
from datetime import date

import requests

from .. import lang
from .datatable import KOSIS_SOURCE, race_lines, race_years, vn_number

log = logging.getLogger(__name__)

SOURCE_NAME = KOSIS_SOURCE
META_URL = "https://kosis.kr/openapi/statisticsData.do"
DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
PAGE = "https://kosis.kr/statHtml/statHtml.do?orgId={org}&tblId={tbl}#nam-{end}"
TIMEOUTS = (60, 90)
RETRY_PAUSE = 10
TOTAL_NAMES = {"계", "합계", "총계"}

# Tên quốc tịch tiếng Hàn -> tiếng Việt (tên tiếng Việt khớp src/render/geo.py để lên bản đồ).
# Quốc tịch không có trong bảng này thì bỏ qua (không bịa tên dịch).
KO_VI = {
    "베트남": "Việt Nam", "중국": "Trung Quốc", "한국계중국인": "Trung Quốc gốc Hàn",
    "네팔": "Nepal", "우즈베키스탄": "Uzbekistan", "캄보디아": "Campuchia",
    "인도네시아": "Indonesia", "미얀마": "Myanmar", "필리핀": "Philippines",
    "타이(태국)": "Thái Lan", "몽골": "Mông Cổ", "미국": "Mỹ", "스리랑카": "Sri Lanka",
    "방글라데시": "Bangladesh", "카자흐스탄": "Kazakhstan", "일본": "Nhật Bản",
    "타이완(대만)": "Đài Loan", "러시아(연방)": "Nga", "한국계러시아인": "Nga gốc Hàn",
    "캐나다": "Canada", "파키스탄": "Pakistan", "인도": "Ấn Độ", "키르기즈": "Kyrgyzstan",
    "라오스": "Lào", "동티모르": "Đông Timor", "호주": "Úc", "영국": "Anh", "프랑스": "Pháp",
    "독일": "Đức", "말레이시아": "Malaysia", "싱가포르": "Singapore", "홍콩": "Hồng Kông",
    "타지키스탄": "Tajikistan", "투르크메니스탄": "Turkmenistan", "아프가니스탄": "Afghanistan",
}

# Loại visa: mã trong ngoặc của tên KOSIS ("비전문취업(E-9)") -> tên tiếng Việt
VISA_VI = {
    "E-9": "Lao động phổ thông (E-9)", "F-6": "Kết hôn (F-6)", "D-2": "Du học (D-2)",
    "D-4": "Học tiếng và đào tạo (D-4)", "C-3": "Lưu trú ngắn hạn (C-3)",
    "F-1": "Thăm thân (F-1)", "E-8": "Lao động thời vụ (E-8)",
    "E-7": "Lao động chuyên ngành (E-7)", "D-10": "Tìm việc (D-10)",
    "E-10": "Thuyền viên (E-10)", "F-2": "Cư trú (F-2)", "F-3": "Người đi kèm (F-3)",
    "F-5": "Thường trú (F-5)", "H-2": "Thăm thân kết hợp làm việc (H-2)",
    "F-4": "Kiều bào (F-4)", "B-1": "Miễn thị thực (B-1)", "B-2": "Quá cảnh (B-2)",
    "G-1": "Diện khác (G-1)", "D-8": "Đầu tư (D-8)", "E-2": "Giảng dạy ngoại ngữ (E-2)",
    "D-7": "Thuyên chuyển nội bộ (D-7)", "D-9": "Kinh doanh thương mại (D-9)",
}


def api_key() -> str:
    return os.getenv("KOSIS_API_KEY", "")


def _get(url: str, **params):
    params.update(apiKey=api_key(), format="json", jsonVD="Y")
    r = None
    for k, wait in enumerate(TIMEOUTS):
        try:
            r = requests.get(url, params=params, timeout=wait)
            break
        except (requests.Timeout, requests.ConnectionError):
            if k == len(TIMEOUTS) - 1:
                raise
            time.sleep(RETRY_PAUSE)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and (data.get("err") or data.get("errMsg")):
        # Lỗi của KOSIS đến dưới dạng JSON {"err": ..., "errMsg": ...}; không in key
        raise RuntimeError(f"KOSIS lỗi {data.get('err')}: {data.get('errMsg')}")
    return data


def table_meta(org: str, tbl: str) -> dict:
    """{mã chiều: [(mã mục, tên mục), ...]} — "ITEM" là chiều chỉ tiêu."""
    dims = {}
    for m in _get(META_URL, method="getMeta", type="ITM", orgId=org, tblId=tbl):
        dims.setdefault(m["OBJ_ID"], []).append((m["ITM_ID"], m["ITM_NM"]))
    return dims


def total_of(items: list) -> str:
    return next((i for i, n in items if n in TOTAL_NAMES), items[0][0])


def fetch_table(org: str, tbl: str, dims: dict, pick: dict, start: int, end: int, item: str = None) -> list:
    """Lấy dữ liệu theo năm. pick: {mã chiều: mã mục hoặc "ALL"}; chiều không nêu = mục tổng; item: mã chỉ tiêu
    (thiếu = chỉ tiêu đầu tiên). -> các dòng thô của KOSIS (C1..Cn, C1_NM..., PRD_DE, DT, UNIT_NM)."""
    order = [d for d in dims if d != "ITEM"]
    params = dict(method="getList", orgId=org, tblId=tbl, itmId=item or dims["ITEM"][0][0], prdSe="Y",
                  startPrdDe=str(start), endPrdDe=str(end))
    for k, d in enumerate(order, 1):
        params[f"objL{k}"] = pick.get(d, total_of(dims[d]))
    rows = _get(DATA_URL, **params)
    return rows if isinstance(rows, list) else []


def by_dimension(rows: list, dims: dict, dim: str) -> dict:
    """{tên mục của chiều `dim`: [(năm, giá trị), ...]} — bỏ ô trống."""
    order = [d for d in dims if d != "ITEM"]
    key = f"C{order.index(dim) + 1}"
    out = {}
    for r in rows:
        v = str(r.get("DT", "")).replace(",", "")
        if v in ("", "-"):
            continue
        out.setdefault(r[f"{key}_NM"], []).append((int(r["PRD_DE"]), float(v)))
    return {n: sorted(s) for n, s in out.items()}


def find_dim(dims: dict, has_item: str) -> str:
    """Mã chiều có một mục tên `has_item` (ví dụ chiều quốc tịch có mục "베트남"), hoặc None."""
    return next((d for d, items in dims.items()
                 if d != "ITEM" and any(n == has_item for _, n in items)), None)


def is_aggregate(name: str) -> bool:
    """Dòng gộp (tổng, tổng châu lục) — không phải một quốc tịch."""
    return name in TOTAL_NAMES or name.endswith("계") or "난민" in name


def build_nationality_race(t: dict, today: date = None):
    """Cuộc đua các cộng đồng người nước ngoài ở Hàn Quốc theo quốc tịch."""
    end = (today or date.today()).year
    dims = table_meta(t["org"], t["tbl"])
    nat = find_dim(dims, "베트남")
    if not nat:
        return None
    rows = fetch_table(t["org"], t["tbl"], dims, {nat: "ALL"}, int(t.get("start", 2010)), end)
    raw = by_dimension(rows, dims, nat)
    # kênh Việt: tên tiếng Việt (KO_VI); kênh Hàn: giữ tên gốc của KOSIS. Chỉ nhận quốc tịch có trong KO_VI.
    label = (lambda k: k) if lang.code() == "ko" else (lambda k: KO_VI[k])
    named = {label(k): v for k, v in raw.items() if not is_aggregate(k) and k in KO_VI}
    if not named:
        return None
    latest = max(y for s in named.values() for y, _ in s)
    top = sorted(named, key=lambda n: -dict(named[n]).get(latest, 0))[:int(t.get("top", 10))]
    series = {n: named[n] for n in top}
    years = race_years(series, 1)                       # số chia theo quốc tịch thường chỉ vài năm
    if len(series) < 3 or len(years) < 2:
        return None
    y0, y1 = years[0], years[-1]
    unit = t.get("unit", lang.pick(vi="người", ko="명"))
    lines = [lang.pick(
        vi=f"Chỉ số: {t['name']} ({unit}). Nguồn: KOSIS — {t.get('org_name', 'Hàn Quốc')},"
           f" bảng {t['org']}/{t['tbl']}. Cuộc đua giữa {len(series)} quốc tịch, từ {y0} đến {y1}.",
        ko=f"지표: {t['name']}({unit}). 출처: KOSIS — {t.get('org_name', '통계청')},"
           f" 표 {t['org']}/{t['tbl']}. {len(series)}개 국적의 순위 경쟁, {y0}–{y1}년.")]
    lines += race_lines(series, years, [n for n in t.get("focus", ["Việt Nam"]) if n in series])
    # Cách đếm của KOSIS dễ làm kể sai: Trung Quốc và Trung Quốc gốc Hàn là HAI dòng riêng
    cn_name, cn_kr_name = lang.pick(vi="Trung Quốc", ko="중국"), lang.pick(vi="Trung Quốc gốc Hàn", ko="한국계중국인")
    cn, cn_kr = dict(series.get(cn_name, [])), dict(series.get(cn_kr_name, []))
    if y1 in cn and y1 in cn_kr:
        total = vn_number(cn[y1] + cn_kr[y1])
        lines.insert(1, lang.pick(
            vi=f"Lưu ý cách đếm: KOSIS tách \"Trung Quốc\" và \"Trung Quốc gốc Hàn\" thành hai"
               f" dòng; gộp lại năm {y1} là {total} người. Khi so sánh phải nói rõ đang tách hay gộp.",
            ko=f"집계 주의: KOSIS는 '중국'과 '한국계중국인'을 따로 집계함; {y1}년 합치면 {total}명."
               f" 비교할 때 나눈 수치인지 합친 수치인지 밝혀야 함."))
    return {
        "title": lang.pick(vi=f"{t['name']}: cuộc đua theo quốc tịch từ {y0} đến {y1}",
                           ko=f"{t['name']}: 국적별 순위 경쟁, {y0}–{y1}년"),
        "summary": "\n".join(lines),
        "url": PAGE.format(org=t["org"], tbl=t["tbl"], end=y1),
        "source": SOURCE_NAME,
        "lang": lang.code(),
    }


def visa_label(name: str):
    m = re.search(r"\(([A-Z]-\d+)\)", name)
    return VISA_VI.get(m.group(1)) if m else None


def build_vietnam_by_category(t: dict, today: date = None):
    """Người Việt ở Hàn Quốc chia theo một phân loại (mặc định: loại visa)."""
    end = (today or date.today()).year
    dims = table_meta(t["org"], t["tbl"])
    nat = find_dim(dims, "베트남")
    cat = next((d for d in dims if d not in ("ITEM", nat)
                and any(visa_label(n) for _, n in dims[d])), None)
    if not (nat and cat):
        return None
    vn_code = next(i for i, n in dims[nat] if n == "베트남")
    rows = fetch_table(t["org"], t["tbl"], dims, {nat: vn_code, cat: "ALL"}, int(t.get("start", 2010)), end)
    raw = by_dimension(rows, dims, cat)
    total = next((raw[k] for k in raw if k in TOTAL_NAMES), None)
    named = {visa_label(k): v for k, v in raw.items() if visa_label(k)}
    if not named or not total:
        return None
    latest = max(y for s in named.values() for y, _ in s)
    top = sorted(named, key=lambda n: -dict(named[n]).get(latest, 0))[:int(t.get("top", 8))]
    series = {n: named[n] for n in top}
    years = race_years(series, 1)
    if len(series) < 3 or len(years) < 2:
        return None
    y0, y1 = years[0], years[-1]
    tot = dict(total)
    lines = [f"Chỉ số: {t['name']} ({t.get('unit', 'người')}). Nguồn: KOSIS — {t.get('org_name', 'Hàn Quốc')},"
             f" bảng {t['org']}/{t['tbl']}, từ {y0} đến {y1}."]
    if y0 in tot and y1 in tot:
        lines.append(f"Tổng số người Việt: năm {y0} là {vn_number(tot[y0])}; năm {y1} là {vn_number(tot[y1])}.")
        shares = "; ".join(f"{n} {vn_number(dict(series[n])[y1] / tot[y1] * 100)}%" for n in top[:4])
        lines.append(f"Tỷ trọng năm {y1}: {shares}.")
    lines += race_lines(series, years, [])
    return {
        "title": f"{t['name']} từ {y0} đến {y1}",
        "summary": "\n".join(lines),
        "url": PAGE.format(org=t["org"], tbl=t["tbl"], end=y1),
        "source": SOURCE_NAME,
        "lang": "vi",
    }


# ------------------------------------------------------------- bản đồ 17 시도 (kênh Hàn, 24/11/2026)
# Một chỉ số theo tỉnh/thành (출산율, 고령인구비율, 1인당 GRDP...) -> ý tưởng "bản đồ Hàn Quốc": nơi cao nhất / thấp
# nhất, Seoul đứng đâu, so với cả nước. Bảng có chiều vùng (nhận ra nhờ mục "서울특별시"); bảng cấp 시군구 (261 mục)
# cũng dùng được — chỉ giữ mục khớp tên 시도 (src/render/geo.py, assets/geo/kr_provinces.json).
MIN_PROVINCES = 16
MIN_SGG = 200               # bản đồ 시군구: năm có số cho ít nhất chừng này vùng (bản đồ có 228 vùng)
SGG_LIST = 10               # tóm tắt chỉ liệt kê 10 nơi cao nhất + 10 nơi thấp nhất (cả bảng nằm ở dòng bảng cuối)
SEOUL = "KR-11"


def _province_series(raw: dict) -> tuple:
    """{tên KOSIS: chuỗi} -> ({mã 시도: chuỗi}, chuỗi cả nước). Hai tên của cùng một tỉnh (강원도 / 강원특별자치도 —
    đổi tên năm 2023) gộp thành một chuỗi, tên mới chồng lên tên cũ."""
    from ..render.geo import code_of, is_province
    out = {}
    for name, series in sorted(raw.items(), key=lambda kv: "특별자치" in kv[0]):
        code = code_of(name)
        if is_province(code):
            merged = dict(out.get(code) or [])
            merged.update(dict(series))
            out[code] = sorted(merged.items())
    return out, raw.get("전국")


def _sgg_series(rows: list, dims: dict, dim: str) -> tuple:
    """Dòng KOSIS cấp 시군구 -> ({mã vùng bản đồ "SGG:서울 중구": chuỗi}, chuỗi cả nước). Đọc theo MÃ mục (tên "중구" trùng ở
    6 thành phố); mục không có trên bản đồ (đơn vị cũ, 구 không tự trị, 구 mới 2026 của Incheon) bị bỏ."""
    from ..render.geo import kosis_sgg_label, sgg_code
    order = [d for d in dims if d != "ITEM"]
    key = f"C{order.index(dim) + 1}"
    out, national = {}, {}
    for r in rows:
        v = str(r.get("DT", "")).replace(",", "")
        if v in ("", "-"):
            continue
        code, year = str(r[key]), int(r["PRD_DE"])
        if code == "00":
            national[year] = float(v)
            continue
        label = kosis_sgg_label(code, r[f"{key}_NM"])
        if label:
            out.setdefault(sgg_code(label), {})[year] = float(v)
    return {c: sorted(s.items()) for c, s in out.items()}, sorted(national.items())


def build_province_map(t: dict, today: date = None):
    """Một chỉ số theo 17 시도 (level "sido", mặc định) hoặc ~229 시군구 (level "sgg") -> ý tưởng bản đồ Hàn Quốc (chỉ kênh
    Hàn: tên vùng, cách nói đều là tiếng Hàn)."""
    import statistics
    from collections import Counter
    from ..render.geo import display_name, load_map
    from .datatable import (SGG_TABLE_KO, beats_lines, ranks_desc, ratio_phrase, region_table_line, relatable_line,
                            series_line, shown_value, story_beats)
    if lang.code() != "ko":
        return None
    end = (today or date.today()).year
    dims = table_meta(t["org"], t["tbl"])
    region = find_dim(dims, "서울특별시")
    if not region:
        return None
    item = next((i for i, n in dims["ITEM"] if t.get("item") and n.startswith(t["item"])), None)
    pick = {region: "ALL"}
    for d, want in (t.get("pick") or {}).items():           # chiều phụ chọn theo TÊN mục
        code = next((i for i, n in dims.get(d, []) if n == want), None)
        if code:
            pick[d] = code
    rows = fetch_table(t["org"], t["tbl"], dims, pick, int(t.get("start", end - 15)), end, item)
    scale = float(t.get("scale", 1))
    sgg = t.get("level") == "sgg"
    if sgg:
        named, national = _sgg_series(rows, dims, region)
        named = {c: [(y, v * scale) for y, v in s] for c, s in named.items()}
        national = [(y, v * scale) for y, v in national]
    else:
        raw = {k: [(y, v * scale) for y, v in s] for k, s in by_dimension(rows, dims, region).items()}
        named, national = _province_series(raw)
    if t.get("national") is False:      # chỉ số mà cả nước luôn = 0 (순이동률: người đi = người đến) — bỏ dòng 전국
        national = None
    need = MIN_SGG if sgg else MIN_PROVINCES
    has = lambda y: sum(1 for s in named.values() if y in dict(s)) >= need
    years = sorted({y for s in named.values() for y, _ in s})
    year = next((y for y in reversed(years) if has(y)), None)
    if year is None:
        return None
    table = {c: dict(s)[year] for c, s in named.items() if year in dict(s)}
    nat = dict(national or []).get(year)
    unit, name, k = t.get("unit", ""), t["name"], lang.josa
    val = lambda v: lang.with_unit(vn_number(v), unit)
    nm = {c: display_name(c) for c in named}
    n = len(table)
    rank = ranks_desc(table)
    order = sorted(table, key=lambda c: -table[c])
    top, bottom = order[0], order[-1]
    level = "시군구" if sgg else "시도"
    lines = [f"지표: {name}({unit}). 출처: KOSIS — {t.get('org_name', '통계청')}, 표 {t['org']}/{t['tbl']}."
             f" {year}년: {n}개 {level} 수치 있음."]
    if nat is not None:
        lines.append(f"{year}년 전국: {val(nat)}.")
    if sgg:
        lines.append(f"{year}년 시군구 상위 {SGG_LIST}곳: "
                     + "; ".join(f"{rank[c]}. {nm[c]} — {val(table[c])}" for c in order[:SGG_LIST]) + ".")
        lines.append(f"{year}년 시군구 하위 {SGG_LIST}곳(낮은 순): "
                     + "; ".join(f"{nm[c]} — {val(table[c])}" for c in reversed(order[-SGG_LIST:])) + ".")
    else:
        lines.append(f"{year}년 시도별 순위(높은 순): "
                     + "; ".join(f"{rank[c]}. {nm[c]} — {val(table[c])}" for c in order) + ".")
    lines.append(f"가장 높은 곳: {nm[top]} {val(table[top])}; 가장 낮은 곳: {nm[bottom]} {val(table[bottom])}.")
    if not sgg and SEOUL in table and SEOUL not in (top, bottom):
        lines.append(f"서울: {n}개 시도 중 높은 순으로 {rank[SEOUL]}위 ({val(table[SEOUL])}).")
    if nat is not None:
        above = [nm[c] for c in order if table[c] > nat]
        lines.append(f"전국 수치보다 높은 {level}: {len(above)}곳"
                     + (f" ({', '.join(above)})." if 0 < len(above) <= 8 else "."))
    if unit.startswith("%"):            # hiệu hai tỷ lệ % là điểm phần trăm (%p), trừ trên số đã làm tròn như được đọc
        gap = round(shown_value(table[top]) - shown_value(table[bottom]), 6)
        beats = [f"{year}년 {k(nm[top], '은/는')} {nm[bottom]}보다 {vn_number(gap)}%p 높음"]
    else:
        beats = [ratio_phrase(nm[top], table[top], nm[bottom], table[bottom], 1.2)]
    if not sgg and SEOUL in table and nat is not None:
        beats.append(ratio_phrase("서울", table[SEOUL], "전국", nat, 1.2)
                     or ratio_phrase("전국", nat, "서울", table[SEOUL], 1.2))
    beats.append(f"{level} 중앙값: {val(statistics.median(table.values()))}")
    if sgg:          # nơi cao / thấp tập trung ở tỉnh nào (đếm bằng code — model hay tự khái quát "주로 지방")
        units = load_map("kr_sgg")["countries"]
        short = {c: p["name"] for c, p in load_map("kr")["countries"].items()}
        for part, word in ((order[:20], "상위"), (order[-20:], "하위")):
            (prov, cnt), = Counter(units[c]["province"] for c in part).most_common(1)
            if cnt >= 5:
                beats.append(f"{word} 20곳 중 {cnt}곳이 {short[prov]}")
    # thứ hạng đổi nhiều nhất so với ~10 năm trước (năm sớm nhất cũng đủ tỉnh có số)
    first = next((y for y in years if y <= year - 5 and has(y)), None)
    if first:
        old = {c: dict(s)[first] for c, s in named.items() if first in dict(s) and c in table}
        r0 = ranks_desc(old)
        moves = sorted((r0[c] - rank[c], c) for c in old)
        for (d, c), word in ((moves[-1], "상승"), (moves[0], "하락")):
            if abs(d) >= (30 if sgg else 3):
                beats.append(f"순위 {word}폭 최대: {nm[c]} — {first}년 {r0[c]}위({val(old[c])}) → {year}년"
                             f" {rank[c]}위({val(table[c])})")
    hist = {}
    if national:
        hist["전국"] = [p for p in national if p[0] <= year]
    if not sgg and SEOUL in named:
        hist["서울"] = [p for p in named[SEOUL] if p[0] <= year]
    beats += story_beats(hist, list(hist), unit) if hist else []
    relate = relatable_line([(nm[top], table[top]), (nm[bottom], table[bottom])], unit, t)
    if relate:
        lines.append(relate)
    lines += beats_lines([b for b in beats if b])
    chart = [("전국", national or []), (nm[top], named[top])] + (
        [(nm[bottom], named[bottom])] if sgg else [("서울", named[SEOUL])] if SEOUL in named and SEOUL != top else [])
    for lab, s in chart:                  # chuỗi theo năm -> biểu đồ đường (cả nước, nơi cao nhất, Seoul)
        s = [p for p in s if p[0] <= year]
        picks = [p for i, p in enumerate(s) if p[0] % 5 == 0 or i in (0, len(s) - 1)]
        if len(picks) >= 2:
            lines.append(series_line(lab, picks))
    lines.append(region_table_line(year, {nm[c]: v for c, v in table.items()}, nat,
                                   **({"marker": SGG_TABLE_KO} if sgg else {})))
    return {
        "title": f"한국 지도: {year}년 {level}별 {name} — 1위 {nm[top]}, 최하위 {nm[bottom]}",
        "summary": "\n".join(lines),
        "url": PAGE.format(org=t["org"], tbl=t["tbl"], end=year),
        "source": SOURCE_NAME,
        "lang": lang.code(),
    }


# ------------------------------------------------------------- số mới công bố theo tháng (kênh Hàn, 24/11/2026)
# Du chốt "phát triển sâu ngách": video NGAY khi cơ quan thống kê công bố số tháng mới — báo chí chỉ có bài chữ, kênh khác
# không tự động làm được bản đồ + biểu đồ trong ngày. Mỗi ngày kiểm từng bảng theo tháng (rẻ: 1-2 lệnh KOSIS); có tháng
# MỚI hơn lần trước (state `kosis_seen_<bảng>`) thì ra một ý tưởng có dấu "신규 공표" (datatable.FRESH_MARK) — main đưa
# thẳng vào ứng viên + cộng điểm, daily dựng trước. Bản đồ: số đếm (출생아 수...) tô theo % THAY ĐỔI so với cùng tháng năm
# trước (`map_value: yoy` — tô số tuyệt đối thì chỉ thấy tỉnh đông dân), tỷ lệ (고용률...) tô theo chính tỷ lệ.
MONTHS_BACK = 121              # 10 năm + 1 tháng: đủ "cùng tháng qua 10 năm" cho biểu đồ đường


def _monthly_rows(t: dict, dims: dict, region: str) -> list:
    order = [d for d in dims if d != "ITEM"]
    item = next((i for i, n in dims["ITEM"] if t.get("item") and n.startswith(t["item"])), dims["ITEM"][0][0])
    params = dict(method="getList", orgId=t["org"], tblId=t["tbl"], itmId=item, prdSe="M",
                  newEstPrdCnt=str(MONTHS_BACK))
    for k, d in enumerate(order, 1):
        want = (t.get("pick") or {}).get(d)
        code = next((i for i, n in dims[d] if n == want), None) if want else None
        params[f"objL{k}"] = "ALL" if d == region else (code or total_of(dims[d]))
    rows = _get(DATA_URL, **params)
    return rows if isinstance(rows, list) else []


def _seen(key: str, value: str = None):
    """Tháng mới nhất đã ra ý tưởng của một bảng (bảng state trong DB của kênh). value != None -> ghi."""
    from .. import db
    con = db.connect()
    try:
        if value is None:
            return db.get_state(con, key)
        db.set_state(con, key, value)
    finally:
        con.close()


def build_monthly_map(t: dict, today: date = None, force: bool = False):
    """Bảng KOSIS theo tháng + theo tỉnh -> ý tưởng "이번 달 통계" khi có tháng MỚI (force: bỏ qua kiểm tháng đã thấy)."""
    import statistics
    from ..render.geo import display_name
    from .datatable import (FRESH_MARK, beats_lines, ranks_desc, ratio_phrase, region_table_line, series_line,
                            shown_value)
    if lang.code() != "ko":
        return None
    dims = table_meta(t["org"], t["tbl"])
    region = find_dim(dims, "서울특별시")
    if not region:
        return None
    rows = _monthly_rows(t, dims, region)
    scale = float(t.get("scale", 1))
    raw = {k: [(y, v * scale) for y, v in s] for k, s in by_dimension(rows, dims, region).items()}
    named, national = _province_series(raw)
    national = national or raw.get("계")
    months = sorted({m for s in named.values() for m, _ in s})
    has = lambda m: sum(1 for s in named.values() if m in dict(s)) >= MIN_PROVINCES - 1     # 15: Gwangju/Jeonnam gộp
    latest = next((m for m in reversed(months) if has(m)), None)
    if latest is None:
        return None
    key = f"kosis_seen_{t['tbl']}_{t.get('item') or ''}_{'_'.join((t.get('pick') or {}).values())}"
    seen = _seen(key)
    if not force and not seen:
        # LẦN ĐẦU gặp bảng: chỉ ghi mốc. Tháng đang có có thể đã công bố từ lâu (số sinh tháng 8 công bố cuối tháng 10)
        # — "số mới" là tháng xuất hiện SAU mốc này.
        _seen(key, str(latest))
        return None
    if not force and str(seen) >= str(latest):
        return None                                        # tháng này đã ra ý tưởng rồi
    y, m = divmod(latest, 100)
    prev = latest - 100                                    # cùng tháng năm trước
    unit, name, k = t.get("unit", ""), t["name"], lang.josa
    pct_unit = unit.startswith("%")
    val = lambda v: lang.with_unit(vn_number(v), unit)
    nat = dict(national or [])
    cur = {c: dict(s)[latest] for c, s in named.items() if latest in dict(s)}
    old = {c: dict(s)[prev] for c, s in named.items() if prev in dict(s)}

    def change(a, b):                                      # (giá trị thay đổi, chữ): %p với tỷ lệ, % với số đếm
        if pct_unit:
            d = round(shown_value(a) - shown_value(b), 6)
            return d, f"{'+' if d > 0 else ''}{vn_number(d)}%p"
        d = (a - b) / b * 100 if b else 0.0
        return d, f"{'+' if d > 0 else ''}{vn_number(d)}%"
    yoy = {c: change(cur[c], old[c]) for c in cur if c in old and (pct_unit or old[c])}
    yoy_map = t.get("map_value") == "yoy"
    table = {c: yoy[c][0] for c in yoy} if yoy_map else cur
    if len(table) < MIN_PROVINCES - 1:
        return None
    nm = {c: display_name(c) for c in named}
    order = sorted(table, key=lambda c: -table[c])
    rank = ranks_desc(table)
    top, bottom = order[0], order[-1]
    map_unit = "%p" if (yoy_map and pct_unit) else ("%" if yoy_map else unit)
    lines = [f"지표: {name}({unit}). 출처: KOSIS — {t.get('org_name', '통계청')}, 표 {t['org']}/{t['tbl']}."
             f" {y}년 {m}월 수치.",
             f"{FRESH_MARK}: {y}년 {m}월 통계가 새로 공표됨 (공표 확인 {(today or date.today()).isoformat()})."
             f" 가장 최근 수치이므로 '{y}년 {m}월'을 분명히 말할 것."]
    if latest in nat:
        line = f"{y}년 {m}월 전국: {val(nat[latest])}"
        if prev in nat and (pct_unit or nat[prev]):
            line += f" — 1년 전({y - 1}년 {m}월 {val(nat[prev])})보다 {change(nat[latest], nat[prev])[1]}"
        lines.append(line + ".")
    up = sum(1 for c in yoy if yoy[c][0] > 0)
    down = sum(1 for c in yoy if yoy[c][0] < 0)
    more, less = ("높아진", "낮아진") if pct_unit else ("늘어난", "줄어든")
    lines.append(f"{len(yoy)}개 시도 중 1년 전 같은 달보다 {more} 곳 {up}곳, {less} 곳 {down}곳.")
    lines.append(f"{y}년 {m}월 시도별 수치(높은 순): " + "; ".join(
        f"{nm[c]} {val(cur[c])}" + (f" ({yoy[c][1]})" if c in yoy else "")
        for c in sorted(cur, key=lambda c: -cur[c])) + ".")
    if yoy_map:
        lines.append(f"1년 전 같은 달 대비 변화 순위: 1위 {nm[top]} {yoy[top][1]}; 최하위 {nm[bottom]} {yoy[bottom][1]}.")
    beats = []
    hi_c, lo_c = max(cur, key=cur.get), min(cur, key=cur.get)
    if yoy_map:
        pass            # số đếm: tỉnh đông dân luôn nhiều hơn ("경기는 세종의 29.4배") — vô nghĩa, kể bằng % thay đổi
    elif pct_unit:
        beats.append(f"{y}년 {m}월 {k(nm[hi_c], '은/는')} {nm[lo_c]}보다 "
                     f"{vn_number(round(shown_value(cur[hi_c]) - shown_value(cur[lo_c]), 6))}%p 높음")
    else:
        beats.append(ratio_phrase(nm[hi_c], cur[hi_c], nm[lo_c], cur[lo_c], 1.2))
    same = sorted((yy, v) for yy, v in ((mm // 100, v) for mm, v in nat.items() if mm % 100 == m))
    if len(same) >= 3:
        hi_y, lo_y = max(same, key=lambda p: p[1]), min(same, key=lambda p: p[1])
        if latest in nat and nat[latest] == hi_y[1]:
            beats.append(f"{m}월 기준 최근 {len(same)}년 중 가장 높음")
        elif latest in nat and nat[latest] == lo_y[1]:
            beats.append(f"{m}월 기준 최근 {len(same)}년 중 가장 낮음")
        else:
            beats.append(f"{m}월 기준 최근 {len(same)}년 최고 {hi_y[0]}년 {val(hi_y[1])}, 최저 {lo_y[0]}년 {val(lo_y[1])}")
    beats.append(f"시도 중앙값: {val(statistics.median(cur.values()))}")
    lines += beats_lines([b for b in beats if b])
    if len(same) >= 2:
        lines.append(series_line(f"전국 {m}월", same))           # 같은 달 10년 -> biểu đồ đường
    lines.append(region_table_line(y, {nm[c]: v for c, v in table.items()}, None if yoy_map else nat.get(latest),
                                   unit="전년 동월 대비 " + map_unit if yoy_map else unit, period=f"{y}년 {m}월"))
    _seen(key, str(latest))
    head = (f"전국 {val(nat[latest])}" if latest in nat else f"1위 {nm[top]}")
    return {
        "title": f"이번 달 통계: {y}년 {m}월 {name} — {head}",
        "summary": "\n".join(lines).replace(" ()", ""),
        "url": PAGE.format(org=t["org"], tbl=t["tbl"], end=latest),
        "source": SOURCE_NAME,
        "lang": lang.code(),
    }


BUILDERS = {"nationality_race": build_nationality_race, "vietnam_by_category": build_vietnam_by_category,
            "province_map": build_province_map}


def fetch_kosis(cfg: dict, today: date = None) -> list:
    if not api_key():
        log.info("Chưa có KOSIS_API_KEY — bỏ qua nguồn KOSIS")
        return []
    tables = cfg.get("tables") or []
    per_day = int(cfg.get("per_day", 1))
    if not tables or per_day <= 0:
        return []
    start = ((today or date.today()).toordinal() * per_day) % len(tables)
    items = []
    for k in range(min(per_day, len(tables))):
        t = tables[(start + k) % len(tables)]
        build = BUILDERS.get(t.get("kind"))
        if not build:
            log.warning("KOSIS: không biết dạng bảng %s", t.get("kind"))
            continue
        try:
            item = build(t, today)
        except Exception as exc:          # mạng chập chờn / KOSIS đổi cấu trúc: không sập pipeline
            log.warning("Bỏ qua bảng KOSIS %s/%s: %s", t.get("org"), t.get("tbl"), exc)
            continue
        if item:
            items.append(item)
            log.info("KOSIS %s: %s", t["tbl"], item["title"])
    for t in cfg.get("monthly") or []:          # số theo tháng: kiểm MỖI NGÀY, chỉ ra ý tưởng khi có tháng mới
        try:
            item = build_monthly_map(t, today)
        except Exception as exc:
            log.warning("Bỏ qua bảng tháng KOSIS %s: %s", t.get("tbl"), exc)
            continue
        if item:
            items.append(item)
            log.info("KOSIS số mới công bố %s: %s", t["tbl"], item["title"])
    return items
