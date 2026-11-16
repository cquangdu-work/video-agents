"""Agent Đăng bài — phần 1: tiêu đề, mô tả, hashtag cho một video đã dựng xong.

LLM chỉ ĐỀ XUẤT; mọi thứ đi qua finalize() là code thuần (không gọi mạng) để:
  - ép giới hạn của YouTube (tiêu đề <= 100 ký tự, mô tả <= 5000, thẻ <= 500),
  - bắt tiêu đề chứa con số KHÔNG có trong kịch bản (cùng luật chống bịa số
    với agent Sản xuất — tiêu đề sai số là sai ngay chỗ nhiều người đọc nhất),
  - luôn gắn nguồn + dòng khai báo AI vào mô tả (luật chính sách trong CLAUDE.md).
"""
import logging
import re

from ..utils import digit_set, norm_title

log = logging.getLogger(__name__)

TITLE_MAX = 100          # giới hạn cứng của YouTube
DESCRIPTION_MAX = 5000
TAGS_MAX_CHARS = 400     # YouTube cho 500, chừa lề vì cách đếm của họ tính cả dấu phẩy/ngoặc


def _clean_line(text: str) -> str:
    """Một dòng, không có < > (YouTube cấm trong tiêu đề/mô tả)."""
    return " ".join(str(text or "").replace("<", "").replace(">", "").split())


def _truncate_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit < 2:
        return ""
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-–")
    return cut + "…"


def to_hashtag(text: str) -> str:
    """'Biến đổi khí hậu' / '#KhíHậu' -> '#biendoikhihau' / '#khihau' (không dấu, liền)."""
    slug = norm_title(str(text).lstrip("#")).replace(" ", "")
    return "#" + slug if slug else ""


# Số liệu dạng TỶ LỆ / BÌNH QUÂN: tiêu đề bỏ mất đơn vị là đổi nghĩa con số. Ca thật video #6
# (đã đăng 15/11): "Vốn FDI của Việt Nam năm 2025 gấp 5,06 lần Hàn Quốc" — số là FDI tính theo
# % GDP (4,27% so với 0,84%), không phải lượng vốn. (mẫu tìm trong tiêu đề ý tưởng, tên đơn vị)
RATIO_UNITS = [
    (r"so với gdp|%\s*gdp|/\s*gdp|trên gdp|của gdp", "so với GDP"),
    (r"(?:trên|/)\s*100\s*(?:dân|người)", "trên 100 dân"),
    (r"bình quân|đầu người", "bình quân đầu người"),
    (r"tỷ lệ|tỉ lệ", "tỷ lệ"),
]
# Dấu hiệu tiêu đề CÓ nói rõ đó là tỷ lệ/bình quân
RATIO_MARKERS = r"%|so với gdp|/\s*gdp|(?:trên|/)\s*100|bình quân|đầu người|tỷ lệ|tỉ lệ|mỗi người|mỗi 100"


def ratio_unit(idea: dict):
    """Đơn vị tỷ lệ/bình quân của số liệu ý tưởng (theo tiêu đề ý tưởng), hoặc None."""
    low = str(idea.get("title") or "").lower()
    return next((name for rx, name in RATIO_UNITS if re.search(rx, low)), None)


def title_drops_unit(title: str, idea: dict):
    """Tên đơn vị mà tiêu đề video đã bỏ mất (số liệu là tỷ lệ mà tiêu đề đọc như số tổng)."""
    unit = ratio_unit(idea)
    return unit if unit and not re.search(RATIO_MARKERS, str(title or "").lower()) else None


def title_fake_numbers(title: str, script_digits: set) -> list:
    """Những con số trong tiêu đề mà kịch bản không hề có."""
    return sorted(d for d in digit_set(title) if d not in script_digits)


def script_digit_set(scenes: list) -> set:
    """Chỉ lấy số từ LỜI ĐỌC đã qua Kiểm chứng. Cố ý KHÔNG tính tiêu đề/góc của ý
    tưởng thô: chúng chưa được kiểm chứng (vd góc ghi "54.000" trong khi nguồn
    tiếng Hàn viết 54만 = 540.000)."""
    return digit_set(" ".join(str(s.get("voice", "")) for s in scenes))


