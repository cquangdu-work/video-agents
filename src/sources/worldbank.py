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
import time
from datetime import date

import requests

from .datatable import (WB_SOURCE, beats_lines, lower_first, parse_series,  # noqa: F401
                        parse_vn_number, race_lines, race_years, ranking, ratio_phrase,
                        relatable_line, spoken_scale, story_beats, trim_leading, vn_number)

log = logging.getLogger(__name__)

SOURCE_NAME = WB_SOURCE                  # datatable.is_data_source() nhận ra tên này
API = "https://api.worldbank.org/v2/country/{countries}/indicator/{code}"
PAGE = "https://data.worldbank.org/indicator/{code}?locations={locs}&end={end}"
HEADERS = {"User-Agent": "video-agents-pipeline/0.1"}
# Đo 12/11: URL truy vấn MỚI thì máy chủ treo hơn 60 giây, nhưng vẫn tính xong ở phía sau và
# lưu đệm — gọi lại sau ~20 giây là trả trong 0,1 giây. Nên lần đầu chỉ là "đánh thức".
TIMEOUTS = (20, 60, 60)      # giây chờ của từng lần gọi
RETRY_PAUSE = 25             # giây nghỉ giữa hai lần gọi


def fetch_indicator(ind: dict, countries: list, default_start: int) -> dict:
    """fetch_series theo cấu hình của một chỉ số: năm bắt đầu riêng (`start_year`, ví dụ
    Internet năm 1990 gần như bằng 0 ở mọi nước, xếp hạng vô nghĩa) và hệ số chia
    (`scale`, ví dụ GDP 3.252.994.239.867 USD -> 3.253 tỷ USD, kèm unit "tỷ USD")."""
    series = fetch_series(ind["code"], countries, int(ind.get("start_year", default_start)))
    scale = float(ind.get("scale", 1) or 1)
    return {c: [(y, v / scale) for y, v in s] for c, s in series.items()}


def _get_rows(url: str, params: dict, timeouts: tuple = TIMEOUTS, pause: float = RETRY_PAUSE) -> list:
    """Gọi API World Bank (lần đầu có thể chỉ là "đánh thức" máy chủ, xem TIMEOUTS) -> các dòng
    số liệu. Treo, mất kết nối, hoặc lỗi 5xx tạm thời của máy chủ (đo 12/11: 502 trong lúc nó
    đang tính) thì nghỉ rồi gọi lại."""
    r = None
    for k, wait in enumerate(timeouts):
        last = k == len(timeouts) - 1
        try:
            r = requests.get(url, headers=HEADERS, timeout=wait, params=params)
        except (requests.Timeout, requests.ConnectionError):
            if last:
                raise
            time.sleep(pause)
            continue
        if r.status_code >= 500 and not last:
            time.sleep(pause)
            continue
        break
    r.raise_for_status()
    payload = r.json()
    return payload[1] if isinstance(payload, list) and len(payload) > 1 and payload[1] else []


def fetch_series(code: str, countries: list, start_year: int) -> dict:
    """-> {mã nước: [(năm, giá trị), ...] tăng dần theo năm}, bỏ các năm không có số."""
    url = API.format(countries=";".join(countries), code=code)
    rows = _get_rows(url, {"format": "json", "per_page": 1000,
                           "date": f"{start_year}:{date.today().year}"})
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


def shown(v: float) -> float:
    """Giá trị đúng như được ĐỌC lên (đã làm tròn bằng vn_number) — phép trừ hai tỷ lệ phải ra
    đúng hiệu của hai số người xem nghe thấy (74,7 - 68,6 = 6,1, không phải 6,13)."""
    return parse_vn_number(vn_number(v))


