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

from . import lang

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
HOOK_MIN_WORDS_KO, HOOK_MAX_WORDS_KO = 4, 12      # tiếng Hàn đếm theo cụm cách nhau bởi dấu cách (어절)

# Số VIẾT BẰNG CHỮ ("bảy mươi ba phần trăm", "năm hai nghìn không trăm mười tám"): lọt qua mọi
# cổng đối chiếu số (code chỉ nhận ra chữ số) — ca thật 12/11 khi thử dàn bài mới. Giọng đọc tự
# đọc chữ số thành lời, nên lời đọc LUÔN phải viết chữ số.
_DIGIT_WORD = r"(?:một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|không|linh|lẻ)"
SPELLED_NUMBER = re.compile(
    rf"\b{_DIGIT_WORD}\s+(?:mươi|trăm|nghìn|ngàn|triệu|tỷ|tỉ|phẩy)\b"          # bảy mươi, hai nghìn, tám phẩy
    rf"|\bmười\s+{_DIGIT_WORD}\b"                                                   # mười ba
    rf"|\b{_DIGIT_WORD}\s+phần\s+trăm\b", re.I)                                     # ba phần trăm
FOREIGN_SCRIPT = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏一-鿿가-힯]")

# ------------------------------------------------ KÊNH TIẾNG HÀN (20/11/2026) — cùng luật, mẫu tiếng Hàn
BANNED_HOOKS_KO = [
    (r"(하지\s*마세요|하지\s*마라|절대\s*하지)", "khuôn “đừng…” (하지 마세요) — câu view theo mẫu"),
    (r"(충격|경악|소름|믿을\s*수\s*없|말도\s*안\s*되|역대급\s*반전|실화)", "từ giật gân — câu view thao túng cảm xúc"),
    (r"^\W*(안녕하세요|오늘은|이번\s*영상|함께\s*알아)", "mở đầu kiểu dẫn chương trình"),
    (r"(알고\s*계셨나요|알고\s*있었나요|아시나요)", "“Bạn có biết…” (알고 계셨나요) — mở đầu nhạt"),
    (r"(99%|모르는\s*사실|아무도\s*모르)", "khuôn “99% không biết” — câu view theo mẫu"),
]
CONTRAST_KO = re.compile(r"(하지만|그런데|불과|겨우|배|앞지|추월|넘어|제쳤|위\b|만에|보다|역전|꼴찌|1위|절반|수준)")
FILLER_KO = re.compile(r"^(데이터에\s*따르면|자료에\s*따르면|통계에\s*따르면|수치를\s*보면|살펴보면|"
                       r"즉|다시\s*말해|구체적으로)\s*,?\s*")
# số viết bằng chữ Hán–Hàn ("칠십삼 퍼센트", "이십 배"): code không đối chiếu được -> phải viết chữ số
SPELLED_NUMBER_KO = re.compile(r"(?<![가-힣])[일이삼사오육칠팔구]?[십백천][일이삼사오육칠팔구십백천]*\s*"
                               r"(?:퍼센트|프로|명|배|년|세|위|달러|시간)")   # "87.5퍼센트" (chữ số + 퍼센트) thì được
# kênh Hàn: lời đọc còn chữ VIỆT có dấu (model lẫn ngôn ngữ) — chữ Latin trần (GDP, OECD) thì được
VIETNAMESE_LETTERS = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


def spelled_numbers(text: str) -> list:
    pat = SPELLED_NUMBER_KO if lang.code() == "ko" else SPELLED_NUMBER
    return [m.group(0) for m in pat.finditer(str(text or ""))]


def foreign_script(text: str) -> bool:
    """Lời đọc còn chữ nước ngoài chưa dịch: kênh Việt — chữ Hàn/Hán/Nhật; kênh Hàn — chữ Việt có dấu
    (giọng đọc sẽ đọc lạ hoặc bỏ qua)."""
    pat = VIETNAMESE_LETTERS if lang.code() == "ko" else FOREIGN_SCRIPT
    return bool(pat.search(str(text or "")))


def _words(text: str) -> list:
    return str(text or "").split()


OPENER_WORDS = 3   # "Việt Nam …" là chuyện thường của kênh: so 2 từ đầu thì chặn oan


