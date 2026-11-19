"""Soát bằng CODE các câu SO SÁNH trong lời đọc, đối chiếu với bảng số của ý tưởng
(World Bank, Our World in Data, KOSIS — các dòng "<Tên> theo năm: ..." trong tóm tắt).

Vì sao có file này (ca thật 19/11/2026, kịch bản #46): câu mở đầu
    "Hàn Quốc năm 2025 mới đạt tỷ lệ phụ nữ đi làm mà Việt Nam đã có từ năm 1990."
là SAI (Hàn Quốc 2025: 56,8%; Việt Nam 1990: 74,7%) mà vẫn "Kiểm chứng ĐẠT":
- cổng chống bịa số (crew.unsourced_numbers) chỉ hỏi "con số có trong nguồn không" — 2025 và
  1990 đều có;
- agent Kiểm chứng (LLM) chỉ soát các "claims" do chính Biên kịch khai, câu hook không nằm trong đó.
Mà "X năm A mới bằng Y năm B" lại là kiểu hook mạnh nhất kênh khuyến khích (crew.HOOK_GUIDE) —
nên cần một cổng riêng, bằng code, không nhờ model nhỏ phán.

Ba dạng câu được soát, CHỈ khi câu nhắc đúng hai đối tượng có trong bảng (nước, "Thế giới"...)
và từ so sánh nằm GIỮA hai tên, không bị ngắt bởi dấu phẩy/"còn"/"trong khi" (tránh báo nhầm câu
ghép kiểu "Việt Nam gần bằng 75%, còn Hàn Quốc năm 2025 là 56,8%"):
- MỐC THỜI GIAN: "A năm Y1 (hoặc "hôm nay" = năm mới nhất) mới bằng/đạt/ngang B năm Y2" -> hai giá
  trị phải lệch nhau không quá 5%
  (cùng ngưỡng với worldbank.catch_up_year), hoặc tóm tắt có sẵn dòng "A năm Y1 (...) tương đương
  B năm Y2". Bảng không có năm đó để kiểm cũng tính là lỗi: model chỉ được dùng mốc đã tính sẵn.
- HƠN/KÉM trong MỘT năm: "năm Y, A cao hơn B" -> so giá trị năm Y (bảng không có năm đó thì bỏ qua).
- GẤP N LẦN: "A gấp N lần B" mà số liệu nói ngược lại (B mới là bên gấp N lần A).
Câu phủ định ("chưa bằng", "không bằng") và câu nói về mức TĂNG/GIẢM ("tăng nhiều hơn") không soát.
"""
import re

from .sources.datatable import parse_series, parse_vn_number, parse_world_table, vn_number

TOLERANCE = 0.05            # "ngang nhau" = lệch không quá 5% (như worldbank.catch_up_year)
RATIO_TOLERANCE = 0.03      # "gấp N lần": tỉ số thật lệch N quá 3% thì không phải N

YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
CATCH_UP = re.compile(r"\b(?:mới\s+(?:bằng|đạt|ngang|chạm|tới)|bằng|ngang|tương\s+đương|"
                      r"đã\s+(?:có|đạt)(?:\s+được)?\s+từ|chạm\s+(?:mức|mốc)|bắt\s+kịp|đuổi\s+kịp)\b",
                      re.I)
NEGATED = re.compile(r"\b(?:chưa|không|chẳng)\s+(?:hề\s+|thể\s+)?(?:bằng|đạt|tới|chạm|ngang|"
                     r"bắt\s+kịp|đuổi\s+kịp)\b", re.I)
MORE = re.compile(r"\b(?:cao\s+hơn|nhiều\s+hơn|lớn\s+hơn|vượt(?:\s+qua)?|bỏ\s+xa)\b", re.I)
LESS = re.compile(r"\b(?:thấp\s+hơn|ít\s+hơn|nhỏ\s+hơn|kém|thua)\b", re.I)
CHANGE = re.compile(r"\b(?:tăng|giảm|nhanh|chậm|tốc\s+độ)\b", re.I)
# "hôm nay" = năm mới nhất trong bảng. Ca thật #37 (19/11): "Việt Nam HÔM NAY mới bằng Hàn Quốc năm
# 1990 về đô thị hóa" (38,8% so với 74%) lọt bản đầu của cổng này vì câu không ghi năm cho Việt Nam.
NOW = re.compile(r"\b(?:hôm\s+nay|hiện\s+nay|ngày\s+nay|bây\s+giờ|hiện\s+tại|năm\s+nay|mới\s+nhất)\b",
                 re.I)
# dấu phẩy NGẮT CÂU, không phải dấu thập phân ("gấp 7,15 lần" không bị coi là hai vế)
SEPARATOR = re.compile(r"[,;:](?!\d)|\b(?:còn|trong\s+khi|nhưng|tuy\s+nhiên)\b", re.I)
TIMES = re.compile(r"gấp\s+(\d[\d.,]*)\s+lần", re.I)
SAME_LINE = re.compile(r"^\s*(.+?) năm ((?:19|20)\d{2}) \([^)]*\) tương đương (.+?) năm ((?:19|20)\d{2})",
                       re.M)


