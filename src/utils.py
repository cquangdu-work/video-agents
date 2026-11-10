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


def extract_json(text: str):
    """LLM hay trả JSON kèm chữ thừa/markdown — hàm này móc khối JSON đầu tiên ra."""
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    for opener, closer in [("[", "]"), ("{", "}")]:
        start = text.find(opener)
        if start == -1:
            continue
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