# Câu mở đầu ĐỐ người xem (26/11/2026): "Trong 212 nước, Việt Nam đứng thứ mấy về CO2 mỗi người?" — khác "Vì sao…?"
# (video bảng số không trả lời được) ở chỗ đáp án là MỘT CON SỐ có trong bảng, nói ngay câu 2. Người xem ở lại chờ
# đáp án và hay đoán trong bình luận (bình luận ≈ 0 ở mọi video tới 26/11). Đáp án phải tới ngay: hỏi rồi vòng vo
# là câu view.
GUESS_HOOK = re.compile(r"(thứ|hạng|vị trí)\s+(mấy|bao nhiêu)|(gấp|hơn|kém)\s+(mấy|bao nhiêu)\s+lần|"
                        r"bao nhiêu\s+(lần|nước|quốc gia)|đoán (xem|thử)")
GUESS_HOOK_KO = re.compile(r"몇\s*(위|배|등|번째|개국|나라)|얼마나|어디일까|누구일까")
GUESS_ANSWER = {"rank": (r"(thứ|hạng|vị trí)\s+(mấy|bao nhiêu)|bao nhiêu\s+(nước|quốc gia)",
                         r"(thứ|hạng|vị trí)\s+\d|đứng (đầu|cuối|chót|bét)|dẫn đầu|\d+\s*(trên|/)\s*\d+"),
                "ratio": (r"lần", r"\d+(,\d+)?\s*lần|gấp\s+(đôi|ba|rưỡi)")}
GUESS_ANSWER_KO = {"rank": (r"몇\s*(위|등|번째)", r"\d+\s*(위|등|번째)|꼴찌|최하위|1위"),
                   "ratio": (r"몇\s*배|얼마나", r"\d+(\.\d+)?\s*배|\d+(\.\d+)?\s*%")}


def is_guess_hook(text: str) -> bool:
    t = " ".join(str(text or "").lower().split())
    return t.rstrip(" \"'”").endswith("?") and bool((GUESS_HOOK_KO if lang.code() == "ko" else GUESS_HOOK).search(t))


def guess_answer_problem(script: dict) -> str:
    """Câu mở đầu đố người xem thì một trong HAI câu ngay sau phải có đáp án bằng con số. Trả "" nếu đạt."""
    scenes = [sc for sc in script.get("scenes") or [] if isinstance(sc, dict)]
    hook = " ".join(str(scenes[0].get("voice") or "").split()) if scenes else ""
    if not is_guess_hook(hook):
        return ""
    after = " ".join(str(sc.get("voice") or "") for sc in scenes[1:3]).lower()
    low = hook.lower()
    for ask, answer in (GUESS_ANSWER_KO if lang.code() == "ko" else GUESS_ANSWER).values():
        if re.search(ask, low):
            return "" if re.search(answer, after) else (
                f"câu mở đầu đố người xem (“{hook[:70]}”) mà 2 câu ngay sau chưa có đáp án — câu 2 phải trả lời"
                " ngay bằng con số")
    return "" if re.search(r"\d", after) else (
        f"câu mở đầu đố người xem (“{hook[:70]}”) mà 2 câu ngay sau chưa có đáp án — câu 2 phải trả lời ngay"
        " bằng con số")


def opener(text: str) -> str:
    """Ba từ đầu (chữ thường, bỏ dấu câu) — để so cách mở đầu giữa các video."""
    return " ".join(w.strip(".,!?:;\"'“”").lower() for w in _words(text)[:OPENER_WORDS])


def hook_problems(text: str) -> list:
    low = " ".join(str(text or "").lower().split())
    out = [why for pat, why in (BANNED_HOOKS_KO if lang.code() == "ko" else BANNED_HOOKS) if re.search(pat, low)]
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
    ko = lang.code() == "ko"
    lo, hi = (HOOK_MIN_WORDS_KO, HOOK_MAX_WORDS_KO) if ko else (HOOK_MIN_WORDS, HOOK_MAX_WORDS)
    score = 0.0
    score += 2 if re.search(r"\d", text or "") else 0
    score += 1 if (CONTRAST_KO if ko else CONTRAST).search(str(text).lower()) else 0
    score += 1 if lo <= n <= hi else (-1 if n > hi + 4 else 0)
    score -= 2 if opener(text) in set(recent_openers) else 0
    return score


