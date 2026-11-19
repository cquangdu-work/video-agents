"""Hàm dùng chung cho các nguồn ý tưởng dạng BẢNG SỐ LIỆU (World Bank, KOSIS, Our World in Data).

Ý tưởng từ bảng số có tóm tắt viết theo một khuôn cố định, để:
- Biên kịch chép số đúng dạng Việt ("36.227", "98,9") -> cổng chống bịa số khớp được;
- code đọc ngược lại được chuỗi số theo năm (parse_series) -> biểu đồ lấy số thẳng từ bảng.
Khuôn quan trọng nhất: mỗi đối tượng một dòng "<Tên> theo năm: 2022: 1.234; 2023: 1.456."
"""
import re

WB_SOURCE = "World Bank Open Data"
KOSIS_SOURCE = "KOSIS — Thống kê Hàn Quốc"
OWID_SOURCE = "Our World in Data"
DATA_SOURCES = {WB_SOURCE, KOSIS_SOURCE, OWID_SOURCE}


def is_data_source(name) -> bool:
    """Ý tưởng này đến từ kho dữ liệu (tóm tắt CHÍNH LÀ bảng số) chứ không phải bài báo."""
    return name in DATA_SOURCES


def topic_family(source_name) -> str:
    """Mảng chủ đề của một ý tưởng, để giữ cân bằng (main chọn ý tưởng đem viết, daily chọn
    kịch bản đem dựng). Ca thật 13-18/11: 6/6 Shorts là "Việt Nam và Hàn Quốc qua một chỉ số
    kinh tế" -> Du chê đơn điệu, và YouTube không cho kiếm tiền nội dung lặp khuôn.
      viet-han: World Bank (hai nước, cuộc đua châu Á, bản đồ có Việt–Hàn), KOSIS
      the-gioi: Our World in Data (khí hậu, năng lượng, thực phẩm, công nghệ, đời sống...)
      bai-bao:  bài báo khoa học, câu hỏi thật"""
    if source_name in (WB_SOURCE, KOSIS_SOURCE):
        return "viet-han"
    if source_name == OWID_SOURCE:
        return "the-gioi"
    return "bai-bao"


def vn_number(x: float) -> str:
    """Viết số kiểu Việt Nam, làm tròn vừa đủ để ĐỌC được: 36226.97 -> '36.227',
    83.74 -> '83,7', 0.721 -> '0,72'. Biên kịch chép nguyên dạng này vào lời đọc nên
    cổng chống bịa số khớp được từng chữ số."""
    a = abs(x)
    decimals = 0 if a >= 100 else 1 if a >= 10 else 2
    s = f"{x:,.{decimals}f}"
    if "." in s:                         # bỏ số 0 thừa: 8,90 -> 8,9; 5,00 -> 5
        s = s.rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


def spoken_scale(x: float) -> str:
    """Số rất lớn kèm cách nói gọn: 100987686 -> ' (khoảng 101,0 triệu)'. Nhỏ thì rỗng."""
    for size, word in ((1e12, "nghìn tỷ"), (1e9, "tỷ"), (1e6, "triệu")):
        if abs(x) >= size:
            return f" (khoảng {vn_number(x / size)} {word})"
    return ""


def parse_vn_number(s: str) -> float:
    """Ngược lại vn_number: '36.227' -> 36227, '98,9' -> 98.9, '0,75' -> 0.75."""
    return float(s.replace(".", "").replace(",", "."))


