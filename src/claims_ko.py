"""Cổng soát câu SO SÁNH / NGUYÊN NHÂN / XU HƯỚNG / CÂU CHỮ cho kịch bản TIẾNG HÀN (20/11/2026).

Cùng nguyên tắc với src/claims.py (đọc docstring ở đó: ca thật #46, #37 — câu so sánh sai mà agent Kiểm chứng
LLM vẫn cho qua, chỉ cổng code bắt được), nhưng tiếng Hàn đảo trật tự câu (chủ ngữ – tân ngữ – động từ):
    한국은 일본보다 높다          A (은/는/이/가) B보다 <so sánh>          -> từ so sánh đứng SAU cả hai tên
    일본은 한국의 1.54배          A (은/는) B의 N배                       -> B là tên đứng ngay trước "의"
    2024년 한국은 1990년 일본 수준  năm–tên, năm–tên, "수준/같은/따라잡"     -> mốc thời gian
    한국이 2018년 일본을 앞질렀다   A (이/가) … B(을/를) 앞지르/추월/넘어서  -> năm vượt
nên không dùng lại được logic "từ so sánh nằm GIỮA hai tên" của bản Việt.

Lời báo lỗi viết bằng TIẾNG VIỆT, giữ đúng các cụm khoá của bản Việt ("so sánh mốc thời gian SAI", "ngược
chiều", "đảo chiều", "nguyên nhân/bối cảnh", "liên tục nhưng", "hiệu hai tỷ lệ", "nói như dự báo", "bảng chỉ có
từ năm", "đã vượt", "không trả lời được nguyên nhân"): learning.kind_of phân loại lỗi theo chính các cụm đó
(bộ nhớ tự học), và Biên kịch nhận lời báo lỗi để viết lại.
"""
import re

from .claims import RATIO_TOLERANCE, TOLERANCE, _short, data_table
from .sources.datatable import parse_vn_number, vn_number

NOW = re.compile(r"(현재|지금|오늘날|요즘|최근|최신)")
SEPARATOR = re.compile(r"[;:]|(?:,\s)|반면|하지만|그러나|한편")
# đuôi động từ đổi theo cách chia: 미치다 -> 미칩니다 / 미쳐 / 미쳤다
NEGATED = re.compile(r"(못\s*미[치칩쳐쳤]|미치지\s*못|못했|못한|못합|아직|않았|않는다|않습)")
CATCH_UP = re.compile(r"(수준|같은|같다|맞먹|비슷|따라잡|도달|이르렀)")
# sau "보다" có thể chen tối đa 2 cụm ("일본보다 출산율이 높다", "일본보다 훨씬 더 많다")
MORE = re.compile(r"^\s*(?:[^\s\d]+\s+){0,2}?(?:훨씬\s*|더\s*|조금\s*)?(높|많|크|길|앞서|앞선|비싸|위)")
LESS = re.compile(r"^\s*(?:[^\s\d]+\s+){0,2}?(?:훨씬\s*|더\s*|조금\s*)?(낮|적|작|짧|뒤처|뒤진|싸|아래)")
CHANGE = re.compile(r"(증가|감소|늘|줄|성장|빠르게|느리게|속도|상승|하락)")
TIMES_OF = re.compile(r"의\s*(\d[\d.,]*)\s*배")
TIMES_THAN = re.compile(r"보다\s*(\d[\d.,]*)\s*배")
SAME_LINE = re.compile(r"^\s*((?:19|20)\d{2})년 (.+?) 수치\([^)]*\)는 ((?:19|20)\d{2})년 (.+?) 수치\([^)]*\)와 같은 수준",
                       re.M)
YEAR_KO = re.compile(r"(?<!\d)((?:19|20)\d{2})(?=년|\b|\D)")