# Câu mở đầu phải nói ĐANG ĐO CÁI GÌ. Ca thật 19/11/2026: video #11 mở bằng "Năm 2018 Việt Nam xếp chót bảng
# nhưng năm 2025 đã vượt qua Mỹ và Anh" — không nói xếp hạng gì (ô tô điện) — 35 lượt xem sau 16 giờ, trong
# khi các video nói rõ chủ đề ngay câu đầu ("Tỷ lệ lao động nông nghiệp…", "Vốn FDI…") được 400-1.235 lượt.
SUBJECT_POINTS = 1.0
_GENERIC = {"tỷ", "lệ", "người", "dân", "số", "năm", "trên", "so", "với", "bình", "quân", "đầu", "mỗi", "trung",
            "và", "của", "trong", "các", "theo", "tổng", "lượng", "mới", "cả", "vào", "làm", "từ", "đến", "nền",
            "kinh", "tế", "chỉ", "việt", "nam", "hàn", "quốc", "thế", "giới", "bản", "đồ", "cuộc", "đua", "bán"}


_GENERIC_KO = {"비율", "인구", "1인당", "대비", "연간", "국가", "세계", "지도", "순위", "경쟁", "한국", "일본", "주요",
               "경제", "수", "및", "의", "등", "전체", "평균"}


def subject_words(text: str) -> set:
    """Từ ĐẶC TRƯNG của chỉ số mà video nói tới, đọc từ tóm tắt ("Chỉ số: X (đơn vị)…") hoặc tiêu đề ý
    tưởng ("Cuộc đua X: …", "Bản đồ thế giới: X năm …", "X: Việt Nam và Hàn Quốc…"). Rỗng = không phải
    ý tưởng bảng số (bài báo)."""
    t = " ".join(str(text or "").split())
    if lang.code() == "ko":                       # "지표: X(단위)", "X 순위 경쟁: …", "세계 지도: 2024년 X — …"
        m = (re.search(r"지표:\s*([^(.]+)", t) or re.match(r"(.+?)\s+순위 경쟁", t)
             or re.match(r"세계 지도:\s*\d{4}년\s+(.+?)(?:\s+—|$)", t) or re.match(r"([^:<>/]{2,80}):\s", t))
        if not m:
            return set()
        return {w for w in re.findall(r"[\w%]+", m.group(1)) if w not in _GENERIC_KO and not w.isdigit()
                and len(w) >= 2}
    m = (re.search(r"Chỉ số:\s*([^(.]+)", t) or re.match(r"Cuộc đua\s+([^:(]+)", t)
         or re.match(r"Bản đồ thế giới:\s*(.+?)\s+năm\s+\d{4}", t)
         or re.match(r"([^:<>/]{4,80}):\s", t))        # "X: Việt Nam và Hàn Quốc…" (không phải HTML / link)
    if not m:
        return set()
    words = {w for w in re.findall(r"\w+", m.group(1).lower()) if not w.isdigit()}
    return {w for w in words if w not in _GENERIC and len(w) >= 2}


def names_subject(text: str, words: set) -> bool:
    """Câu có nhắc tới chỉ số không (ít nhất 2 từ đặc trưng, hoặc đủ cả khi chỉ có 1 từ như "GDP")."""
    if not words:
        return True
    if lang.code() == "ko":                       # trợ từ dính liền danh từ ("출산율은"): so chuỗi con
        t = str(text or "")
        return sum(1 for w in words if w in t) >= min(2, len(words))
    have = set(re.findall(r"\w+", str(text or "").lower()))
    return len(words & have) >= min(2, len(words))