def data_table(summary: str) -> dict:
    """{nhãn: {năm: giá trị}} đọc từ tóm tắt: các dòng "theo năm" + bảng mọi nước (bản đồ thế giới)."""
    table = {s["label"]: dict(zip(s["xs"], s["ys"])) for s in parse_series(summary)}
    world = parse_world_table(summary)
    if world:
        for it in world["items"]:
            table.setdefault(it["label"], {}).setdefault(world["year"], it["value"])
    return table


def _label_pattern(lab: str) -> str:
    """Tên riêng so KHỚP HOA THƯỜNG để "Ý" (nước Ý) không khớp chữ "ý" (ý nghĩa); riêng tên nhiều
    tiếng thì chữ cái đầu được viết thường ("mức của thế giới" khớp nhãn "Thế giới")."""
    head = f"(?i:{re.escape(lab[0])})" if len(lab.split()) > 1 else re.escape(lab[0])
    return r"(?<!\w)" + head + re.escape(lab[1:]) + r"(?!\w)"


def _mentions(text: str, labels) -> list:
    """[(đầu, cuối, nhãn)] các đối tượng được nhắc, theo thứ tự trong câu; hai nhãn chồng nhau thì
    nhãn dài thắng ("Việt Nam" không bị đọc thành "Nam Phi")."""
    taken, out = [], []
    for lab in sorted(labels, key=len, reverse=True):
        for m in re.finditer(_label_pattern(lab), text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), m.end(), lab))
    return sorted(out)


def _assign_years(text: str, mentions: list, table: dict = None) -> dict:
    """{nhãn: năm}: mỗi đối tượng nhận năm ĐẦU TIÊN đứng sau tên nó (trước tên kế tiếp). Đối tượng
    không có năm phía sau nhận năm còn thừa — "Năm 2024, Việt Nam mới bằng Hàn Quốc năm 1991" — hoặc,
    nếu câu nói "hôm nay/hiện nay…", năm mới nhất của nó trong bảng."""
    years = [(m.start(), int(m.group())) for m in YEAR.finditer(text)]
    got = {}
    for k, (_, end, lab) in enumerate(mentions):
        nxt = mentions[k + 1][0] if k + 1 < len(mentions) else len(text)
        if lab in got:
            continue
        y = next((y for pos, y in years if end <= pos < nxt), None)
        if y is not None:
            got[lab] = y
    labels = list(dict.fromkeys(lab for _, _, lab in mentions))
    left = [y for _, y in years if y not in got.values()]
    missing = [lab for lab in labels if lab not in got]
    if len(missing) == 1 and len(set(left)) == 1:
        got[missing[0]] = left[0]
    elif len(missing) == 1 and not left and NOW.search(text) and (table or {}).get(missing[0]):
        got[missing[0]] = max(table[missing[0]])
    return got


def _short(text: str, n: int = 70) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _check_catch_up(text, between, labels, years, table, known_pairs) -> str:
    if not CATCH_UP.search(between) or NEGATED.search(text):
        return ""
    a, b = labels
    ya, yb = years.get(a), years.get(b)
    if ya is None or yb is None or ya == yb:
        return ""
    va, vb = table.get(a, {}).get(ya), table.get(b, {}).get(yb)
    if va is not None and vb is not None:
        if abs(va - vb) <= TOLERANCE * max(abs(va), abs(vb)):
            return ""
        return (f"câu “{_short(text)}” so sánh mốc thời gian SAI: {a} năm {ya} là {vn_number(va)},"
                f" {b} năm {yb} là {vn_number(vb)} — hai mức không ngang nhau")
    if (a, ya, b, yb) in known_pairs:
        return ""
    return (f"câu “{_short(text)}” so {a} năm {ya} với {b} năm {yb} nhưng bảng số không có căn cứ —"
            " chỉ dùng mốc “tương đương” đã tính sẵn trong tóm tắt, hoặc so cùng một năm")


def _check_direction(text, between, labels, table) -> str:
    a, b = labels[0], labels[1]
    years = sorted({int(m.group()) for m in YEAR.finditer(text)})
    if not years and NOW.search(text):              # "hiện nay A cao hơn B" = năm chung mới nhất
        common = set(table.get(a, {})) & set(table.get(b, {}))
        years = [max(common)] if common else []
    more, less = MORE.search(between), LESS.search(between)
    if len(years) != 1 or bool(more) == bool(less) or CHANGE.search(between):
        return ""
    y = years[0]
    va, vb = table.get(a, {}).get(y), table.get(b, {}).get(y)
    if va is None or vb is None or va == vb:
        return ""
    if (more and va < vb) or (less and va > vb):
        return (f"câu “{_short(text)}” nói {a} {'cao' if more else 'thấp'} hơn {b} năm {y} nhưng bảng"
                f" ghi {a} {vn_number(va)}, {b} {vn_number(vb)} — ngược chiều")
    return ""


