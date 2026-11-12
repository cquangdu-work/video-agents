"""Ý tưởng "Việt Nam – Hàn Quốc qua một chỉ số" từ kho dữ liệu mở World Bank (không cần key).

Các nguồn khác đưa về BÀI BÁO có vài con số. Nguồn này đưa về chính BẢNG SỐ LIỆU:
mỗi chỉ số (GDP đầu người, tỷ suất sinh, tuổi thọ...) thành một ý tưởng, phần tóm tắt
là hồ sơ số liệu của hai nước qua các năm. Lợi ích:
- Biên kịch có sẵn hàng chục con số thật để viết, khỏi "chế" số;
- cổng chống bịa số (crew.unsourced_numbers) có đủ căn cứ để đối chiếu;
- agent Sản xuất có chuỗi số theo năm để vẽ biểu đồ đường, so găng;
- đúng "góc Việt–Hàn" của kênh, ít kênh Việt khai thác.

Mỗi ngày chỉ đưa vào `per_day` chỉ số, xoay vòng theo ngày, để kho ý tưởng không bị
ngập bởi một loại nội dung. Chỉ số đã vào kho rồi thì DB tự bỏ qua (trùng URL).
"""
import logging
import re
import time
from datetime import date

import requests

log = logging.getLogger(__name__)

SOURCE_NAME = "World Bank Open Data"     # src/main.py nhận ra tên này: tóm tắt CHÍNH LÀ nguồn
API = "https://api.worldbank.org/v2/country/{countries}/indicator/{code}"
PAGE = "https://data.worldbank.org/indicator/{code}?locations={locs}&end={end}"
HEADERS = {"User-Agent": "video-agents-pipeline/0.1"}
# Đo 12/11: URL truy vấn MỚI thì máy chủ treo hơn 60 giây, nhưng vẫn tính xong ở phía sau và
# lưu đệm — gọi lại sau ~20 giây là trả trong 0,1 giây. Nên lần đầu chỉ là "đánh thức".
TIMEOUTS = (20, 60, 60)      # giây chờ của từng lần gọi
RETRY_PAUSE = 25             # giây nghỉ giữa hai lần gọi


def vn_number(x: float) -> str:
    """Viết số kiểu Việt Nam, làm tròn vừa đủ để ĐỌC được: 36226.97 -> '36.227',
    83.74 -> '83,7', 0.721 -> '0,72'. Biên kịch chép nguyên dạng này vào lời đọc nên
    cổng chống bịa số khớp được từng chữ số."""
    a = abs(x)
    decimals = 0 if a >= 100 else 1 if a >= 10 else 2
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


def spoken_scale(x: float) -> str:
    """Số rất lớn kèm cách nói gọn: 100987686 -> ' (khoảng 101,0 triệu)'. Nhỏ thì rỗng."""
    for size, word in ((1e12, "nghìn tỷ"), (1e9, "tỷ"), (1e6, "triệu")):
        if abs(x) >= size:
            return f" (khoảng {vn_number(x / size)} {word})"
    return ""


def fetch_indicator(ind: dict, countries: list, default_start: int) -> dict:
    """fetch_series theo cấu hình của một chỉ số: năm bắt đầu riêng (`start_year`, ví dụ
    Internet năm 1990 gần như bằng 0 ở mọi nước, xếp hạng vô nghĩa) và hệ số chia
    (`scale`, ví dụ GDP 3.252.994.239.867 USD -> 3.253 tỷ USD, kèm unit "tỷ USD")."""
    series = fetch_series(ind["code"], countries, int(ind.get("start_year", default_start)))
    scale = float(ind.get("scale", 1) or 1)
    return {c: [(y, v / scale) for y, v in s] for c, s in series.items()}


