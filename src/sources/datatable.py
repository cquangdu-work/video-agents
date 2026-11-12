"""Hàm dùng chung cho các nguồn ý tưởng dạng BẢNG SỐ LIỆU (World Bank, KOSIS...).

Ý tưởng từ bảng số có tóm tắt viết theo một khuôn cố định, để:
- Biên kịch chép số đúng dạng Việt ("36.227", "98,9") -> cổng chống bịa số khớp được;
- code đọc ngược lại được chuỗi số theo năm (parse_series) -> biểu đồ lấy số thẳng từ bảng.
Khuôn quan trọng nhất: mỗi đối tượng một dòng "<Tên> theo năm: 2022: 1.234; 2023: 1.456."
"""
import re

WB_SOURCE = "World Bank Open Data"
KOSIS_SOURCE = "KOSIS — Thống kê Hàn Quốc"
DATA_SOURCES = {WB_SOURCE, KOSIS_SOURCE}


def is_data_source(name) -> bool:
    """Ý tưởng này đến từ kho dữ liệu (tóm tắt CHÍNH LÀ bảng số) chứ không phải bài báo."""
    return name in DATA_SOURCES


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


def lower_first(name: str) -> str:
    """Viết thường chữ đầu để ghép vào câu, trừ khi từ đầu là chữ viết tắt ("GDP ...")."""
    first_word = name.split()[0] if name.split() else ""
    if len(first_word) > 1 and first_word.isupper():
        return name
    return name[:1].lower() + name[1:]


def race_lines(series: dict, years: list, focus: list) -> list:
    """Phần thân tóm tắt của một "cuộc đua": xếp hạng năm đầu/năm cuối, dòng "ai vượt ai"
    cho các đối tượng trọng tâm, rồi bảng theo năm.
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
    for n in sorted(series, key=lambda n: -at[n][y1]):
        lines.append(f"{n} theo năm: " + "; ".join(f"{y}: {vn_number(at[n][y])}" for y in years) + ".")
    return lines