def change_phrase(first: float, last: float, unit: str = "") -> str:
    """Mô tả thay đổi từ số đầu tới số cuối bằng lời: 'tăng gấp 21,2 lần' / 'giảm 69,8%'.

    Chỉ số là TỶ LỆ % (unit bắt đầu bằng "%") thì nói bằng ĐIỂM PHẦN TRĂM: 74,7% -> 68,6% là
    "giảm 6,1 điểm phần trăm". Nói "giảm 8,28%" (thay đổi tương đối của một tỷ lệ) là đúng toán
    nhưng người xem hiểu thành 74,7% - 8,28% — ca thật kịch bản #46 (19/11/2026)."""
    if unit.startswith("%"):
        gap = round(shown(last) - shown(first), 6)
        if gap == 0:
            return "giữ nguyên"
        phrase = f"{'tăng' if gap > 0 else 'giảm'} {vn_number(abs(gap))} điểm phần trăm"
        if first > 0 and last / first >= 2:
            phrase += f" (gấp {vn_number(last / first)} lần)"
        return phrase
    if first <= 0 or last < 0:
        return ""
    ratio = last / first
    if ratio >= 2:
        return f"tăng gấp {vn_number(ratio)} lần"
    if ratio >= 1:
        return f"tăng {vn_number((ratio - 1) * 100)}%"
    return f"giảm {vn_number((1 - ratio) * 100)}%"


def latest_gap_line(name_a: str, va: float, name_b: str, vb: float, unit: str) -> str:
    """Dòng so hai nước ở số mới nhất. Tỷ lệ % chênh ít (dưới 1,5 lần) thì nói hiệu bằng điểm
    phần trăm ("hơn 11,8 điểm phần trăm") — "gấp 1,21 lần" của hai tỷ lệ nghe gượng và dễ hiểu sai."""
    if not va or not vb or min(va, vb) <= 0:
        return ""
    (hi, v_hi), (lo, v_lo) = sorted(((name_a, va), (name_b, vb)), key=lambda p: -p[1])
    if unit.startswith("%") and v_hi / v_lo < 1.5:
        gap = round(shown(v_hi) - shown(v_lo), 6)
        return f"Số mới nhất: {hi} hơn {lo} {vn_number(gap)} điểm phần trăm." if gap else ""
    return f"Số mới nhất: {hi} gấp {vn_number(v_hi / v_lo)} lần {lo}."


def build_item(ind: dict, countries: list, series: dict):
    """Một chỉ số + số liệu hai nước -> một ý tưởng thô {title, summary, url, source, lang}.
    countries: [{"iso3": "VNM", "iso2": "VN", "name": "Việt Nam"}, {...}].
    Trả về None nếu số liệu quá mỏng để kể thành chuyện."""
    ca, cb = countries[:2]
    (a, name_a), (b, name_b) = (ca["iso3"], ca["name"]), (cb["iso3"], cb["name"])
    sa, sb = trim_leading(series.get(a, []), series.get(b, []))
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
        phrase = change_phrase(v0, v1, unit)
        if phrase:
            lines.append(f"Từ {y0} đến {y1}, {name} {phrase}.")
    gap_line = latest_gap_line(name_a, va1, name_b, vb1, unit)
    if gap_line:
        lines.append(gap_line)
    match = catch_up_year(va1, sb)
    if match:
        lines.append(f"{name_a} năm {ya1} ({val(va1)}) tương đương {name_b} năm {match[0]}"
                     f" ({val(match[1])}) — cách nhau {ya1 - match[0]} năm.")
    relate = relatable_line([(name_a, va1), (name_b, vb1)], unit, ind)
    if relate:
        lines.append(relate)
    lines += beats_lines(story_beats({name_a: sa, name_b: sb}, [name_a, name_b], unit))
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


def build_race_item(ind: dict, countries: list, series: dict, focus: list, step: int = 5):
    """Một chỉ số + số liệu nhiều nước -> ý tưởng "cuộc đua" (thanh ngang đổi chỗ qua các năm).
    countries: [{"iso3", "iso2", "name"}, ...]; focus: mã iso3 các nước cần kể kỹ (Việt Nam, Hàn Quốc).
    None nếu dữ liệu không đủ cho một cuộc đua (dưới 3 nước hoặc dưới 4 mốc năm)."""
    names = {c["iso3"]: c["name"] for c in countries}
    series = {c: s for c, s in series.items() if c in names and s}
    years = race_years(series, step)
    if len(series) < 3 or len(years) < 4:
        return None
    y0, y1 = years[0], years[-1]
    unit = ind.get("unit", "")
    named = {names[c]: series[c] for c in series}
    lines = [f"Chỉ số: {ind['name']} ({unit}). Nguồn: World Bank Open Data, mã {ind['code']}."
             f" Cuộc đua giữa {len(series)} nền kinh tế châu Á, từ {y0} đến {y1}."]
    focus_names = [names[c] for c in focus if c in series]
    relate = relatable_line([(n, dict(named[n]).get(y1)) for n in focus_names], unit, ind)
    if relate:
        lines.append(relate)
    lines += race_lines(named, years, focus_names, unit)
    locs = "-".join(c["iso2"] for c in countries if c["iso3"] in series)
    return {
        "title": f"Cuộc đua {lower_first(ind['name'])}: {len(series)} nền kinh tế châu Á"
                 f" từ {y0} đến {y1}",
        "summary": "\n".join(lines),
        "url": PAGE.format(code=ind["code"], locs=locs, end=y1),
        "source": SOURCE_NAME,
        "lang": "vi",
    }