def finalize(raw: dict, idea: dict, scenes: list, cfg: dict, music_credit: str = None) -> dict:
    """Biến đề xuất thô của LLM thành metadata hợp lệ. Trả về kèm 'warnings'.
    music_credit: tên bài nhạc nền ("New Land — ALBIS") -> một dòng ghi công trong mô tả."""
    pub = cfg.get("publish", {})
    warnings = []

    # --- Tiêu đề
    title = _truncate_words(_clean_line(raw.get("title")), TITLE_MAX)
    if not title:
        warnings.append("LLM không trả tiêu đề")
    fakes = title_fake_numbers(title, script_digit_set(scenes))
    if fakes:
        warnings.append(f"Tiêu đề có số không nằm trong kịch bản: {fakes}")
    unit = title_drops_unit(title, idea)
    if title and unit:
        warnings.append(f"Tiêu đề bỏ mất đơn vị '{unit}': số liệu là tỷ lệ/bình quân, đọc tiêu đề sẽ"
                        f" hiểu thành số tổng — phải nói rõ (vd '{unit}', '% GDP', 'tỷ lệ')")

    # --- Hashtag: cố định của kênh trước, rồi của LLM; bỏ trùng; giới hạn số lượng
    tags_seen, hashtags = set(), []
    for h in list(pub.get("hashtags_fixed", [])) + list(raw.get("hashtags", [])):
        tag = to_hashtag(h)
        if len(tag) > 2 and tag.lower() not in tags_seen:
            tags_seen.add(tag.lower())
            # giữ nguyên kiểu viết của hashtag cố định (vd "#Shorts")
            hashtags.append(h if h in pub.get("hashtags_fixed", []) else tag)
    hashtags = hashtags[: int(pub.get("max_hashtags", 5))]

    # --- Mô tả = tóm tắt + nguồn + khai báo AI + hashtag
    body = str(raw.get("description") or "").replace("<", "").replace(">", "").strip()
    body = re.sub(r"(?m)^\s*#\S+(\s+#\S+)*\s*$", "", body).strip()   # LLM hay tự chèn dòng hashtag
    extras = []
    source_bits = [b for b in (idea.get("source_name"), idea.get("source_url")) if b]
    if source_bits:
        extras.append("Nguồn: " + " — ".join(source_bits))
    else:
        warnings.append("Thiếu nguồn để ghi vào mô tả")
    if music_credit:
        # Ghi công luôn: bài thư viện "không cần ghi công" thì thừa cũng không sao, bài Creative
        # Commons thì BẮT BUỘC — file tải về không mang theo loại giấy phép nên không phân biệt được
        extras.append(f"Nhạc nền: {music_credit} ({cfg.get('music', {}).get('library', 'YouTube Audio Library')})")
    if pub.get("disclosure"):
        extras.append(pub["disclosure"])
    if hashtags:
        extras.append(" ".join(hashtags))
    tail = "\n\n".join(extras)
    # Mô tả quá dài thì cắt phần tóm tắt, KHÔNG cắt nguồn/khai báo/hashtag
    room = max(DESCRIPTION_MAX - len(tail) - 2, 0)
    description = "\n\n".join(x for x in (_truncate_words(body, room) if body else "", tail) if x)

    # --- Thẻ (tags): từ khoá tìm kiếm, có dấu bình thường
    tags, used = [], 0
    for t in raw.get("tags", []):
        t = _clean_line(t).strip(",")
        if not t or t.lower() in (x.lower() for x in tags):
            continue
        if used + len(t) + 3 > TAGS_MAX_CHARS:
            break
        tags.append(t)
        used += len(t) + 3

    return {"title": title, "description": description, "tags": tags,
            "hashtags": hashtags, "warnings": warnings}


def build_metadata(idea: dict, scenes: list, hooks: list, cfg: dict, music_credit: str = None) -> dict:
    """Gọi agent viết metadata; tiêu đề sai số thì trả về viết lại 1 lần,
    vẫn sai thì dùng câu hook đã kiểm chứng làm tiêu đề (an toàn hơn là liều)."""
    from ..crew import write_metadata   # import muộn: cần crewai + API key

    feedback, meta = None, None
    for attempt in range(2):
        meta = finalize(write_metadata(idea, scenes, hooks, cfg, feedback=feedback),
                        idea, scenes, cfg, music_credit)
        bad = [w for w in meta["warnings"] if "Tiêu đề" in w or "tiêu đề" in w]
        if not bad:
            return meta
        log.warning("Metadata bị trả lại (lần %d): %s", attempt + 1, "; ".join(bad))
        feedback = "; ".join(bad)
    fallback = (hooks or [scenes[0].get("voice", "")])[0]
    meta["title"] = _truncate_words(_clean_line(fallback), TITLE_MAX)
    meta["warnings"] = [w for w in meta["warnings"] if "iêu đề" not in w]
    meta["warnings"].append("Tiêu đề LLM viết 2 lần đều bị trả lại — đã dùng câu hook của kịch bản")
    unit = title_drops_unit(meta["title"], idea)
    if unit:          # câu hook cũng không nói rõ đơn vị: không chặn, nhưng Du thấy ngay khi duyệt
        meta["warnings"].append(f"Tiêu đề chưa nói rõ đơn vị '{unit}' — Du sửa tiêu đề trước khi bấm ✅")
    return meta