def fetch_series(code: str, countries: list, start_year: int) -> dict:
    """-> {mã nước: [(năm, giá trị), ...] tăng dần theo năm}, bỏ các năm không có số."""
    url = API.format(countries=";".join(countries), code=code)
    params = {"format": "json", "per_page": 1000, "date": f"{start_year}:{date.today().year}"}
    r = None
    for k, wait in enumerate(TIMEOUTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=wait, params=params)
            break
        except (requests.Timeout, requests.ConnectionError):
            if k == len(TIMEOUTS) - 1:
                raise
            time.sleep(RETRY_PAUSE)
    r.raise_for_status()
    payload = r.json()
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and payload[1] else []
    series = {c: [] for c in countries}
    for row in rows:
        c, v = row.get("countryiso3code"), row.get("value")
        if c in series and v is not None:
            series[c].append((int(row["date"]), float(v)))
    return {c: sorted(v) for c, v in series.items()}


def catch_up_year(latest_a: float, series_b: list):
    """Nước A hôm nay "bằng" nước B của năm nào: năm mà giá trị của B gần giá trị hiện
    tại của A nhất, chỉ nhận khi lệch không quá 5%. Không có năm nào như vậy -> None.
    (Đây là "góc" hay nhất của dạng so sánh này: "Việt Nam hôm nay bằng Hàn Quốc năm 1987".)"""
    if not series_b or not latest_a:
        return None
    year, value = min(series_b[:-1] or series_b, key=lambda p: abs(p[1] - latest_a))
    return (year, value) if abs(value - latest_a) <= 0.05 * abs(latest_a) else None


def change_phrase(first: float, last: float) -> str:
    """Mô tả thay đổi từ số đầu tới số cuối bằng lời: 'tăng gấp 21,2 lần' / 'giảm 69,8%'."""
    if first <= 0 or last < 0:
        return ""
    ratio = last / first
    if ratio >= 2:
        return f"tăng gấp {vn_number(ratio)} lần"
    if ratio >= 1:
        return f"tăng {vn_number((ratio - 1) * 100)}%"
    return f"giảm {vn_number((1 - ratio) * 100)}%"


def build_item(ind: dict, countries: list, series: dict):
    """Một chỉ số + số liệu hai nước -> một ý tưởng thô {title, summary, url, source, lang}.
    countries: [{"iso3": "VNM", "iso2": "VN", "name": "Việt Nam"}, {...}].
    Trả về None nếu số liệu quá mỏng để kể thành chuyện."""
    ca, cb = countries[:2]
    (a, name_a), (b, name_b) = (ca["iso3"], ca["name"]), (cb["iso3"], cb["name"])
    sa, sb = series.get(a, []), series.get(b, [])
    if len(sa) < 5 or len(sb) < 5:
        return None
    unit = ind.get("unit", "")
    val = lambda v: f"{vn_number(v)} {unit}".strip() + spoken_scale(v)
    (ya0, va0), (ya1, va1) = sa[0], sa[-1]
    (yb0, vb0), (yb1, vb1) = sb[0], sb[-1]
    lines = [
        f"Chỉ số: {ind['name']} ({unit}). Nguồn: World Bank Open Data, mã {ind['code']}.",
        f"{name_a}: năm {ya0} là {val(va0)}; năm {ya1} là {val(va1)}.",
        f"{name_b}: năm {yb0} là {val(vb0)}; năm {yb1} là {val(vb1)}.",
    ]
    for name, (y0, v0), (y1, v1) in ((name_a, sa[0], sa[-1]), (name_b, sb[0], sb[-1])):
        phrase = change_phrase(v0, v1)
        if phrase:
            lines.append(f"Từ {y0} đến {y1}, {name} {phrase}.")
    if va1 and vb1 and min(va1, vb1) > 0:
        hi, lo = (name_b, name_a) if vb1 >= va1 else (name_a, name_b)
        lines.append(f"Số mới nhất: {hi} gấp {vn_number(max(va1, vb1) / min(va1, vb1))} lần {lo}.")
    match = catch_up_year(va1, sb)
    if match:
        lines.append(f"{name_a} năm {ya1} ({val(va1)}) tương đương {name_b} năm {match[0]}"
                     f" ({val(match[1])}) — cách nhau {ya1 - match[0]} năm.")
    # Bảng theo mốc 5 năm (kèm năm đầu và năm cuối) — đủ điểm để vẽ biểu đồ đường
    for name, s in ((name_a, sa), (name_b, sb)):
        picks = [p for i, p in enumerate(s) if p[0] % 5 == 0 or i in (0, len(s) - 1)]
        lines.append(f"{name} theo năm: " + "; ".join(f"{y}: {vn_number(v)}" for y, v in picks) + ".")
    return {
        "title": f"{ind['name']}: {name_a} và {name_b} từ {min(ya0, yb0)} đến {max(ya1, yb1)}",
        "summary": "\n".join(lines),
        # trang xem của World Bank dùng mã nước 2 chữ; &end= đổi khi có số liệu năm mới
        "url": PAGE.format(code=ind["code"], locs=f"{ca['iso2']}-{cb['iso2']}", end=max(ya1, yb1)),
        "source": SOURCE_NAME,
        "lang": "vi",
    }


