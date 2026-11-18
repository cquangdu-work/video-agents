"""Ý tưởng "thế giới qua một bảng số" từ Our World in Data (OWID) — không cần key, giấy phép CC BY 4.0.

Vì sao có nguồn này (18/11/2026): các nguồn bảng số cũ (World Bank, KOSIS) đều xoay quanh Việt Nam –
Hàn Quốc và kinh tế vĩ mô, nên 6/6 Shorts tuần đầu là "Việt Nam và Hàn Quốc từ 19xx đến 20xx".
Du thấy chủ đề đơn điệu, và YouTube không cho kiếm tiền nội dung lặp khuôn. OWID có hàng nghìn bảng
về khí hậu, năng lượng, thực phẩm, công nghệ, đời sống, của gần như mọi nước.

Hai dạng ý tưởng (sources.owid.charts[].kind trong config), viết ĐÚNG khuôn tóm tắt của World Bank
(src/sources/datatable.py) nên Biên kịch, cổng chống bịa số, biểu đồ, bản đồ, cuộc đua chạy y như cũ:
- "map":  mọi nước trong một năm -> bản đồ thế giới, ai cao nhất/thấp nhất, Việt Nam đứng thứ mấy,
          kèm chuỗi theo năm của Việt Nam (và của "Thế giới" nếu là số bình quân) cho biểu đồ đường.
- "race": vài nước qua các năm -> cuộc đua thanh ngang. group "top" = các nước dẫn đầu năm mới nhất
          (+ Việt Nam), hợp với số TỔNG (CO2, điện mặt trời); group có tên (vd "major") = danh sách
          nước cố định trong config, hợp với số BÌNH QUÂN (xếp đầu toàn nước tí hon thì vô vị).
Việt Nam vẫn là "điểm neo" cho người xem Việt, nhưng chủ đề là của cả thế giới.
"""
import logging
from datetime import date

from .datatable import OWID_SOURCE, lower_first, race_lines, race_years
from .worldbank import MIN_WORLD_COUNTRIES, build_world_item, pick_world_year, todays_indicators

log = logging.getLogger(__name__)

GRAPHER = "https://ourworldindata.org/grapher/{slug}"
WORLD = "OWID_WRL"                 # mã OWID của "Thế giới" (tổng hoặc bình quân cả thế giới)
WORLD_LABEL = "Thế giới"
TOP_N = 10                         # số nước tối đa của một cuộc đua (vừa khung dọc)


def load_table(slug: str, fetch=None) -> dict:
    """{(mã ISO3 hoặc OWID_WRL, năm): giá trị} của một biểu đồ OWID (lưu đệm 7 ngày).
    Dùng chung bộ tải với khâu đối chiếu nguồn thứ hai (src/second_source.py)."""
    if fetch is None:
        from ..second_source import fetch_table as fetch
    return fetch(slug)


def source_line(chart: dict) -> str:
    origin = f" (số liệu gốc: {chart['origin']})" if chart.get("origin") else ""
    return f"Nguồn: Our World in Data, biểu đồ “{chart['slug']}”{origin}."


def by_year(table: dict, codes: set, scale: float, first: int, last: int) -> dict:
    """{năm: {mã: giá trị đã chia scale}} cho các mã trong `codes`, năm trong [first, last]."""
    out = {}
    for (code, year), v in table.items():
        if code in codes and first <= year <= last:
            out.setdefault(year, {})[code] = v / scale
    return out


def history(table: dict, code: str, scale: float, first: int, last: int) -> list:
    """[(năm, giá trị)] tăng dần của một mã."""
    return sorted((y, v / scale) for (c, y), v in table.items() if c == code and first <= y <= last)


def build_map(chart: dict, table: dict, names: dict, focus: list, this_year: int):
    """Ý tưởng "bản đồ thế giới" từ một biểu đồ OWID. None nếu không năm nào đủ nước có số."""
    scale = float(chart.get("scale", 1) or 1)
    # 10 năm gần nhất, KHÔNG lấy năm tương lai (vài bảng OWID có cả số dự báo)
    years = by_year(table, set(names), scale, this_year - 10, this_year)
    year = pick_world_year(years, focus[0] if focus else None)
    if year is None:
        return None
    start = int(chart.get("start_year", 1990))
    hist = {c: history(table, c, scale, start, year) for c in focus}
    extra = {}
    world = history(table, WORLD, scale, start, year)
    # Chuỗi "Thế giới" chỉ khi nó là số BÌNH QUÂN (nằm trong khoảng của các nước). Số TỔNG cả thế
    # giới (CO2 cả năm) lớn hơn mọi nước -> vẽ chung trục thì đường các nước dẹp lép dưới đáy.
    if world and world[-1][1] <= max(years[year].values()):
        extra[WORLD_LABEL] = world
    ind = {"code": chart["slug"], "name": chart["name"], "unit": chart.get("unit", "")}
    return build_world_item(ind, year, years[year], names, focus, hist,
                            source_line=source_line(chart), source=OWID_SOURCE, extra_series=extra,
                            url=GRAPHER.format(slug=chart["slug"]) + f"?tab=map&time={year}")


def race_countries(chart: dict, table: dict, names: dict, groups: dict, focus: list,
                   this_year: int) -> tuple:
    """Các nước của một cuộc đua -> (mã ISO3, nước focus được THÊM vào vì không lọt top hay không)."""
    group = chart.get("group", "top")
    if group != "top":
        return [c for c in groups.get(group, []) if c in names], False
    scale = float(chart.get("scale", 1) or 1)
    years = by_year(table, set(names), scale, this_year - 10, this_year)
    year = pick_world_year(years, None)
    if year is None:
        return [], False
    latest = years[year]
    top = sorted(latest, key=lambda c: -latest[c])[:TOP_N]
    anchor = next((c for c in focus if c in latest), None)
    if anchor is None or anchor in top:
        return top, False
    # Việt Nam (điểm neo của người xem Việt) không lọt top: nhường chỗ cuối cho Việt Nam
    return top[:TOP_N - 1] + [anchor], True


