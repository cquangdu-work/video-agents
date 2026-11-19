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
    is_sourced(text): câu đúng với nguồn (mọi con số có trong nguồn, câu so sánh khớp bảng số) —
    phương án sai không được chọn. Cảnh 1 hiện có mà sai thì phương án đúng nào cũng thay được nó,
    kể cả điểm thấp hơn (ca thật #46: hook so mốc năm SAI nằm sẵn ở cảnh 1, hai phương án đúng
    không "mạnh hơn hẳn" nên không thay được). Trả về câu mở đầu cuối cùng."""
    scenes = script.get("scenes") or []
    if not scenes:
        return ""
    current = str(scenes[0].get("voice") or "")
    best, best_score = current, (hook_score(current, recent_openers) if is_sourced(current)
                                 else float("-inf"))
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


def data_numbers(text: str) -> set:
    """Các GIÁ TRỊ THÔ của bảng số trong một câu (chuỗi chữ số đã bỏ dấu phân cách).

    Không tính (19/11/2026, đo trên bản nháp thật — câu diễn giải từng bị đếm là "câu có số" nên
    kịch bản nào cũng thành chuỗi số dài): mốc năm (đã có luật số mốc năm riêng); số trong phép so
    sánh/xếp hạng ("gấp 5,22 lần", "đứng thứ 56 trên 231", "hạng 9"); cách nói "cứ 3 người thì 2";
    số đếm nhỏ (đến 10) không kèm %."""
    t, out = str(text or ""), set()
    for m in re.finditer(r"\d[\d.,]*\d|\d", t):
        raw = m.group(0)
        before, after = t[max(0, m.start() - 12):m.start()].lower(), t[m.end():m.end() + 8].lower()
        if re.fullmatch(r"(?:19|20)\d{2}", raw):
            continue
        if re.search(r"(gấp|thứ|hạng|vị trí|top|cứ|trên)\s*$", before) or re.match(r"\s*lần\b", after):
            continue
        if raw.isdigit() and int(raw) <= 10 and not after.startswith("%"):
            continue
        out.add(re.sub(r"[.,]", "", raw))
    return out


def has_data_number(text: str) -> bool:
    return bool(data_numbers(text))


def longest_number_run(script: dict) -> int:
    """Số câu nêu con số MỚI đứng liền nhau dài nhất — đọc số mới liên tiếp mới là đọc bảng. Câu
    nhắc lại con số đã nói để diễn giải ("Mức 68,6% tức là cứ 3 phụ nữ thì 2 người") không tính."""
    best = run = 0
    seen = set()
    for s in script.get("scenes") or []:
        nums = data_numbers(str(s.get("voice") or ""))
        run = run + 1 if nums - seen else 0
        seen |= nums
        best = max(best, run)
    return best


# ------------------------------------------- 15 giây đầu + câu kết (19/11/2026, từ số liệu thật)
# YouTube Analytics của video #6 (FDI) và #7 (thuê bao): người xem bỏ đi nhiều nhất trong 15 giây
# đầu, đúng ở câu định nghĩa ("Chỉ số này đo lường tỷ lệ vốn đầu tư…"), câu đệm ("Chiếc điện thoại
# trong tay bạn là một phần của hạ tầng viễn thông khổng lồ") và câu lùi về năm đầu bảng ("Nhìn lại
# năm 1960, cả hai nước đều có 0 thuê bao"). Còn ở giây ~18: 60% (#6), 38% (#7).
OPENING_SCENES = 5            # cảnh 1-5 ≈ 15 giây đầu
DEFINITION = re.compile(r"\b(chỉ số (này |đó )?(đo|là|phản ánh|cho biết|thể hiện)|được tính (bằng|theo)|"
                        r"được định nghĩa|là thước đo)\b", re.I)
BACKTRACK = re.compile(r"^\W*(hãy\s+)?(cùng\s+)?(nhìn lại|quay (ngược|lại|về)|trở lại|lùi về|ngược dòng)\b",
                       re.I)
GENERIC = re.compile(r"\b(trong tay bạn|cuộc sống (hằng|hàng) ngày|thay đổi hoàn toàn cách|"
                     r"mỗi ngày chúng ta|ai trong chúng ta cũng)\b", re.I)
_YEARS = re.compile(r"\b(?:19|20)\d{2}\b")


def opening_problems(script: dict) -> tuple:
    """Lỗi nhịp ở 15 giây đầu (cảnh 2-5; cảnh 1 là hook, có luật riêng) -> (lỗi chặn, lỗi nhắc).

    Chặn: câu định nghĩa chỉ số; hai câu liền nhau không có con số. Nhắc (đưa vào lời trả về viết
    lại nhưng không giữ kịch bản ở nháp): câu đệm chung chung, câu lùi về quá khứ mà năm đó không
    có trong hook (lùi về đúng năm hook nhắc là đang chứng minh hook — được)."""
    scenes = [s for s in script.get("scenes") or [] if isinstance(s, dict)]
    voices = [" ".join(str(s.get("voice") or "").split()) for s in scenes[:OPENING_SCENES]]
    if len(voices) < 3:
        return [], []
    hook_years = set(_YEARS.findall(voices[0]))
    hard, soft = [], []
    for k, v in enumerate(voices[1:], 2):
        # câu định nghĩa thật không có con số; "Năm 2025, chỉ số này là 68,6%" là nêu giá trị — được
        if DEFINITION.search(v) and not re.search(r"\d", v):
            hard.append(f"cảnh {k} định nghĩa chỉ số (“{v[:60]}”) — định nghĩa để trên chữ của biểu"
                        " đồ, lời đọc 15 giây đầu phải chứng minh hook bằng con số")
        elif BACKTRACK.search(v) and not (set(_YEARS.findall(v)) & hook_years):
            soft.append(f"cảnh {k} lùi về quá khứ ngay đầu video (“{v[:60]}”) — chứng minh hook trước")
        elif GENERIC.search(v):
            soft.append(f"cảnh {k} là câu đệm chung chung (“{v[:60]}”)")
    empty = [not re.search(r"\d", v) for v in voices[1:]]
    if any(a and b for a, b in zip(empty, empty[1:])):
        hard.append("15 giây đầu (cảnh 2-5) có hai câu liền nhau không có con số — người xem bỏ đi"
                    " đúng ở chỗ như vậy (video #7)")
    return hard, soft


def _syllable_pairs(text: str) -> set:
    w = [x.strip(".,!?:;\"'“”()").lower() for x in str(text or "").split()]
    w = [x for x in w if x]
    return {f"{a} {b}" for a, b in zip(w, w[1:])}


def ending_problem(script: dict) -> str:
    """Câu kết phải quay lại câu mở đầu (nhắc lại con số của hook, hoặc ít nhất hai cụm từ của nó)
    để video lặp vòng tự nhiên — Shorts tính cả lượt xem lặp. Trả "" nếu đạt."""
    from .utils import digit_set
    scenes = [s for s in script.get("scenes") or [] if isinstance(s, dict)]
    if len(scenes) < 4:
        return ""
    hook, last = str(scenes[0].get("voice") or ""), str(scenes[-1].get("voice") or "")
    hd = digit_set(hook)
    if hd and hd & digit_set(last):
        return ""
    if not hd and len(_syllable_pairs(hook) & _syllable_pairs(last)) >= 2:
        return ""
    return ("câu kết không quay lại câu mở đầu — nhắc lại con số (hoặc đối tượng) của hook với góc nhìn"
            " mới để người xem muốn xem lại từ đầu")


def safe_patterns(items) -> list:
    """Bỏ khỏi "công thức đối thủ" những khuôn/luật câu view mà kênh không được dùng."""
    bad = re.compile(r"đừng|sai lầm|phủ định mạnh|cấm đoán|sốc|giật mình|chết lặng|khiến bạn", re.I)
    return [x for x in items or [] if not bad.search(str(x))]