def _check_times(text, between_start, between_end, labels, table, summary) -> str:
    m = TIMES.search(text, between_start, between_end)
    if not m:
        return ""
    a, b, num = labels[0], labels[1], m.group(1).rstrip(".,")
    inverted = f"{b} gấp {num} lần {a}" in summary and f"{a} gấp {num} lần {b}" not in summary
    years = sorted({int(y.group()) for y in YEAR.finditer(text)})
    if not inverted and len(years) == 1:
        va, vb = table.get(a, {}).get(years[0]), table.get(b, {}).get(years[0])
        try:
            claimed = parse_vn_number(num)
        except ValueError:
            claimed = 0
        if va and vb and claimed:
            close = lambda r: abs(r - claimed) <= RATIO_TOLERANCE * claimed
            inverted = close(vb / va) and not close(va / vb)
    if inverted:
        return f"câu “{_short(text)}” đảo chiều: số liệu là {b} gấp {num} lần {a}, không phải ngược lại"
    return ""


def comparison_problems(texts, summary: str) -> list:
    """Các câu so sánh SAI hoặc không kiểm được trong `texts` (danh sách câu) -> danh sách lý do.
    Tóm tắt không có bảng số (ý tưởng bài báo) thì không có gì để soát -> []."""
    summary = str(summary or "")
    table = data_table(summary)
    if not table:
        return []
    known = set()
    for m in SAME_LINE.finditer(summary):
        a, ya, b, yb = m.group(1).strip(), int(m.group(2)), m.group(3).strip(), int(m.group(4))
        known |= {(a, ya, b, yb), (b, yb, a, ya)}
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        mentions = _mentions(text, table)
        labels = list(dict.fromkeys(lab for _, _, lab in mentions))
        if len(labels) != 2:
            continue
        first_a = mentions[0]
        first_b = next(m for m in mentions if m[2] == labels[1])
        between = text[first_a[1]:first_b[0]]
        if SEPARATOR.search(between):
            continue
        problem = (_check_catch_up(text, between, labels, _assign_years(text, mentions, table), table,
                                   known)
                   or _check_direction(text, between, labels, table)
                   or _check_times(text, first_a[1], first_b[0], labels, table, summary))
        if problem:
            out.append(problem)
    return out


# Câu nêu NGUYÊN NHÂN / BỐI CẢNH. Bảng số (World Bank, OWID, KOSIS) chỉ có con số, không có nguyên
# nhân -> câu kiểu này trong kịch bản từ bảng số là model tự thêm. Ca thật kịch bản #23 (video #6):
# "Sự mở cửa đã thu hút mạnh mẽ các dự án quốc tế lớn" — không có trong nguồn, và là chỗ người xem
# bỏ đi. Chỉ bắt những cụm gán nguyên nhân RÕ RÀNG (chính sách, cải cách, mở cửa...) cho khỏi chặn oan.
CAUSE = re.compile(r"\b(?:nhờ\s+(?:vào|có|chính\s+sách)|chính\s+sách|cải\s+cách|đổi\s+mới|mở\s+cửa|"
                   r"là\s+kết\s+quả\s+của|xuất\s+phát\s+từ|bởi\s+vì|nguyên\s+nhân|"
                   r"do\s+(?:chính\s+phủ|nhà\s+nước|chính\s+sách|tác\s+động|ảnh\s+hưởng))\b", re.I)


def cause_claims(texts, summary: str) -> list:
    """Câu khẳng định nguyên nhân/bối cảnh trong kịch bản từ BẢNG SỐ mà tóm tắt không nói -> lý do.
    Câu hỏi ("Vì sao…?") không khẳng định gì nên bỏ qua; ý tưởng bài báo (không có bảng) không soát
    ở đây — bài báo có thể nói nguyên nhân, agent Kiểm chứng đối chiếu."""
    summary = str(summary or "")
    if not data_table(summary):
        return []
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        if not text or text.endswith("?"):
            continue
        m = CAUSE.search(text)
        if m and m.group(0).lower() not in summary.lower():
            out.append(f"câu “{_short(text)}” nêu nguyên nhân/bối cảnh (“{m.group(0)}”) mà bảng số"
                       " không nói — bỏ, thay bằng điểm nhấn hoặc cách nói dễ hình dung có trong tóm tắt")
    return out


def script_cause_claims(script: dict, summary: str) -> list:
    return cause_claims([s.get("voice", "") for s in script.get("scenes") or [] if isinstance(s, dict)],
                        summary)


def script_comparison_problems(script: dict, summary: str) -> list:
    """comparison_problems trên lời đọc của mọi cảnh trong một kịch bản."""
    return comparison_problems([s.get("voice", "") for s in script.get("scenes") or []
                                if isinstance(s, dict)], summary)