def build_race(chart: dict, table: dict, names: dict, groups: dict, focus: list, this_year: int):
    """Ý tưởng "cuộc đua" từ một biểu đồ OWID. None nếu dưới 3 nước hoặc dưới 4 mốc năm."""
    codes, added = race_countries(chart, table, names, groups, focus, this_year)
    scale = float(chart.get("scale", 1) or 1)
    start = int(chart.get("start_year", 1990))
    series = {c: history(table, c, scale, start, this_year) for c in codes}
    series = {c: s for c, s in series.items() if s}
    years = race_years(series, int(chart.get("year_step", 5)))
    if len(series) < 3 or len(years) < 4:
        return None
    y0, y1 = years[0], years[-1]
    in_focus = [names[c] for c in focus if c in series]
    if chart.get("group", "top") == "top":
        who = (f"{len(series) - 1} nước dẫn đầu thế giới và {in_focus[0]}" if added and in_focus
               else f"{len(series)} nước dẫn đầu thế giới")
    else:
        who = (f"{in_focus[0]} và {len(series) - 1} nền kinh tế lớn" if in_focus
               else f"{len(series)} nền kinh tế lớn")
    unit = chart.get("unit", "")
    lines = [f"Chỉ số: {chart['name']} ({unit}). {source_line(chart)}"
             f" Cuộc đua giữa {who}, từ {y0} đến {y1}. Mọi thứ hạng trong cuộc đua là hạng GIỮA"
             f" {len(series)} nước này, không phải hạng thế giới."]
    world_line = world_rank_line(table, names, series, focus, y1)
    if world_line:
        lines.append(world_line)
    lines += race_lines({names[c]: s for c, s in series.items()}, years, in_focus)
    return {
        "title": f"Cuộc đua {lower_first(chart['name'])}: {who} từ {y0} đến {y1}",
        "summary": "\n".join(lines),
        "url": GRAPHER.format(slug=chart["slug"]) + "?tab=chart&time={}..{}&country={}".format(
            y0, y1, "~".join(series)),
        "source": OWID_SOURCE,
        "lang": "vi",
    }


def world_rank_line(table: dict, names: dict, series: dict, focus: list, year: int):
    """Hạng THẾ GIỚI thật của nước focus trong năm cuối cuộc đua, hoặc None nếu năm đó quá ít nước
    có số để gọi là "thế giới". Ca thật 18/11 (kịch bản #44): cuộc đua xe điện giữa 10 nền kinh tế
    lớn, Việt Nam hạng 2 TRONG NHÓM -> Biên kịch viết "hạng 2 toàn cầu" (Na Uy cao hơn nhiều), và
    agent Kiểm chứng để lọt. Có sẵn hạng thật thì Biên kịch có con số đúng mà dùng."""
    from .datatable import ranks_desc
    anchor = next((c for c in focus if c in series), None)
    world = {c: v for (c, y), v in table.items() if y == year and c in names}
    if anchor is None or anchor not in world or len(world) < 2 * len(series):
        return None
    at = {c: dict(s).get(year) for c, s in series.items()}
    race_rank = ranks_desc({c: v for c, v in at.items() if v is not None})[anchor]
    world_rank = ranks_desc(world)[anchor]
    line = (f"Hạng thế giới thật năm {year}: {names[anchor]} thứ {world_rank} trong {len(world)}"
            f" nước và vùng lãnh thổ có số liệu.")
    if world_rank != race_rank:
        line += (f" Hạng {race_rank} của {names[anchor]} trong cuộc đua chỉ là hạng trong nhóm, KHÔNG"
                 f" được gọi là hạng thế giới hay toàn cầu.")
    return line


def fetch_owid(cfg: dict, today: date = None, fetch=None) -> list:
    """Mỗi ngày `per_day` biểu đồ, xoay vòng hết danh sách rồi mới lặp (cùng cách với World Bank).
    Biểu đồ đã thành ý tưởng thì DB tự bỏ (trùng URL) cho tới khi OWID có số năm mới."""
    charts = cfg.get("charts") or []
    if not charts:
        return []
    from ..render.geo import has_map, load_map
    if not has_map("world"):
        return []
    names = {c: w["name"] for c, w in load_map("world")["countries"].items()}
    focus = cfg.get("focus") or ["VNM"]
    groups = cfg.get("groups") or {}
    this_year = (today or date.today()).year
    items = []
    for chart in todays_indicators(charts, int(cfg.get("per_day", 2)), today):
        try:
            table = load_table(chart["slug"], fetch)
            if chart.get("kind", "map") == "race":
                item = build_race(chart, table, names, groups, focus, this_year)
            else:
                item = build_map(chart, table, names, focus, this_year)
        except Exception as exc:          # mạng chập chờn không được làm sập cả pipeline
            log.warning("Bỏ qua biểu đồ OWID %s: %s", chart.get("slug"), exc)
            continue
        if item:
            items.append(item)
            log.info("OWID %s: %s", chart["slug"], item["title"])
        else:
            log.info("OWID %s: số liệu không đủ (dưới %d nước hoặc thiếu mốc năm) — bỏ",
                     chart["slug"], MIN_WORLD_COUNTRIES)
    return items