def pick_hook(script: dict, recent_openers=(), is_sourced=lambda text: True, bonus=None, subject=()) -> str:
    """Chọn câu mở đầu mạnh nhất trong các phương án "hooks" và cảnh 1 hiện có; phương án nào
    mạnh hơn hẳn cảnh 1 thì thay vào lời đọc của cảnh 1 (giữ hình của cảnh 1).
    is_sourced(text): câu đúng với nguồn (mọi con số có trong nguồn, câu so sánh khớp bảng số) —
    phương án sai không được chọn. Cảnh 1 hiện có mà sai thì phương án đúng nào cũng thay được nó,
    kể cả điểm thấp hơn (ca thật #46: hook so mốc năm SAI nằm sẵn ở cảnh 1, hai phương án đúng
    không "mạnh hơn hẳn" nên không thay được). Trả về câu mở đầu cuối cùng."""
    scenes = script.get("scenes") or []
    if not scenes:
        return ""
    # bonus(text): điểm cộng tự học từ người xem (src/learning.hook_bonus) — chỉ để phân thắng thua giữa
    # các phương án ĐÚNG; phương án phạm khuôn cấm vẫn -10 điểm. subject: từ đặc trưng của chỉ số — phương
    # án NÓI RÕ đang đo cái gì được cộng một điểm luật (SUBJECT_POINTS)
    score = lambda text: (hook_score(text, recent_openers)
                          + (bonus(text) if bonus and not hook_problems(text) else 0)
                          + (SUBJECT_POINTS if subject and names_subject(text, subject) else 0))
    current = str(scenes[0].get("voice") or "")
    best, best_score = current, (score(current) if is_sourced(current) else float("-inf"))
    for h in script.get("hooks") or []:
        h = " ".join(str(h or "").split())
        if not h or h == current or not is_sourced(h):
            continue
        s = score(h)
        if s > best_score:
            best, best_score = h, s
    if best != current:
        scenes[0]["voice"] = best
    return best


def strip_fillers(script: dict) -> int:
    """Gọt câu đệm ở đầu mỗi câu ("Số liệu cho thấy Việt Nam…" -> "Việt Nam…"). Trả về số câu đã gọt."""
    n = 0
    filler = FILLER_KO if lang.code() == "ko" else FILLER
    for s in script.get("scenes") or []:
        v = str(s.get("voice") or "")
        cut = filler.sub("", v, count=1)
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
        # kênh Hàn: "3배", "5위", "10명 중 4명", "129개국 중 73위"
        if re.match(r"\s*(배|위|번째|등)", after) or re.match(r"\s*(명|대|개국|분의)?\s*중(?![가-힣])", after) \
                or re.search(r"(중|상위|하위)\s*$", before):
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
_YEARS = re.compile(r"\b(?:19|20)\d{2}(?=\b|년)")
DEFINITION_KO = re.compile(r"(이\s*지표는|라는\s*지표|(으)?로\s*계산|(을|를)\s*뜻합니다|(을|를)\s*의미합니다|"
                           r"측정하는\s*지표|나타내는\s*지표)")
BACKTRACK_KO = re.compile(r"^\W*(시간을\s*)?(되돌아|거슬러\s*올라|돌아가\s*보|과거로)")
GENERIC_KO = re.compile(r"(우리\s*삶|일상생활|우리\s*모두|여러분의\s*손|완전히\s*바꾼)")


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
    ko = lang.code() == "ko"
    definition, backtrack, generic = ((DEFINITION_KO, BACKTRACK_KO, GENERIC_KO) if ko
                                      else (DEFINITION, BACKTRACK, GENERIC))
    for k, v in enumerate(voices[1:], 2):
        # câu định nghĩa thật không có con số; "Năm 2025, chỉ số này là 68,6%" là nêu giá trị — được
        if definition.search(v) and not re.search(r"\d", v):
            hard.append(f"cảnh {k} định nghĩa chỉ số (“{v[:60]}”) — định nghĩa để trên chữ của biểu"
                        " đồ, lời đọc 15 giây đầu phải chứng minh hook bằng con số")
        elif backtrack.search(v) and not (set(_YEARS.findall(v)) & hook_years):
            soft.append(f"cảnh {k} lùi về quá khứ ngay đầu video (“{v[:60]}”) — chứng minh hook trước")
        elif generic.search(v):
            soft.append(f"cảnh {k} là câu đệm chung chung (“{v[:60]}”)")
    guess = guess_answer_problem(script)
    if guess:
        hard.append(guess)
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
    bad = re.compile(r"đừng|sai lầm|phủ định mạnh|cấm đoán|sốc|giật mình|chết lặng|khiến bạn|"
                     r"하지\s*마|충격|경악|소름|99%", re.I)
    return [x for x in items or [] if not bad.search(str(x))]