# ---------------------------------------------------------------- bản đồ thế giới
WORLD_PAGE = "https://data.worldbank.org/indicator/{code}?view=map&year={year}"
SOUTHEAST_ASIA = ("BRN", "KHM", "IDN", "LAO", "MYS", "MMR", "PHL", "SGP", "THA", "VNM", "TLS")
MIN_WORLD_COUNTRIES = 100       # ít hơn thì "bản đồ thế giới" toàn ô trống, không đáng làm
# Đo 12/11: truy vấn "mọi nước x 11 năm" chưa có trong bộ đệm thì máy chủ tính mất vài phút
# (treo, rồi 502), tính xong thì trả trong 0,2 giây. Lịch chờ dài hơn (tối đa ~9 phút) — bước
# ý tưởng của lượt hằng ngày có trần 1 giờ.
WORLD_TIMEOUTS = (20, 120, 120, 120)
WORLD_PAUSE = 60


def fetch_world_table(code: str, known: set, years_back: int = 10) -> dict:
    """Số liệu MỌI nước của một chỉ số trong `years_back` năm gần nhất (một lần gọi)
    -> {năm: {mã ISO3: giá trị}}. Chỉ giữ mã có trên bản đồ (`known`) — API trả cả các
    nhóm như "Thế giới", "Đông Á & Thái Bình Dương", không phải nước."""
    this_year = date.today().year
    rows = _get_rows(API.format(countries="all", code=code),
                     {"format": "json", "per_page": 20000, "date": f"{this_year - years_back}:{this_year}"},
                     WORLD_TIMEOUTS, WORLD_PAUSE)
    out = {}
    for row in rows:
        c, v = row.get("countryiso3code"), row.get("value")
        if c in known and v is not None:
            out.setdefault(int(row["date"]), {})[c] = float(v)
    return out


def pick_world_year(by_year: dict, must_have: str = "VNM", min_share: float = 0.85):
    """Năm mới nhất có số của gần đủ các nước (World Bank cập nhật dần: năm mới nhất thường
    mới có vài chục nước) VÀ có số của Việt Nam. Không trộn năm: mọi nước cùng một năm."""
    if not by_year:
        return None
    best = max(len(v) for v in by_year.values())
    ok = [y for y, v in by_year.items() if len(v) >= min_share * best
          and (must_have is None or must_have in v)]
    return max(ok) if ok else None