def _mentions(text: str, labels) -> list:
    """[(đầu, cuối, nhãn)] như claims._mentions, nhưng trợ từ được DÍNH liền sau tên ("한국은", "일본의") —
    chỉ đòi phía TRƯỚC tên không phải chữ. Nhãn dài thắng ("한국계중국인" không bị đọc thành "한국")."""
    taken, out = [], []
    for lab in sorted(labels, key=len, reverse=True):
        for m in re.finditer(r"(?<![\w가-힣])" + re.escape(lab), text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), m.end(), lab))
    return sorted(out)


def _years(text: str) -> list:
    return [(m.start(), int(m.group(1))) for m in YEAR_KO.finditer(text)]


def _two_labels(text: str, table: dict):
    mentions = _mentions(text, table)
    labels = list(dict.fromkeys(lab for _, _, lab in mentions))
    return (mentions, labels) if len(labels) == 2 else (mentions, None)


def _known_pairs(summary: str) -> set:
    known = set()
    for m in SAME_LINE.finditer(summary):
        ya, a, yb, b = int(m.group(1)), m.group(2).strip(), int(m.group(3)), m.group(4).strip()
        known |= {(a, ya, b, yb), (b, yb, a, ya)}
    return known


def _check_catch_up(text, mentions, labels, table, known) -> str:
    if not CATCH_UP.search(text) or NEGATED.search(text):
        return ""
    years = _years(text)
    order = [lab for lab in dict.fromkeys(lab for _, _, lab in mentions)]
    got = {}
    if len(years) == 2:                              # năm thứ nhất đi với tên thứ nhất (cả "2024년 한국",
        got = {order[0]: years[0][1], order[1]: years[1][1]}     # lẫn "한국의 2024년 수치")
    elif len(years) == 1 and NOW.search(text):       # "현재 한국은 1990년 일본 수준": tên không có năm = năm mới nhất
        pos, y = years[0]
        near = min(mentions, key=lambda m: abs(m[0] - pos))[2]
        other = order[1] if near == order[0] else order[0]
        if table.get(other):
            got = {near: y, other: max(table[other])}
    a, b = order
    ya, yb = got.get(a), got.get(b)
    if ya is None or yb is None or ya == yb:
        return ""
    va, vb = table.get(a, {}).get(ya), table.get(b, {}).get(yb)
    if va is not None and vb is not None:
        if abs(va - vb) <= TOLERANCE * max(abs(va), abs(vb)):
            return ""
        return (f"câu “{_short(text)}” so sánh mốc thời gian SAI: {a} năm {ya} là {vn_number(va)},"
                f" {b} năm {yb} là {vn_number(vb)} — hai mức không ngang nhau")
    if (a, ya, b, yb) in known:
        return ""
    return (f"câu “{_short(text)}” so {a} năm {ya} với {b} năm {yb} nhưng bảng số không có căn cứ —"
            " chỉ dùng mốc “같은 수준” đã tính sẵn trong tóm tắt, hoặc so cùng một năm")


def _one_year(text, a, b, table):
    years = sorted({y for _, y in _years(text)})
    if not years and NOW.search(text):
        common = set(table.get(a, {})) & set(table.get(b, {}))
        years = [max(common)] if common else []
    return years[0] if len(years) == 1 else None


def _check_direction(text, mentions, labels, table) -> str:
    """"A는 B보다 높다/낮다": B = tên đứng ngay trước "보다"."""
    for m in re.finditer(r"보다", text):
        before = [x for x in mentions if x[1] <= m.start() and not text[x[1]:m.start()].strip(" 의")]
        if not before:
            continue
        b = before[-1][2]
        a = labels[0] if labels[1] == b else labels[1]
        after = text[m.end():m.end() + 20]
        more, less = MORE.search(after), LESS.search(after)
        if bool(more) == bool(less) or CHANGE.search(after) or re.match(r"\s*\d", after):
            continue
        y = _one_year(text, a, b, table)
        va, vb = table.get(a, {}).get(y), table.get(b, {}).get(y)
        if y is None or va is None or vb is None or va == vb:
            continue
        if (more and va < vb) or (less and va > vb):
            return (f"câu “{_short(text)}” nói {a} {'cao' if more else 'thấp'} hơn {b} năm {y} nhưng bảng"
                    f" ghi {a} {vn_number(va)}, {b} {vn_number(vb)} — ngược chiều")
    return ""


