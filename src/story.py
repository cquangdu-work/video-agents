"""Luật kể chuyện cho kịch bản — code thuần, không gọi LLM, để test được và để model nhỏ không
"lách" được.

Vì sao có file này (đo trên 18 kịch bản thật trên VM, 12/11/2026):
- 11/18 câu mở đầu chép khuôn "Đừng … nữa!" / "Sai lầm …" của file công thức đối thủ. Video nào
  cũng mở giống nhau = "nội dung theo mẫu, lặp lại" (loại 1 không được kiếm tiền), và câu kiểu
  "Sai lầm 99% người…" là câu view thao túng (loại 2) — còn bịa luôn con số 99%.
- Dàn bài cũ bảo "mỗi con số một cảnh" -> kịch bản đọc số liên tiếp như đọc bảng (#16: 21 câu
  có số liền nhau), chen câu đệm kiểu báo cáo "Số liệu cho thấy…", "Điều này có nghĩa là…".
- Thiết kế ghi "viết 3 câu mở đầu để chọn cái mạnh nhất" nhưng chưa có ai chọn.

Các hàm:
    hook_problems(text)        câu mở đầu phạm khuôn cấm nào
    hook_score(text, ...)      điểm của một câu mở đầu (cao hơn = mạnh hơn)
    pick_hook(script, ...)     chọn câu mở đầu mạnh nhất trong 3 phương án + cảnh 1, đặt vào cảnh 1
    strip_fillers(script)      gọt câu đệm kiểu báo cáo ở đầu câu
    longest_number_run(script) số câu có số đứng liền nhau dài nhất
    safe_patterns(items)       lọc khuôn câu view ra khỏi "công thức đối thủ"
"""
import re

# (mẫu, lý do) — so trên chữ thường. Câu mở đầu phạm một mẫu là hỏng.
BANNED_HOOKS = [
    (r"^\W*đừng\b", "khuôn “Đừng … nữa!” — câu view theo mẫu"),
    (r"^\W*sai lầm\b", "khuôn “Sai lầm …” — câu view theo mẫu"),
    (r"\bbạn có biết\b", "“Bạn có biết…” — mở đầu nhạt, chưa nói được gì"),
    (r"^\W*(hôm nay|xin chào|chào (các )?bạn|trong video này|cùng (mình|tìm hiểu|khám phá)|hãy cùng)\b",
     "mở đầu kiểu dẫn chương trình"),
    (r"\b(giật mình|sốc|kinh hoàng|không thể tin|choáng váng|rùng mình|sự thật (sẽ|khiến|đằng sau))\b",
     "từ giật gân — câu view thao túng cảm xúc"),
    # "…đạt bao nhiêu tuổi?" hỏi một con số trần; "cần bao nhiêu năm để bằng Hàn Quốc?" thì vẫn được
    (r"\b(đạt|là|có)\s+bao nhiêu\b[^.!?]{0,15}\?\s*$", "câu hỏi chung chung, chưa hé lộ điều gì bất ngờ"),
]

# Dấu hiệu của một so sánh/đối lập cụ thể — thứ làm người xem dừng lại
CONTRAST = re.compile(r"\b(nhưng|chỉ|mới bằng|bằng .{1,30} năm|gấp|vượt|hơn cả|thấp thứ|cao thứ|đứng thứ|"
                      r"chưa bằng|từ .{1,25} lên|tụt|bỏ xa|ngang|đúng chính giữa|nhiều hơn|ít hơn)\b")

# Câu đệm kiểu báo cáo ở ĐẦU câu: bỏ đi thì câu vẫn trọn ý mà nghe tự nhiên hơn
FILLER = re.compile(r"^(số liệu (cho thấy|chỉ ra)|tính toán cho thấy|theo số liệu( mới nhất)?|"
                    r"điều này có nghĩa là|điều đó có nghĩa là|cụ thể( là)?|nhìn rộng ra( thế giới)?|"
                    r"đáng chú ý( là)?|có thể thấy( rằng)?|thống kê cho thấy)\s*,?\s*", re.I)

HOOK_MIN_WORDS, HOOK_MAX_WORDS = 6, 16

# Số VIẾT BẰNG CHỮ ("bảy mươi ba phần trăm", "năm hai nghìn không trăm mười tám"): lọt qua mọi
# cổng đối chiếu số (code chỉ nhận ra chữ số) — ca thật 12/11 khi thử dàn bài mới. Giọng đọc tự
# đọc chữ số thành lời, nên lời đọc LUÔN phải viết chữ số.
_DIGIT_WORD = r"(?:một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|không|linh|lẻ)"
SPELLED_NUMBER = re.compile(
    rf"\b{_DIGIT_WORD}\s+(?:mươi|trăm|nghìn|ngàn|triệu|tỷ|tỉ|phẩy)\b"          # bảy mươi, hai nghìn, tám phẩy
    rf"|\bmười\s+{_DIGIT_WORD}\b"                                                   # mười ba
    rf"|\b{_DIGIT_WORD}\s+phần\s+trăm\b", re.I)                                     # ba phần trăm
