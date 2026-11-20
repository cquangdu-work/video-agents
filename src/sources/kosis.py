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


def fetch_table(org: str, tbl: str, dims: dict, pick: dict, start: int, end: int) -> list:
    """Lấy dữ liệu theo năm. pick: {mã chiều: mã mục hoặc "ALL"}; chiều không nêu = mục tổng.
    -> các dòng thô của KOSIS (C1..Cn, C1_NM..., PRD_DE, DT)."""
    order = [d for d in dims if d != "ITEM"]
    params = dict(method="getList", orgId=org, tblId=tbl, itmId=dims["ITEM"][0][0], prdSe="Y",
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


BUILDERS = {"nationality_race": build_nationality_race, "vietnam_by_category": build_vietnam_by_category}


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
    return items