def _check_times(text, mentions, labels, table, summary) -> str:
    """"A는 B의 N배" (B đứng trước 의) hoặc "A가 B보다 N배" — tỉ số thật phải là A/B, không phải B/A."""
    for pat in (TIMES_OF, TIMES_THAN):
        for m in pat.finditer(text):
            before = [x for x in mentions if x[1] <= m.start() and not text[x[1]:m.start()].strip()]
            if not before:
                continue
            b = before[-1][2]
            a = labels[0] if labels[1] == b else labels[1]
            num = m.group(1).rstrip(".,")
            inverted = (re.search(rf"{re.escape(b)}[은는] {re.escape(a)}의 {re.escape(num)}배", summary)
                        and not re.search(rf"{re.escape(a)}[은는] {re.escape(b)}의 {re.escape(num)}배", summary))
            y = _one_year(text, a, b, table)
            if not inverted and y is not None:
                va, vb = table.get(a, {}).get(y), table.get(b, {}).get(y)
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
    summary = str(summary or "")
    table = data_table(summary)
    if not table:
        return []
    known = _known_pairs(summary)
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        mentions, labels = _two_labels(text, table)
        if not labels:
            continue
        problem = (_check_catch_up(text, mentions, labels, table, known)
                   or _check_direction(text, mentions, labels, table)
                   or _check_times(text, mentions, labels, table, summary))
        if problem:
            out.append(problem)
    return out


CAUSE = re.compile(r"(때문|덕분|덕택|정책|개혁|개방|(?:으)?로\s*인해|원인|결과로|영향으로|힘입어|탓)")


def cause_claims(texts, summary: str) -> list:
    summary = str(summary or "")
    if not data_table(summary):
        return []
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        if not text or text.endswith("?"):
            continue
        m = CAUSE.search(text)
        if m and m.group(0) not in summary:
            out.append(f"câu “{_short(text)}” nêu nguyên nhân/bối cảnh (“{m.group(0)}”) mà bảng số"
                       " không nói — bỏ, thay bằng điểm nhấn hoặc cách nói dễ hình dung có trong tóm tắt")
    return out


_UP = r"증가|늘|상승|오르|올라|성장|높아"
_DOWN = r"감소|줄|하락|떨어|낮아|내려"
TREND = re.compile(rf"(?:꾸준히|계속|줄곧|매년|해마다|끊임없이|쉬지\s*않고)\s*(?:\S+\s+)?(?P<w>{_UP}|{_DOWN})"
                   rf"|한\s*번도\s*(?:\S+\s+)?(?P<n>{_UP}|{_DOWN})[^\s]*\s*않")


def trend_problems(texts, summary: str) -> list:
    table = data_table(str(summary or ""))
    if not table:
        return []
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        m = TREND.search(text)
        if not m:
            continue
        word = m.group("w") or m.group("n")
        up = bool(re.match(_UP, word)) != bool(m.group("n"))      # "한 번도 줄지 않고" = luôn tăng
        before = [x for x in _mentions(text, table) if x[0] < m.start()]
        mentions = before or _mentions(text, table)
        if not mentions:
            continue
        label = mentions[-1][2] if before else mentions[0][2]
        years = sorted(y for _, y in _years(text))
        pts = sorted(table[label].items())
        if len(years) >= 2:
            pts = [p for p in pts if years[0] <= p[0] <= years[-1]]
        bad = next(((a, b) for a, b in zip(pts, pts[1:]) if (b[1] < a[1] if up else b[1] > a[1])), None)
        if bad:
            (y0, v0), (y1, v1) = bad
            out.append(f"câu “{_short(text)}” nói {label} {'tăng' if up else 'giảm'} liên tục nhưng bảng ghi"
                       f" {y0}: {vn_number(v0)} → {y1}: {vn_number(v1)}")
    return out