def parse_series(summary: str) -> list:
    """Đọc lại các dòng "<Tên> theo năm: 1990: 98,9; 1995: 159; ..." trong tóm tắt
    -> [{"label": "Việt Nam", "xs": [1990, 1995, ...], "ys": [98.9, 159, ...]}, ...].

    Để biểu đồ lấy số THẲNG từ bảng gốc: model nhỏ chép chuỗi 8-10 con số hay chép
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


def race_years(series: dict, step: int = 5) -> list:
    """Các mốc năm cho cuộc đua: những năm MỌI đối tượng đều có số, lấy cách nhau `step`
    năm, luôn kèm năm đầu và năm cuối."""
    common = set.intersection(*[{y for y, _ in s} for s in series.values()]) if series else set()
    if not common:
        return []
    first, last = min(common), max(common)
    return sorted(y for y in common if y in (first, last) or y % step == 0)


def ranking(values: dict) -> list:
    """{tên: giá trị} -> danh sách tên xếp từ cao xuống thấp."""
    return [name for name, _ in sorted(values.items(), key=lambda kv: -kv[1])]


def ranks_desc(values: dict) -> dict:
    """{khoá: giá trị} -> {khoá: thứ hạng từ cao xuống thấp}; bằng nhau thì cùng hạng
    (1 + số nơi có giá trị LỚN HƠN). Tóm tắt và bản đồ cùng dùng hàm này nên hạng đọc
    trong lời và hạng hiện trên hình luôn khớp."""
    vals = sorted(values.values(), reverse=True)
    import bisect
    neg = [-v for v in vals]                     # tăng dần, để đếm số giá trị lớn hơn bằng bisect
    return {k: bisect.bisect_left(neg, -v) + 1 for k, v in values.items()}


# Dòng bảng đủ mọi nước của ý tưởng "bản đồ thế giới" — máy đọc lại để tô bản đồ (quá dài
# để model chép, và model không được dùng số ở đây cho lời đọc).
WORLD_TABLE = "Số liệu từng nước năm"


def world_table_line(year: int, named: dict) -> str:
    """{tên tiếng Việt: giá trị} -> 'Số liệu từng nước năm 2024 (...): Afghanistan 66,0; ...'"""
    body = "; ".join(f"{n} {vn_number(v)}" for n, v in sorted(named.items()))
    return (f"{WORLD_TABLE} {year} (máy dùng để tô bản đồ; lời đọc chỉ dùng các số đã nêu ở"
            f" trên): {body}.")


def parse_world_table(summary: str):
    """Ngược lại world_table_line -> {"year": 2024, "items": [{"label", "value"}]} hoặc None."""
    m = re.search(rf"^{WORLD_TABLE} ((?:19|20)\d{{2}})[^:]*:\s*(.+?)\.?\s*$", str(summary or ""), re.M)
    if not m:
        return None
    items = []
    for part in m.group(2).split(";"):
        pm = re.match(r"\s*(.+?)\s+(-?[\d.]*\d(?:,\d+)?)\s*$", part)
        if pm:
            items.append({"label": pm.group(1), "value": parse_vn_number(pm.group(2))})
    return {"year": int(m.group(1)), "items": items} if items else None


def lower_first(name: str) -> str:
    """Viết thường chữ đầu để ghép vào câu, trừ khi từ đầu là chữ viết tắt ("GDP ...")."""
    first_word = name.split()[0] if name.split() else ""
    if len(first_word) > 1 and first_word.isupper():
        return name
    return name[:1].lower() + name[1:]


# ------------------------------------------------- điểm nhấn + cách nói dễ hình dung (19/11/2026)
# Vì sao: số liệu giữ chân người xem của kênh (video #6, #7) cho thấy người xem bỏ đi đúng ở các câu
# không có thông tin mới — model chỉ có vài con số nên tự chế câu giải thích ("Đó là giai đoạn khởi
# đầu của các tập đoàn công nghiệp lớn", không có trong nguồn) hoặc kể từ năm đầu bảng ("Nhìn lại năm
# 1960, cả hai nước đều có 0 thuê bao"). Code tính sẵn những điều ĐÁNG KỂ có thật trong bảng.
BEATS_HEADER = "Điểm nhấn (máy tính sẵn từ bảng số — dựng câu chuyện từ đây):"
RELATE_HEADER = "Cách nói dễ hình dung (máy tính sẵn):"
PERIODS = {"ngày": 365, "tuần": 52, "tháng": 12}


def shown_value(v: float) -> float:
    """Giá trị đúng như được ĐỌC lên (đã làm tròn bằng vn_number)."""
    return parse_vn_number(vn_number(v))


def fraction_phrase(p: float, per: str) -> str:
    """Tỷ lệ % -> cách nói bằng phân số: 68,6 -> "cứ 3 phụ nữ thì 2", 38,8 -> "cứ 5 người thì 2",
    56,8 -> "cứ 10 người thì gần 6", 2,1 -> "cứ 100 người thì 2". Ngoài khoảng (0, 100) -> ""."""
    import math
    if not 0 < p < 100:
        return ""
    if 10 <= p < 90:
        for n in (2, 3, 4, 5):                       # phân số nhỏ, lệch không quá 2 điểm phần trăm
            k = round(p / 100 * n)
            if 1 <= k < n and math.gcd(k, n) == 1 and abs(100 * k / n - p) <= 2.0:
                return f"cứ {n} {per} thì {k}"
        n, k = 10, round(p / 10)
    else:                                            # tỷ lệ rất nhỏ / rất lớn: trên 100
        n, k = 100, round(p)
    if k < 1:
        return f"chưa tới 1 trong 100 {per}"
    step = 100 / n
    qual = "gần " if k * step > p + step / 10 else ("hơn " if k * step < p - step / 10 else "")
    return f"cứ {n} {per} thì {qual}{k}"


def relatable_line(pairs: list, unit: str, ind: dict) -> str:
    """Một dòng "cách nói dễ hình dung" cho các cặp (tên, giá trị). Theo cấu hình của chỉ số:
    `per` (tỷ lệ % -> phân số "cứ 5 người thì 2") hoặc `period` (số mỗi năm -> mỗi ngày/tuần/tháng:
    5.066 USD/năm -> khoảng 422 USD mỗi tháng). Không cấu hình -> ""."""
    per, period = (ind or {}).get("per"), (ind or {}).get("period")
    bits = []
    for name, v in pairs:
        if v is None:
            continue
        if per and unit.startswith("%"):
            f = fraction_phrase(v, per)
            if f:
                bits.append(f"{name} {vn_number(v)}% ≈ {f}")
        elif period in PERIODS and v > 0:
            bits.append(f"{name} {vn_number(v)} {unit} mỗi năm ≈ khoảng {vn_number(v / PERIODS[period])}"
                        f" {unit} mỗi {period}")
    return f"{RELATE_HEADER} " + "; ".join(bits) + "." if bits else ""


def _milestones(lo: float, hi: float, pct: bool) -> list:
    if pct:
        return [m for m in (25, 50, 75, 90) if lo < m < hi]
    out, k = [], -3
    while 10 ** k <= max(abs(hi), 1e-9) * 10 and k < 16:
        out += [m * 10 ** k for m in (1, 2, 5) if lo < m * 10 ** k < hi]
        k += 1
    return sorted(set(out))


def _fmt(v: float, unit: str) -> str:
    return (f"{vn_number(v)}%" if unit.startswith("%") else f"{vn_number(v)} {unit}".strip())


def story_beats(named: dict, focus: list, unit: str, step: int = 5) -> list:
    """Những điều ĐÁNG KỂ có thật trong bảng, tính bằng code -> các dòng điểm nhấn.

    named: {tên: [(năm, giá trị)] tăng dần theo năm} (chuỗi theo NĂM đầy đủ); focus: tên cần kể kỹ,
    tên đầu là "ta" (Việt Nam). Gồm: năm hai nước vượt nhau, khoảng cách đầu–cuối, đỉnh/đáy nằm
    GIỮA chuỗi, giai đoạn `step` năm thay đổi nhanh nhất, và mốc tròn lớn nhất vừa vượt qua."""
    pct = unit.startswith("%")
    names = [n for n in focus if len(named.get(n) or []) >= 2]
    if not names:
        return []
    out = []
    a = names[0]
    da = dict(named[a])
    if len(names) > 1:
        b = names[1]
        db = dict(named[b])
        common = sorted(set(da) & set(db))
        crosses = []
        for y0, y1 in zip(common, common[1:]):
            s0, s1 = da[y0] - db[y0], da[y1] - db[y1]
            if s0 and s1 and (s0 > 0) != (s1 > 0):
                lead, other = (a, b) if s1 > 0 else (b, a)
                crosses.append(f"Năm {y1}: {lead} vượt {other} ({lead} {_fmt(dict(named[lead])[y1], unit)},"
                               f" {other} {_fmt(dict(named[other])[y1], unit)})")
        out += crosses[:1] + crosses[-1:] if len(crosses) > 1 else crosses
        if len(common) >= 2:
            y0, y1 = common[0], common[-1]
            if pct:
                g0 = round(shown_value(da[y0]) - shown_value(db[y0]), 6)
                g1 = round(shown_value(da[y1]) - shown_value(db[y1]), 6)
                if abs(abs(g1) - abs(g0)) >= 3:
                    side = lambda g: f"{a} {'hơn' if g > 0 else 'kém'} {b} {vn_number(abs(g))} điểm phần trăm"
                    out.append(f"Khoảng cách: năm {y0} {side(g0)}; năm {y1} {side(g1)}")
            elif min(da[y0], db[y0], da[y1], db[y1]) > 0:
                r = lambda y: (max(da[y], db[y]) / min(da[y], db[y]), a if da[y] >= db[y] else b,
                               b if da[y] >= db[y] else a)
                (r0, h0, l0), (r1, h1, l1) = r(y0), r(y1)
                if r0 >= 1.2 or r1 >= 1.2:
                    if h0 != h1 or abs(r1 - r0) / max(r0, r1) >= 0.2:
                        out.append(f"Khoảng cách: năm {y0} {h0} gấp {vn_number(r0)} lần {l0};"
                                   f" năm {y1} {h1} gấp {vn_number(r1)} lần {l1}")
    for n in names[:2]:
        s = named[n]
        ys = [v for _, v in s]
        top = max(range(len(s)), key=lambda i: ys[i])
        low = min(range(len(s)), key=lambda i: ys[i])
        if 0 < top < len(s) - 1 and ys[top] > 0 and ys[-1] < 0.95 * ys[top]:
            out.append(f"Đỉnh của {n}: năm {s[top][0]} ({_fmt(ys[top], unit)}); năm {s[-1][0]} còn"
                       f" {_fmt(ys[-1], unit)}")
        if 0 < low < len(s) - 1 and ys[low] >= 0 and ys[-1] > 1.05 * ys[low] and ys[0] > 1.05 * ys[low]:
            out.append(f"Đáy của {n}: năm {s[low][0]} ({_fmt(ys[low], unit)}), rồi hồi lên"
                       f" {_fmt(ys[-1], unit)} năm {s[-1][0]}")
    s = named[a]
    best = None
    for y, v in s:
        if y + step in da:
            d = da[y + step] - v
            if best is None or abs(d) > abs(best[2]):
                best = (y, v, d)
    if best and len(s) >= 3 and best[2] != 0 and s[-1][0] - s[0][0] >= 2 * step:
        y, v, d = best
        out.append(f"Giai đoạn {a} thay đổi nhanh nhất: {y}–{y + step}, từ {_fmt(v, unit)}"
                   f" {'lên' if d > 0 else 'xuống'} {_fmt(v + d, unit)}")
    first, last = s[0][1], s[-1][1]
    up = last > first
    crossed = []
    for m in _milestones(min(first, last), max(first, last), pct):
        for (y0, v0), (y1, v1) in zip(s, s[1:]):
            if (up and v0 < m <= v1) or (not up and v0 > m >= v1):
                crossed.append((m, y1))
                break
    if crossed:
        m, y = crossed[-1] if up else crossed[0]
        out.append(f"{a} {'vượt' if up else 'xuống dưới'} mốc {_fmt(m, unit)} vào năm {y}")
    return out


def trim_leading(*series, share: float = 0.001) -> tuple:
    """Bỏ các năm đầu mà MỌI chuỗi còn gần bằng 0 (dưới 0,1% giá trị lớn nhất): thuê bao di động
    1960-1985 toàn số 0, câu chuyện phải bắt đầu từ năm có số thật. Ca thật #30 (video #7): câu
    "Nhìn lại năm 1960, cả Việt Nam và Hàn Quốc đều ghi nhận 0 thuê bao" là chỗ người xem bỏ đi.
    Ngưỡng thấp có chủ ý: GDP đầu người Hàn Quốc 1960 (159 USD, 0,4% mức 2025) là chuyện đáng kể."""
    peak = max((abs(v) for s in series for _, v in s), default=0)
    start = min((y for s in series for y, v in s if abs(v) >= share * peak), default=None) if peak else None
    if start is None:
        return series
    return tuple([p for p in s if p[0] >= start] for s in series)


def beats_lines(beats: list) -> list:
    return [BEATS_HEADER] + [f"• {b}." for b in beats] if beats else []


def race_lines(series: dict, years: list, focus: list, unit: str = None) -> list:
    """Phần thân tóm tắt của một "cuộc đua": xếp hạng năm đầu/năm cuối, dòng "ai vượt ai"
    cho các đối tượng trọng tâm, điểm nhấn (giai đoạn leo hạng mạnh nhất; có `unit` thì thêm điểm
    nhấn về số liệu — story_beats), rồi bảng theo năm.
    series: {tên: [(năm, giá trị), ...]}; years: mốc năm (mọi tên đều có số); focus: tên cần kể kỹ."""
    at = {n: dict(s) for n, s in series.items()}
    y0, y1 = years[0], years[-1]
    first = ranking({n: at[n][y0] for n in series})
    last = ranking({n: at[n][y1] for n in series})

    def rank_line(y, order):
        return f"Xếp hạng năm {y}: " + "; ".join(
            f"{k + 1}. {n} {vn_number(at[n][y])}" for k, n in enumerate(order)) + "."
    lines = [rank_line(y0, first), rank_line(y1, last)]
    for n in focus:
        if n not in series:
            continue
        r0, r1 = first.index(n) + 1, last.index(n) + 1
        passed = [m for m in first[:r0 - 1] if last.index(m) > r1 - 1]       # trước ở trên, sau ở dưới
        lost = [m for m in first[r0:] if last.index(m) < r1 - 1]             # trước ở dưới, sau ở trên
        line = f"{n}: hạng {r0} năm {y0}, hạng {r1} năm {y1}"
        if passed:
            line += " — vượt " + ", ".join(passed)
        if lost:
            line += ("; " if passed else " — ") + "bị vượt bởi " + ", ".join(lost)
        lines.append(line + ".")
    beats = story_beats(series, [n for n in focus if n in series], unit) if unit is not None else []
    for n in focus:                       # giai đoạn leo (hoặc tụt) hạng mạnh nhất giữa hai mốc liền nhau
        if n not in series or len(years) < 3:
            continue
        ranks = [ranking({m: at[m][y] for m in series}).index(n) + 1 for y in years]
        k = max(range(len(years) - 1), key=lambda i: abs(ranks[i] - ranks[i + 1]))
        if ranks[k] != ranks[k + 1]:
            verb = "leo" if ranks[k + 1] < ranks[k] else "tụt"
            beats.append(f"Giai đoạn {n} {verb} hạng mạnh nhất: {years[k]}–{years[k + 1]}, từ hạng"
                         f" {ranks[k]} {'lên' if verb == 'leo' else 'xuống'} hạng {ranks[k + 1]}")
    lines += beats_lines(beats)
    for n in sorted(series, key=lambda n: -at[n][y1]):
        lines.append(f"{n} theo năm: " + "; ".join(f"{y}: {vn_number(at[n][y])}" for y in years) + ".")
    return lines