def race_years(series: dict, step: int = 5) -> list:
    """Các mốc năm cho cuộc đua: những năm MỌI nước đều có số, lấy cách nhau `step` năm,
    luôn kèm năm đầu và năm cuối."""
    common = set.intersection(*[{y for y, _ in s} for s in series.values()]) if series else set()
    if not common:
        return []
    first, last = min(common), max(common)
    return sorted(y for y in common if y in (first, last) or y % step == 0)


def ranking(values: dict) -> list:
    """{tên nước: giá trị} -> danh sách tên nước xếp từ cao xuống thấp."""
    return [name for name, _ in sorted(values.items(), key=lambda kv: -kv[1])]


def build_race_item(ind: dict, countries: list, series: dict, focus: list, step: int = 5):
    """Một chỉ số + số liệu nhiều nước -> ý tưởng "cuộc đua" (thanh ngang đổi chỗ qua các năm).
    countries: [{"iso3", "iso2", "name"}, ...]; focus: mã iso3 các nước cần kể kỹ (Việt Nam, Hàn Quốc).
    None nếu dữ liệu không đủ cho một cuộc đua (dưới 3 nước hoặc dưới 4 mốc năm)."""
    names = {c["iso3"]: c["name"] for c in countries}
    series = {c: s for c, s in series.items() if c in names and s}
    years = race_years(series, step)
    if len(series) < 3 or len(years) < 4:
        return None
    at = {c: dict(s) for c, s in series.items()}                 # {mã: {năm: giá trị}}
    y0, y1 = years[0], years[-1]
    first = ranking({names[c]: at[c][y0] for c in series})
    last = ranking({names[c]: at[c][y1] for c in series})
    unit = ind.get("unit", "")
    rank_line = lambda y, order: f"Xếp hạng năm {y}: " + "; ".join(
        f"{k + 1}. {n} {vn_number(at[next(c for c in series if names[c] == n)][y])}"
        for k, n in enumerate(order)) + "."
    lines = [f"Chỉ số: {ind['name']} ({unit}). Nguồn: World Bank Open Data, mã {ind['code']}."
             f" Cuộc đua giữa {len(series)} nền kinh tế châu Á, từ {y0} đến {y1}.",
             rank_line(y0, first), rank_line(y1, last)]
    for code in focus:
        if code not in series:
            continue
        n = names[code]
        r0, r1 = first.index(n) + 1, last.index(n) + 1
        passed = [m for m in first[:r0 - 1] if last.index(m) > r1 - 1]       # trước ở trên, sau ở dưới
        lost = [m for m in first[r0:] if last.index(m) < r1 - 1]             # trước ở dưới, sau ở trên
        line = f"{n}: hạng {r0} năm {y0}, hạng {r1} năm {y1}"
        if passed:
            line += " — vượt " + ", ".join(passed)
        if lost:
            line += ("; " if passed else " — ") + "bị vượt bởi " + ", ".join(lost)
        lines.append(line + ".")
    for code in sorted(series, key=lambda c: -at[c][y1]):
        lines.append(f"{names[code]} theo năm: "
                     + "; ".join(f"{y}: {vn_number(at[code][y])}" for y in years) + ".")
    locs = "-".join(c["iso2"] for c in countries if c["iso3"] in series)
    name = ind["name"]
    first_word = name.split()[0] if name.split() else ""
    if not (len(first_word) > 1 and first_word.isupper()):     # "GDP ..." giữ nguyên, "Tỷ lệ" -> "tỷ lệ"
        name = name[:1].lower() + name[1:]
    return {
        "title": f"Cuộc đua {name}: {len(series)} nền kinh tế châu Á từ {y0} đến {y1}",
        "summary": "\n".join(lines),
        "url": PAGE.format(code=ind["code"], locs=locs, end=y1),
        "source": SOURCE_NAME,
        "lang": "vi",
    }