def build_world_item(ind: dict, year: int, table: dict, names: dict, focus: list, history: dict,
                     *, source_line: str = None, url: str = None, source: str = SOURCE_NAME,
                     extra_series: dict = None):
    """Một chỉ số + số liệu mọi nước trong một năm -> ý tưởng "Việt Nam đứng thứ mấy thế giới".
    table: {ISO3: giá trị} (đã chia scale); names: {ISO3: tên tiếng Việt}; focus: [VNM, KOR];
    history: {ISO3: [(năm, giá trị)]} của các nước focus (để vẽ thêm biểu đồ đường).
    Nguồn khác World Bank (src/sources/owid.py) truyền source_line/url/source của mình, và
    extra_series {nhãn: [(năm, giá trị)]} (vd "Thế giới") để vẽ thêm vào biểu đồ đường.
    None nếu quá ít nước có số hoặc thiếu Việt Nam."""
    import statistics
    from .datatable import ranks_desc, world_table_line
    table = {c: v for c, v in table.items() if c in names}
    n = len(table)
    if n < MIN_WORLD_COUNTRIES or (focus and focus[0] not in table):
        return None
    unit = ind.get("unit", "")
    val = lambda v: f"{vn_number(v)} {unit}".strip()
    rank = ranks_desc(table)
    order = sorted(table, key=lambda c: -table[c])
    where = f"{n} nước và vùng lãnh thổ"
    source_line = source_line or f"Nguồn: World Bank Open Data, mã {ind['code']}."
    lines = [f"Chỉ số: {ind['name']} ({unit}). {source_line} Năm {year}: có số của {where}."]
    for c in focus:
        if c in table:
            below = sum(1 for v in table.values() if v < table[c])
            if rank[c] <= n / 2:
                lines.append(f"{names[c]}: {val(table[c])} — cao thứ {rank[c]} trên {where}"
                             f" (cao hơn {round(100 * below / n)}% số nơi có số liệu).")
            else:          # nửa dưới bảng: "thấp thứ 2" thay vì "cao thứ 213, cao hơn 0%"
                lines.append(f"{names[c]}: {val(table[c])} — thấp thứ {below + 1} trên {where}"
                             f" (tức cao thứ {rank[c]}).")
    lines.append("5 nơi cao nhất: " + "; ".join(
        f"{rank[c]}. {names[c]} — {val(table[c])}" for c in order[:5]) + ".")
    lines.append("3 nơi thấp nhất: " + "; ".join(
        f"{names[c]} — {val(table[c])}" for c in order[-3:]) + ".")
    lines.append(f"Trung vị thế giới: {val(statistics.median(table.values()))}.")
    sea = {c: table[c] for c in SOUTHEAST_ASIA if c in table}
    if focus and focus[0] in sea and len(sea) >= 5:
        top = max(sea, key=sea.get)
        lines.append(f"Trong {len(sea)} nước Đông Nam Á có số liệu, {names[focus[0]]} đứng thứ"
                     f" {ranks_desc(sea)[focus[0]]}; cao nhất là {names[top]} — {val(sea[top])}.")
    a, b = (focus + [None, None])[:2]
    if a in table and b in table and table[a] != table[b]:
        hi, lo = (b, a) if table[b] > table[a] else (a, b)
        if table[lo] > 0 and table[hi] / table[lo] >= 1.5:    # "gấp 1,12 lần" nghe gượng
            lines.append(f"Năm {year}: {names[hi]} gấp {vn_number(table[hi] / table[lo])} lần {names[lo]}.")
        else:                    # hiệu của hai tỷ lệ % là "điểm phần trăm", không phải %
            # trừ trên số ĐÃ LÀM TRÒN như được đọc lên (83,6 - 74,7 = 8,9, không phải 8,89)
            gap = round(shown(table[hi]) - shown(table[lo]), 6)
            gap_text = (f"{vn_number(gap)} điểm phần trăm" if unit.startswith("%") else val(gap))
            lines.append(f"Năm {year}: {names[hi]} hơn {names[lo]} {gap_text}.")
    # Góc kể chuyện mạnh nhất của kênh: "Việt Nam hôm nay bằng Hàn Quốc năm nào"
    match = catch_up_year(table[a], history.get(b) or []) if a in table and b else None
    if match and match[0] < year:
        lines.append(f"{names[a]} năm {year} ({val(table[a])}) tương đương {names[b]} năm {match[0]}"
                     f" ({val(match[1])}) — cách nhau {year - match[0]} năm.")
    relate = relatable_line([(names[c], table[c]) for c in focus if c in table], unit, ind)
    if relate:
        lines.append(relate)
    hist_named = {names[c]: history[c] for c in focus if c in names and len(history.get(c) or []) >= 2}
    beats = story_beats(hist_named, [names[c] for c in focus if names.get(c) in hist_named], unit)
    if a in table:                         # so với nơi cao nhất / thấp nhất / trung vị — tính sẵn
        top, bottom, med = order[0], order[-1], statistics.median(table.values())
        beats += [r for r in (
            ratio_phrase(f"{names[top]} (cao nhất)", table[top], names[a], table[a]) if top != a else "",
            ratio_phrase(names[a], table[a], f"{names[bottom]} (thấp nhất)", table[bottom]) if bottom != a else "",
            ratio_phrase(names[a], table[a], "trung vị thế giới", med, 1.2),
            ratio_phrase("Trung vị thế giới", med, names[a], table[a], 1.2)) if r]
    lines += beats_lines(beats)
    # chuỗi theo năm -> biểu đồ đường (các nước focus, rồi chuỗi thêm như "Thế giới")
    series = [(names[c], history.get(c) or []) for c in focus] + list((extra_series or {}).items())
    for label, s in series:
        picks = [p for i, p in enumerate(s) if p[0] % 5 == 0 or i in (0, len(s) - 1)]
        if len(picks) >= 2:
            lines.append(f"{label} theo năm: " + "; ".join(f"{y}: {vn_number(v)}" for y, v in picks) + ".")
    lines.append(world_table_line(year, {names[c]: v for c, v in table.items()}))
    title = f"Bản đồ thế giới: {lower_first(ind['name'])} năm {year}"
    if focus and focus[0] in table:
        title += f" — {names[focus[0]]} thứ {rank[focus[0]]}/{n}"
    return {"title": title, "summary": "\n".join(lines),
            "url": url or WORLD_PAGE.format(code=ind["code"], year=year),
            "source": source, "lang": "vi"}


