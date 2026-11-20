"""Hàm dùng chung: chuẩn hóa tiêu đề, đo độ giống nhau, tách JSON từ câu trả lời LLM."""
import json
import re
import unicodedata

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "is", "are",
    "la", "va", "cua", "mot", "nhung", "duoc", "khong", "trong", "den", "voi",
}


def norm_title(title: str) -> str:
    """Bỏ dấu, viết thường, bỏ ký tự lạ — để so sánh trùng lặp."""
    s = unicodedata.normalize("NFD", title.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())


def title_tokens(title: str) -> set:
    return {w for w in norm_title(title).split() if w not in _STOPWORDS and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard trên tập từ khóa: 0 = khác hẳn, 1 = trùng khít."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def digit_set(text: str) -> set:
    """Tập 'chuỗi chữ số' trong văn bản: '8.030 hệ thống, 29,3 tuổi' -> {'8030','293'}.
    Dùng để bắt LLM bịa số: số trong spec phải có mặt trong kịch bản."""
    return {re.sub(r"[.,\s]", "", m) for m in re.findall(r"\d[\d.,]*", text)}


def digits_of(value) -> set:
    """Các dạng chữ số hợp lệ của một giá trị, kể cả khi kịch bản viết '5 triệu'
    còn spec viết 5000000 (thử chia 1 nghìn/triệu/tỷ)."""
    out = set()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return out
    from . import lang                    # kênh Hàn nói số theo bội 10.000 (만, 억, 조)
    for scaled in (v, *(v / d for d in lang.scale_divisors())):
        s = f"{scaled:.10g}"
        if "e" not in s:
            out.add(re.sub(r"[.,\s-]", "", s))
    return out


def number_values(text: str) -> set:
    """Mọi giá trị số có thể đọc ra từ văn bản, thử CẢ hai cách viết: kiểu Việt
    ("2.462" = 2462, "4,90" = 4,9) và kiểu Anh ("2,462" = 2462, "4.90" = 4,9).
    So theo GIÁ TRỊ thì "4,9" khớp "4,90"; so chuỗi chữ số ("49" với "490") thì không."""
    out = set()
    for tok in re.findall(r"\d[\d.,]*\d|\d", str(text)):
        for cand in (tok.replace(".", "").replace(",", "."), tok.replace(",", "")):
            try:
                out.add(float(cand))
            except ValueError:
                pass
    return out


def spec_values(params: dict) -> list:
    """Mọi con số SỐ LIỆU mà một cảnh hiển thị (không tính trục năm xs, số thứ tự n).
    Dùng chung cho cổng chống bịa số (crew) và Kiểm định (qc) — thêm template mới có
    trường số mới thì chỉ sửa ở đây."""
    if not isinstance(params, dict):
        return []
    vals = [params.get("value")]
    vals += [i.get("value") for i in params.get("items") or [] if isinstance(i, dict)]
    for i in params.get("items") or []:                      # bar_race: mỗi nước một chuỗi năm
        if isinstance(i, dict):
            vals += list(i.get("values") or [])
    vals += [params[side].get("value") for side in ("left", "right")
             if isinstance(params.get(side), dict)]
    vals += list(params.get("ys") or [])
    for s in params.get("series") or []:
        if isinstance(s, dict):
            vals += list(s.get("ys") or [])
    return [v for v in vals if v is not None]


def extract_json(text: str):
    """LLM hay trả JSON kèm chữ thừa/markdown — hàm này móc khối JSON đầu tiên ra."""
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    # Lấy khối JSON xuất hiện TRƯỚC trong văn bản (không ưu tiên [ hơn {,
    # kẻo object chứa mảng con sẽ bị móc nhầm mảng con ra)
    starts = [(text.find(o), o, c) for o, c in [("[", "]"), ("{", "}")] if text.find(o) != -1]
    for start, opener, closer in sorted(starts):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"Không tìm thấy JSON hợp lệ trong: {text[:200]}...")