FUTURE = re.compile(r"(예상|전망|예측|것으로\s*보|할\s*것|될\s*것|것입니다)")
HISTORIC = re.compile(r"(역대\s*최|사상\s*최|역사상|역대급|사상\s*처음)")
OVERTAKE = re.compile(r"(앞질|추월|제쳤|제치|넘어섰|역전)")


def wording_problems(texts, summary: str) -> list:
    summary = str(summary or "")
    table = data_table(summary)
    if not table:
        return []
    years_all = sorted({y for s in table.values() for y in s})
    first_year, last_year = years_all[0], years_all[-1]
    points = set(re.findall(r"(\d[\d.,]*)%p", summary))
    out = []
    for text in texts:
        text = " ".join(str(text or "").split())
        if not text:
            continue
        for x in points:
            if re.search(re.escape(x) + r"\s*%(?!p|포인트)", text) and not re.search(re.escape(x) + r"%(?!p)", summary):
                out.append(f"câu “{_short(text)}” ghi {x}% nhưng đây là hiệu hai tỷ lệ — phải nói “{x}%p”"
                           " (퍼센트포인트)")
        years = [y for _, y in _years(text)]
        if FUTURE.search(text) and not text.endswith("?") and years and min(years) <= last_year:
            out.append(f"câu “{_short(text)}” nói như dự báo (“{FUTURE.search(text).group(0)}”) — số liệu"
                       f" đến năm {last_year} là số ĐÃ GHI NHẬN")
        if HISTORIC.search(text):
            out.append(f"câu “{_short(text)}” nói “{HISTORIC.search(text).group(0)}” — bảng chỉ có từ năm"
                       f" {first_year}: nói “{first_year}년 이후” hoặc “지난 {last_year - first_year}년 동안”")
        out += _overtake_timing(text, table)
    return out


def _overtake_timing(text: str, table: dict) -> list:
    """"A가 Y년 B를 앞질렀다" -> A phải ĐANG kém B ở mốc bảng liền trước Y. B = tên có 을/를 ngay sau."""
    m = OVERTAKE.search(text)
    if not m:
        return []
    mentions = [x for x in _mentions(text, table) if x[0] < m.start()]
    obj = [x for x in mentions if re.match(r"[을를]", text[x[1]:x[1] + 1])]
    if not obj:
        return []
    b = obj[-1][2]
    subj = [x for x in mentions if x[2] != b]
    if not subj:
        return []
    a = subj[0][2]
    ys = [y for _, y in _years(text)]
    if not ys:
        return []
    y = ys[0]
    common = sorted(set(table.get(a, {})) & set(table.get(b, {})))
    if y not in common:
        return []
    prev = [p for p in common if p < y]
    if not prev or table[a][y] <= table[b][y]:
        return []
    p = prev[-1]
    if table[a][p] > table[b][p]:
        lost = [q for q in common if q < y and table[a][q] <= table[b][q]]
        since = f"giữa {lost[-1]} và {next(q for q in common if q > lost[-1])}" if lost else f"trước {common[0]}"
        return [f"câu “{_short(text)}” nói {a} vượt {b} năm {y} nhưng bảng cho thấy {a} đã vượt {b} {since}"
                f" (năm {p}: {vn_number(table[a][p])} so với {vn_number(table[b][p])})"]
    return []


WHY_HOOK = re.compile(r"^\W*(왜|어째서|도대체\s*왜|그\s*이유는)")


def why_hook_problem(script: dict, summary: str) -> str:
    scenes = [s for s in script.get("scenes") or [] if isinstance(s, dict)]
    if scenes and data_table(str(summary or "")) and WHY_HOOK.search(str(scenes[0].get("voice") or "")):
        return ("câu mở đầu hỏi “Vì sao…?” (왜…?) mà video từ bảng số không trả lời được nguyên nhân — mở bằng"
                " đối lập con số, mốc thời gian hoặc thứ hạng bất ngờ")
    return ""