def fetch_world_maps(cfg: dict, indicators: list, today: date = None) -> list:
    """Ý tưởng "bản đồ thế giới" (cấu hình sources.worldbank.world): mỗi ngày `per_day` chỉ số,
    tên/đơn vị/scale lấy từ danh sách indicators chung theo mã."""
    from ..render.geo import has_map, load_map
    codes = cfg.get("indicators") or []
    if not codes or not has_map("world"):
        return []
    lookup = {i["code"]: i for i in indicators or []}
    pool = [lookup[c] for c in codes if c in lookup]
    world = load_map("world")["countries"]
    names = {c: w["name"] for c, w in world.items()}
    focus = cfg.get("focus") or ["VNM", "KOR"]
    items = []
    for ind in todays_indicators(pool, int(cfg.get("per_day", 1)), today, cfg.get("priority")):
        try:
            scale = float(ind.get("scale", 1) or 1)
            by_year = fetch_world_table(ind["code"], set(world))
            year = pick_world_year(by_year, focus[0])
            if year is None:
                log.info("World Bank (bản đồ) %s: chưa năm nào đủ số liệu — bỏ", ind["code"])
                continue
            table = {c: v / scale for c, v in by_year[year].items()}
            history = fetch_indicator(ind, focus, int(cfg.get("start_year", 1990)))
            item = build_world_item(ind, year, table, names, focus, history)
        except Exception as exc:          # mạng chập chờn không được làm sập cả pipeline
            log.warning("Bỏ qua bản đồ World Bank %s: %s", ind.get("code"), exc)
            continue
        if item:
            items.append(item)
            log.info("World Bank (bản đồ) %s: %s", ind["code"], item["title"])
    return items


def todays_indicators(indicators: list, per_day: int, today: date = None, priority=()) -> list:
    """Chọn per_day chỉ số cho hôm nay, xoay vòng hết danh sách rồi mới lặp lại. priority: mã chỉ số /
    slug được yêu cầu (người xem, Du, video đột biến — src/topics.py) được lấy TRƯỚC xoay vòng."""
    if not indicators or per_day <= 0:
        return []
    n = min(per_day, len(indicators))
    wanted = set(priority or ())
    first = [i for i in indicators if isinstance(i, dict) and (i.get("code") or i.get("slug")) in wanted][:n]
    start = ((today or date.today()).toordinal() * per_day) % len(indicators)
    rotation = [indicators[(start + k) % len(indicators)] for k in range(len(indicators))]
    return (first + [i for i in rotation if i not in first])[:n]


def fetch_worldbank(cfg: dict, today: date = None) -> list:
    countries = cfg.get("countries") or []
    if len(countries) < 2:
        return []
    items = []
    for ind in todays_indicators(cfg.get("indicators", []), int(cfg.get("per_day", 2)), today, cfg.get("priority")):
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
    items += fetch_world_maps(cfg.get("world") or {}, cfg.get("indicators", []), today)
    return items


def fetch_races(cfg: dict, today: date = None) -> list:
    """Ý tưởng "cuộc đua" nhiều nước (cấu hình sources.worldbank.races)."""
    countries = cfg.get("countries") or []
    if len(countries) < 3:
        return []
    focus = cfg.get("focus") or []
    items = []
    for ind in todays_indicators(cfg.get("indicators", []), int(cfg.get("per_day", 1)), today, cfg.get("priority")):
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