FOREIGN_SCRIPT = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏一-鿿가-힯]")


def spelled_numbers(text: str) -> list:
    return [m.group(0) for m in SPELLED_NUMBER.finditer(str(text or ""))]


def foreign_script(text: str) -> bool:
    """Lời đọc còn chữ Hàn/Hán/Nhật chưa dịch (giọng đọc tiếng Việt sẽ đọc lạ hoặc bỏ qua)."""
    return bool(FOREIGN_SCRIPT.search(str(text or "")))


def _words(text: str) -> list:
    return str(text or "").split()


OPENER_WORDS = 3   # "Việt Nam …" là chuyện thường của kênh: so 2 từ đầu thì chặn oan


def opener(text: str) -> str:
    """Ba từ đầu (chữ thường, bỏ dấu câu) — để so cách mở đầu giữa các video."""
    return " ".join(w.strip(".,!?:;\"'“”").lower() for w in _words(text)[:OPENER_WORDS])


def hook_problems(text: str) -> list:
    low = " ".join(str(text or "").lower().split())
    out = [why for pat, why in BANNED_HOOKS if re.search(pat, low)]
    if spelled_numbers(text):
        out.append("số viết bằng chữ — phải viết chữ số để máy đối chiếu nguồn")
    if foreign_script(text):
        out.append("còn chữ nước ngoài chưa dịch")
    return out


def hook_score(text: str, recent_openers=()) -> float:
    """Câu mở đầu mạnh = có con số cụ thể + có đối lập/so sánh + gọn. Phạm khuôn cấm thì
    điểm rất thấp; mở đầu giống video gần đây thì trừ điểm (chống "theo mẫu")."""
    if hook_problems(text):
        return -10.0
    n = len(_words(text))
    score = 0.0
    score += 2 if re.search(r"\d", text or "") else 0
    score += 1 if CONTRAST.search(str(text).lower()) else 0
    score += 1 if HOOK_MIN_WORDS <= n <= HOOK_MAX_WORDS else (-1 if n > HOOK_MAX_WORDS + 4 else 0)
    score -= 2 if opener(text) in set(recent_openers) else 0
    return score


def pick_hook(script: dict, recent_openers=(), is_sourced=lambda text: True) -> str:
    """Chọn câu mở đầu mạnh nhất trong các phương án "hooks" và cảnh 1 hiện có; phương án nào
    mạnh hơn hẳn cảnh 1 thì thay vào lời đọc của cảnh 1 (giữ hình của cảnh 1).
    is_sourced(text): mọi con số trong câu đều có trong nguồn — phương án bịa số không được chọn.
    Trả về câu mở đầu cuối cùng."""
    scenes = script.get("scenes") or []
    if not scenes:
        return ""
    current = str(scenes[0].get("voice") or "")
    best, best_score = current, hook_score(current, recent_openers)
    for h in script.get("hooks") or []:
        h = " ".join(str(h or "").split())
        if not h or h == current or not is_sourced(h):
            continue
        s = hook_score(h, recent_openers)
        if s > best_score:
            best, best_score = h, s
    if best != current:
        scenes[0]["voice"] = best
    return best


def strip_fillers(script: dict) -> int:
    """Gọt câu đệm ở đầu mỗi câu ("Số liệu cho thấy Việt Nam…" -> "Việt Nam…"). Trả về số câu đã gọt."""
    n = 0
    for s in script.get("scenes") or []:
        v = str(s.get("voice") or "")
        cut = FILLER.sub("", v, count=1)
        if cut != v and len(cut.split()) >= 4:          # gọt xong còn quá ngắn thì giữ nguyên
            s["voice"] = cut[:1].upper() + cut[1:]
            n += 1
    return n


def longest_number_run(script: dict) -> int:
    """Số câu có chứa con số đứng liền nhau dài nhất (đọc số liên tiếp = đọc bảng)."""
    best = run = 0
    for s in script.get("scenes") or []:
        run = run + 1 if re.search(r"\d", str(s.get("voice") or "")) else 0
        best = max(best, run)
    return best


def safe_patterns(items) -> list:
    """Bỏ khỏi "công thức đối thủ" những khuôn/luật câu view mà kênh không được dùng."""
    bad = re.compile(r"đừng|sai lầm|phủ định mạnh|cấm đoán|sốc|giật mình|chết lặng|khiến bạn", re.I)
    return [x for x in items or [] if not bad.search(str(x))]