def parse_vn_number(s: str) -> float:
    """Ngược lại vn_number: '36.227' -> 36227, '98,9' -> 98.9, '0,75' -> 0.75."""
    return float(s.replace(".", "").replace(",", "."))


def parse_series(summary: str) -> list:
    """Đọc lại các dòng "<Nước> theo năm: 1990: 98,9; 1995: 159; ..." mà build_item viết
    -> [{"label": "Việt Nam", "xs": [1990, 1995, ...], "ys": [98.9, 159, ...]}, ...].

    Để biểu đồ đường lấy số THẲNG từ bảng gốc: model nhỏ chép chuỗi 8-10 con số hay chép
    sai/bịa (ca thật 12/11: tự chế 11.500 và 11.800 kWh cho Hàn Quốc ba lần liền).
    """
    out = []
    for line in str(summary or "").splitlines():
        m = re.match(r"\s*(.+?) theo năm:\s*(.+?)\.?\s*$", line)
        if not m:
            continue
        xs, ys = [], []
        for pair in m.group(2).split(";"):
            pm = re.match(r"\s*((?:19|20)\d{2}):\s*([\d.,]+)\s*$", pair)
            if pm:
                xs.append(int(pm.group(1)))
                ys.append(parse_vn_number(pm.group(2)))
        if len(xs) >= 2:
            out.append({"label": m.group(1).strip(), "xs": xs, "ys": ys})
    return out


def todays_indicators(indicators: list, per_day: int, today: date = None) -> list:
    """Chọn per_day chỉ số cho hôm nay, xoay vòng hết danh sách rồi mới lặp lại."""
    if not indicators or per_day <= 0:
        return []
    start = ((today or date.today()).toordinal() * per_day) % len(indicators)
    return [indicators[(start + k) % len(indicators)] for k in range(min(per_day, len(indicators)))]


def fetch_worldbank(cfg: dict, today: date = None) -> list:
    countries = cfg.get("countries") or []
    if len(countries) < 2:
        return []
    items = []
    for ind in todays_indicators(cfg.get("indicators", []), int(cfg.get("per_day", 2)), today):
        try:
            series = fetch_indicator(ind, [c["iso3"] for c in countries[:2]],
                                     int(cfg.get("start_year", 1960)))
            item = build_item(ind, countries, series)
        except Exception as exc:      # mạng chập chờn không được làm sập cả pipeline
            log.warning("Bỏ qua chỉ số World Bank %s: %s", ind.get("code"), exc)
            continue
        if item:
            items.append(item)
            log.info("World Bank %s: %s", ind["code"], item["title"])
        else:
            log.info("World Bank %s: số liệu quá mỏng — bỏ", ind["code"])
    items += fetch_races(cfg.get("races") or {}, today)
    return items


def fetch_races(cfg: dict, today: date = None) -> list:
    """Ý tưởng "cuộc đua" nhiều nước (cấu hình sources.worldbank.races)."""
    countries = cfg.get("countries") or []
    if len(countries) < 3:
        return []
    focus = cfg.get("focus") or []
    items = []
    for ind in todays_indicators(cfg.get("indicators", []), int(cfg.get("per_day", 1)), today):
        try:
            series = fetch_indicator(ind, [c["iso3"] for c in countries],
                                     int(cfg.get("start_year", 1990)))
            item = build_race_item(ind, countries, series, focus, int(cfg.get("year_step", 5)))
        except Exception as exc:
            log.warning("Bỏ qua cuộc đua World Bank %s: %s", ind.get("code"), exc)
            continue
        if item:
            items.append(item)
            log.info("World Bank (cuộc đua) %s: %s", ind["code"], item["title"])
    return items
