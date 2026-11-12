"""Các agent dùng LLM, điều phối bằng CrewAI (chạy tuần tự).

Luồng: Săn ý tưởng -> Biên tập -> Biên kịch -> Kiểm chứng.
Mỗi bước nhận đầu ra JSON của bước trước. Import crewai để trong hàm
để chế độ --dry-run không cần cài thư viện nặng này.

LLM lấy từ biến môi trường MODEL (chuẩn litellm, ví dụ gemini/gemini-2.5-flash).
"""
import json
import logging
import os
import re

from .utils import extract_json

log = logging.getLogger(__name__)


def _model_chain() -> list:
    """Model chính + các model dự phòng (free tier Gemini hay quá tải 503)."""
    chain = [os.getenv("MODEL", "gemini/gemini-3.5-flash-lite")]
    chain += [m.strip() for m in os.getenv("MODEL_FALLBACKS", "").split(",") if m.strip()]
    return chain


def _is_transient(exc: Exception) -> bool:
    s = str(exc)
    return any(k in s for k in ("503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED"))


def _run_single_task(role: str, goal: str, description: str, expected_output: str) -> str:
    """Tạo một crew 1-agent-1-task rồi chạy. Đơn giản, dễ debug từng bước.

    Quá tải (503/429) thì chờ rồi thử lại, hết kiên nhẫn thì đổi model dự phòng.
    """
    import time

    from crewai import LLM, Agent, Crew, Task

    last_exc = None
    for model in _model_chain():
        for attempt in range(3):
            try:
                agent = Agent(role=role, goal=goal, backstory="",
                              llm=LLM(model=model, temperature=0.7), verbose=False)
                task = Task(description=description, expected_output=expected_output, agent=agent)
                return str(Crew(agents=[agent], tasks=[task], verbose=False).kickoff())
            except Exception as exc:
                if not _is_transient(exc):
                    raise
                last_exc = exc
                wait = 20 * (attempt + 1)
                log.warning("%s quá tải (lần %d) — chờ %ds rồi thử lại", model, attempt + 1, wait)
                time.sleep(wait)
        log.warning("Bỏ %s, chuyển model dự phòng tiếp theo", model)
    raise RuntimeError(f"Mọi model đều quá tải: {last_exc}")


# ---------------------------------------------------------------- Săn ý tưởng
def hunt_ideas(raw_items: list, cfg: dict) -> list:
    """Nhận ~30-60 ý tưởng thô, trả về các ứng viên có 'góc' rõ ràng."""
    from .utils import digit_set

    def numbers_in(i: dict) -> int:     # đếm con số có sẵn trong tiêu đề + tóm tắt
        return len(digit_set(f"{i['title']} {i['summary']}"))

    listing = "\n".join(
        f"- [{i['id']}] ({i['source_name']}, {i['lang']}, {numbers_in(i)} con số)"
        f" {i['title']} — {i['summary'][:150]}"
        for i in raw_items
    )
    out = _run_single_task(
        role="Thợ săn ý tưởng video khoa học dữ liệu",
        goal="Chọn ý tưởng độc đáo, tránh nội dung đại trà",
        description=f"""Kênh: {cfg['channel']['name']} — {cfg['channel']['description']}

Luật về "góc" (bắt buộc): {cfg['angle_rules']}

Danh sách ý tưởng thô hôm nay:
{listing}

Chọn tối đa {cfg['daily']['shortlist'] * 3} ý tưởng CÓ GÓC rõ nhất và minh họa được
bằng biểu đồ/bản đồ/số liệu. Với mỗi ý tưởng, viết góc cụ thể bằng tiếng Việt.
KÊNH DỰNG HÌNH BẰNG SỐ LIỆU: ưu tiên rõ rệt ý tưởng mà nguồn đã có sẵn nhiều con số cụ
thể (số lượng, tỷ lệ, số tiền, mốc năm — xem "N con số" ghi ở mỗi dòng). Ý tưởng thuần
quan điểm, định tính, không đo đếm được gì thì LOẠI dù nghe hay.
CẨN THẬN ĐƠN VỊ khi nhắc số liệu từ nguồn tiếng Hàn/Anh: 만 = 10.000 (54만 = 540.000),
억 = 100 triệu; million = triệu, billion = tỷ. Không chắc thì đừng ghi con số vào góc.""",
        expected_output="""JSON array, mỗi phần tử:
{"id": <id gốc>, "angle": "<góc cụ thể, 1-2 câu tiếng Việt>",
 "keyword": "<3-6 từ TIẾNG VIỆT nói đúng đề tài, như người Việt gõ tìm trên YouTube,
             ví dụ 'tỷ suất sinh Hàn Quốc' — dùng để kiểm tra đã có ai làm chưa>",
 "reason": "<vì sao chọn>"}""",
    )
    try:
        picked = extract_json(out)
    except ValueError:
        picked = []
    # Model dự phòng hay trả sai khuôn: chỉ giữ phần tử đúng dạng, có id và góc
    return [c for c in (picked if isinstance(picked, list) else [])
            if isinstance(c, dict) and "id" in c and c.get("angle")]


# ------------------------------------------------------------------ Biên tập
def score_ideas(candidates: list, cfg: dict) -> list:
    """Chấm điểm 1-5 theo 5 tiêu chí, trả về kèm tổng điểm có trọng số."""
    w = cfg["scoring_weights"]
    listing = "\n".join(
        f"- [{c['id']}] {c['title']}\n  Góc: {c['angle']}" for c in candidates
    )
    out = _run_single_task(
        role="Biên tập viên kênh video dữ liệu",
        goal="Chấm điểm khách quan, giữ cân bằng chủ đề",
        description=f"""Chấm từng ý tưởng theo 5 tiêu chí, mỗi tiêu chí 1-5 điểm:
curiosity (độ tò mò), novelty (độ mới), verifiability (kiểm chứng được),
accessibility (ai cũng hiểu), visualizability (dễ minh họa bằng biểu đồ/bản đồ).

Danh sách:
{listing}""",
        expected_output="""JSON array: [{"id": <id>, "curiosity": n, "novelty": n,
"verifiability": n, "accessibility": n, "visualizability": n}]""",
    )
    scored = extract_json(out)
    for s in scored:
        s["total"] = round(sum(
            s[k] * w[k] for k in
            ("curiosity", "novelty", "verifiability", "accessibility", "visualizability")
        ), 1)
    return sorted(scored, key=lambda s: -s["total"])


def _formula_block() -> str:
    """Kiến thức nền cho Biên kịch: công thức rút từ đối thủ (config/formula.yaml)
    + bài học từ số liệu thật của chính kênh (data/learned.yaml, agent Phân tích ghi)."""
    from .analysis.formula import load_formula
    from .analysis.learned import load_learned
    block = ""
    f = load_formula()
    if f:
        block += f"""
CÔNG THỨC rút từ video ăn khách của các kênh cùng mảng (áp dụng linh hoạt, không máy móc):
- Khuôn tiêu đề/hook hay thắng: {'; '.join(f.get('title_patterns', []))}
- Luật viết hook: {'; '.join(f.get('hook_rules', []))}
- Độ dài hay thắng: {f.get('length_seconds', {})}
"""
    insights = load_learned().get("insights") or []
    if insights:
        block += ("\nBÀI HỌC TỪ SỐ LIỆU THẬT CỦA CHÍNH KÊNH NÀY (ưu tiên hơn công thức đối thủ):\n"
                  + "\n".join(f"- {i}" for i in insights) + "\n")
    return block


# ------------------------------------------------------------------ Biên kịch
# Khoảng chấp nhận: video đổi cảnh 2-4s -> 60-90s cần cỡ 15-24 cảnh.
SCRIPT_MIN_SCENES, SCRIPT_MAX_SCENES = 12, 28
WORDS_PER_SECOND = 3.4   # ĐO THẬT 11/2026 trên 3 video (giọng Gemini, tiếng Việt, tính cả
                         # nghỉ giữa câu): 3,2-3,5 từ/giây. Số cũ 2,7 làm video hụt ~20%.


def words_per_second(cfg: dict) -> float:
    return float(cfg.get("pacing", {}).get("words_per_second", WORDS_PER_SECOND))


def word_budget(cfg: dict) -> tuple:
    """(ít nhất, nhiều nhất) số từ lời đọc để video dài đúng video_seconds_min..max."""
    ch, wps = cfg["channel"], words_per_second(cfg)
    return int(ch["video_seconds_min"] * wps), int(ch["video_seconds_max"] * wps)


SCRIPT_MIN_NUMBERS = 4   # kênh "Thế giới qua con số" — lời đọc ít số là hỏng từ gốc


def _script_stats(script: dict) -> tuple:
    from .utils import digit_set
    scenes = script.get("scenes", [])
    voice_all = " ".join(str(s.get("voice", "")) for s in scenes)
    words = sum(len(str(s.get("voice", "")).split()) for s in scenes)
    return len(scenes), words, len(digit_set(voice_all))


def clean_spoken(text) -> str:
    """Lời ĐỌC không được chứa thứ chỉ dành cho tiêu đề: hashtag, emoji, đuôi "| Tên kênh".
    Biên kịch hay lẫn câu mở đầu với tiêu đề YouTube ("...môi trường! #Shorts") và giọng
    đọc sẽ đọc cả "#Shorts" thành tiếng."""
    text = str(text or "")
    text = re.sub(r"\s*\|[^|]*$", "", text)                                  # "... | Thế giới qua con số"
    text = re.sub(r"#\w+", "", text)                                         # #Shorts
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", text)   # emoji
    return " ".join(text.split())


def unsourced_numbers(script: dict, idea: dict, source_text: str) -> list:
    """Những con số trong lời đọc KHÔNG tìm thấy trong bài nguồn (kể cả tiêu đề, tóm tắt).

    Agent Kiểm chứng chỉ soát danh sách "claims" do chính Biên kịch khai, nên con số bịa
    đặt ở chỗ khác lọt lưới. Ca thật 12/11/2026: câu mở đầu "Sai lầm 99% người ăn chay
    mắc phải..." — 11 con số còn lại đều có trong nguồn, riêng 99% là tự chế để câu view.
    Ở đây code tự đối chiếu, không nhờ LLM:
    - so theo chuỗi chữ số, bỏ dấu chấm/phẩy ("2.549,55" khớp "2,549.55");
    - bỏ qua số 0 ở đuôi để chịu được quy đổi đơn vị ("540.000" khớp "54만", "5 triệu");
    - số đếm thông thường từ 0 đến 10 (không kèm %) được miễn ("3 lý do", "2 nhóm").
    """
    from .utils import digit_set
    have = digit_set(f"{source_text} {idea.get('title', '')} {idea.get('summary', '')}")
    loose = {h.rstrip("0") for h in have}
    voice = " ".join(str(s.get("voice", "")) for s in script.get("scenes", []))
    out = []
    for m in re.finditer(r"\d[\d.,]*\d|\d", voice):
        raw = m.group(0)
        percent = voice[m.end():m.end() + 1] == "%"
        norm = re.sub(r"[.,]", "", raw)
        if not percent and raw.isdigit() and int(raw) <= 10:
            continue
        if norm in have or (norm.rstrip("0") and norm.rstrip("0") in loose):
            continue
        shown = raw + ("%" if percent else "")
        if shown not in out:
            out.append(shown)
    return out


def as_script(obj) -> dict:
    """Đưa câu trả lời của LLM về đúng dạng {"hooks": [...], "scenes": [...], "claims": [...]}.

    Model dự phòng (lúc model chính quá tải) hay trả sai khuôn: mảng cảnh trần, hoặc
    object bọc trong mảng. Ca thật 12/11/2026: trả mảng -> script.get() nổ, sập cả khâu
    ý tưởng. Không cứu được thì trả kịch bản rỗng — nó sẽ bị tính là hụt chuẩn và viết lại.
    """
    if isinstance(obj, list):
        if len(obj) == 1 and isinstance(obj[0], dict) and "scenes" in obj[0]:
            obj = obj[0]
        elif obj and all(isinstance(s, dict) and "voice" in s for s in obj):
            obj = {"scenes": obj}
    if not isinstance(obj, dict):
        obj = {}
    scenes = obj.get("scenes")
    obj["scenes"] = [s for s in scenes if isinstance(s, dict)] if isinstance(scenes, list) else []
    for key in ("hooks", "claims"):
        if not isinstance(obj.get(key), list):
            obj[key] = []
    for s in obj["scenes"]:                     # lời đọc sạch hashtag/emoji trước khi tới TTS
        s["voice"] = clean_spoken(s.get("voice"))
    obj["hooks"] = [clean_spoken(h) for h in obj["hooks"]]
    return obj


MAX_SPOKEN_YEARS = 5     # lời đọc nhắc quá nhiều mốc năm = đang đọc bảng số, không kể chuyện

DATA_STORY = """
ĐÂY LÀ Ý TƯỞNG TỪ BẢNG SỐ LIỆU (không phải bài báo) — phần này ƯU TIÊN hơn dàn bài chung:
- Video sẽ có biểu đồ (đường, hoặc cuộc đua xếp hạng nhiều nước) vẽ TOÀN BỘ chuỗi năm. Vì vậy
  lời đọc KHÔNG đọc lần lượt từng mốc năm ("năm 1995 là..., năm 2000 là...") — người xem sẽ
  lướt đi ngay.
- Kể thành CÂU CHUYỆN: hook là điều bất ngờ nhất trong bảng (ví dụ "Việt Nam hôm nay mới bằng
  Hàn Quốc năm X", "tăng gấp N lần", "từ bét bảng lên hạng 7"); rồi điểm xuất phát, hiện tại,
  khoảng cách. Bảng có XẾP HẠNG nhiều nước thì kể ai vượt ai, Việt Nam và Hàn Quốc đứng thứ
  mấy lúc đầu và bây giờ (các dòng "hạng ... vượt ..." đã tính sẵn trong bảng).
- Chỉ dùng 5-8 con số đắt nhất, tối đa 4 mốc năm khác nhau trong toàn bài.
- Giữa các con số là phần giải thích Ý NGHĨA (chênh lệch đó nói gì về đời sống, kinh tế) —
  phần giải thích KHÔNG được thêm con số nào ngoài bảng, không khuyên người xem làm gì.
- Đây là số liệu thống kê đã ghi nhận, KHÔNG gọi là "dự báo"."""


def spoken_years(script: dict) -> set:
    """Các mốc năm (1900-2099) được nhắc trong lời đọc."""
    voice = " ".join(str(s.get("voice", "")) for s in script.get("scenes", []))
    return set(re.findall(r"\b(?:19|20)\d{2}\b", voice))


def script_problems(script: dict, cfg: dict) -> list:
    """Kịch bản hụt chuẩn ở đâu -> danh sách lý do (rỗng = đạt). Dùng chung cho vòng
    viết lại của Biên kịch và cho main (kịch bản còn lỗi thì KHÔNG được đem đi dựng)."""
    lo_words, hi_words = word_budget(cfg)
    n, words, numbers = _script_stats(script)
    problems = []
    if not SCRIPT_MIN_SCENES <= n <= SCRIPT_MAX_SCENES:
        problems.append(f"{n} cảnh (cần {SCRIPT_MIN_SCENES}-{SCRIPT_MAX_SCENES})")
    # Cho lệch một chút quanh ngân sách từ: hụt 10% hay dư 5% vẫn ra video đúng cỡ
    if not 0.9 * lo_words <= words <= 1.05 * hi_words:
        problems.append(f"{words} từ (cần {lo_words}-{hi_words})")
    if numbers < SCRIPT_MIN_NUMBERS:
        problems.append(f"chỉ {numbers} con số trong lời đọc (cần ít nhất {SCRIPT_MIN_NUMBERS})")
    years = spoken_years(script)
    if len(years) > MAX_SPOKEN_YEARS:
        # Ca thật 12/11: kịch bản điện tiêu thụ đọc 9 mốc năm x 2 nước như đọc bảng
        problems.append(f"đọc lần lượt {len(years)} mốc năm như đọc bảng số — biểu đồ đã vẽ cả"
                        f" chuỗi năm, lời đọc chỉ giữ tối đa {MAX_SPOKEN_YEARS - 1} mốc đắt nhất")
    return problems


def write_script(idea: dict, cfg: dict, feedback: str = None, source_text: str = "") -> dict:
    """Viết kịch bản 60-90 giây + 3 phương án câu mở đầu.

    Tự kiểm số cảnh/số từ/số con số; hụt chuẩn thì trả lại cho LLM viết lại, cuối cùng
    giữ bản ÍT LỖI NHẤT (bản viết lại có khi còn tệ hơn bản đầu).
    feedback: lỗi từ agent Kiểm chứng (luồng "sai thì trả về Biên kịch").
    source_text: toàn văn bài nguồn. Trước đây Biên kịch chỉ thấy đoạn tóm tắt RSS
    vài dòng nên không có số mà dùng — kịch bản ra 1-2 con số, toàn câu chữ.
    """
    ch = cfg["channel"]
    lo_words, hi_words = word_budget(cfg)
    from .sources.worldbank import SOURCE_NAME as DATA_SOURCE
    data_story = DATA_STORY if idea.get("source_name") == DATA_SOURCE else ""
    excerpt = (source_text or "").strip()[:5000]
    source_block = (f"\nTRÍCH BÀI NGUỒN (mọi con số trong kịch bản phải lấy từ đây hoặc từ tóm tắt"
                    f" bên trên, tuyệt đối không tự nghĩ ra):\n\"\"\"\n{excerpt}\n\"\"\"\n"
                    if excerpt else "")
    base_description = f"""Viết kịch bản video dọc {ch['video_seconds_min']}-{ch['video_seconds_max']} giây
cho kênh "{ch['name']}". Tốc độ đọc ~{words_per_second(cfg) * 60:.0f} từ/phút -> TỔNG LỜI ĐỌC PHẢI ĐẠT {lo_words}-{hi_words} từ.

Ý tưởng: {idea['title']}
Góc: {idea['angle']}
Nguồn gốc: {idea['source_url']}
Tóm tắt nguồn: {idea.get('summary', '')}
{source_block}
Luật chính sách (bắt buộc tuân thủ): {cfg['policy_rules']}
{_formula_block()}

Yêu cầu CỨNG về cấu trúc (video đổi cảnh mỗi 2-4 giây):
- Chia thành 16-26 CẢNH. Mỗi cảnh đúng 1 câu lời đọc NGẮN (8-15 từ).
- Cảnh 1 chính là hook. Dàn bài: hook (1 cảnh) -> mở vấn đề (2-3 cảnh)
  -> số liệu chính, mỗi con số một cảnh (8-14 cảnh) -> ngã rẽ/so sánh bất ngờ
  (2-3 cảnh) -> câu kết đọng lại (1-2 cảnh).
- Mỗi cảnh kèm mô tả hình (biểu đồ gì, dữ liệu gì) + nguồn dữ liệu của cảnh đó.
- GIÀU SỐ LIỆU: lời đọc toàn video phải chứa ÍT NHẤT 6 con số cụ thể lấy từ nguồn
  (kênh tên là "{ch['name']}" — thiếu số là hỏng). LUÔN viết số bằng CHỮ SỐ
  ("8.030", "38%", "15 tỷ"), không viết bằng chữ ("tám nghìn").
- CẨN THẬN ĐƠN VỊ khi nguồn là tiếng Hàn/Anh: 만 = 10.000 (54만 = 540.000),
  억 = 100 triệu; million = triệu, billion = tỷ. Quy đổi sai một bậc là tai nạn.
- Viết 3 PHƯƠNG ÁN hook khác nhau, mỗi câu <= 15 từ. Hook là câu ĐỌC THÀNH TIẾNG, không
  phải tiêu đề: không hashtag, không emoji, không kèm tên kênh.
- TUYỆT ĐỐI không tự chế con số để giật gân ("99% người...", "9 trên 10 người...") — hook
  cũng chỉ được dùng con số có trong bài nguồn. Máy sẽ đối chiếu TỪNG con số với nguồn.
- Kết không kêu gọi hành động sáo rỗng.
- Mọi con số trong lời đọc phải ghi rõ lấy từ nguồn nào.""" + data_story
    if feedback:
        base_description += f"""

AGENT KIỂM CHỨNG ĐÃ PHÁT HIỆN LỖI SỐ LIỆU Ở BẢN TRƯỚC — phải sửa đúng theo nguồn:
{feedback}"""
    expected = """JSON object:
{"hooks": ["...", "...", "..."],
 "scenes": [{"voice": "<1 câu lời đọc>", "visual": "<mô tả hình/biểu đồ>", "data_source": "<nguồn>"}],
 "claims": [{"claim": "<khẳng định có số liệu>", "source": "<nguồn/link>"}]}"""

    description, best, best_problems = base_description, None, None
    tries = 2
    for attempt in range(tries):
        answer = _run_single_task(
            role="Biên kịch video ngắn tiếng Việt",
            goal="Kịch bản cuốn hút, chính xác, dựng được bằng biểu đồ",
            description=description, expected_output=expected)
        try:
            script = as_script(extract_json(answer))
        except ValueError:                      # không móc được JSON nào ra
            script = as_script(None)
        problems = script_problems(script, cfg)
        if best is None or len(problems) <= len(best_problems):
            best, best_problems = script, problems
        if not problems:
            return script
        log.warning("Kịch bản hụt chuẩn (%s) — lần viết %d/%d", "; ".join(problems),
                    attempt + 1, tries)
        description = base_description + f"""

BẢN NHÁP TRƯỚC BỊ TRẢ LẠI vì: {'; '.join(problems)}.
Phải đạt 16-26 cảnh, {lo_words}-{hi_words} từ, ÍT NHẤT 6 con số cụ thể viết bằng chữ số
(lấy từ TRÍCH BÀI NGUỒN), và nhắc tối đa {MAX_SPOKEN_YEARS - 1} mốc năm khác nhau.
Tách mỗi ý thành một cảnh riêng, đừng gộp."""
    log.warning("Vẫn hụt chuẩn sau %d lần viết — giữ bản ít lỗi nhất (%s)", tries,
                "; ".join(best_problems))
    return best


# ---------------------------------------------------------------- Sản xuất
TEMPLATE_GUIDE = """Các template có sẵn và tham số (CHỈ dùng đúng các template này):
1. "big_number": {"title": str, "value": số, "suffix": str, "source": str, "decimals": int}
   — một con số gây ấn tượng đếm từ 0. Dùng khi lời đọc xoay quanh MỘT con số.
2. "versus": {"title": str, "left": {"label": str, "value": số}, "right": {"label": str,
   "value": số}, "suffix": str, "source": str, "decimals": int}
   — so sánh 2 bên (Việt-Hàn để left=Việt Nam, right=Hàn Quốc).
3. "bar_chart": {"title": str, "items": [{"label": str, "value": số}], "unit": str,
   "source": str, "decimals": int} — xếp hạng 3-6 mục.
4. "line_chart": {"title": str, "xs": [số...], "ys": [số...], "unit": str, "source": str,
   "decimals": int} — xu hướng theo thời gian, xs/ys cùng độ dài.
   SO HAI NƯỚC QUA CÁC NĂM (dạng mạnh nhất của kênh): thay "ys" bằng
   "series": [{"label": "Việt Nam", "ys": [...]}, {"label": "Hàn Quốc", "ys": [...]}],
   mỗi "ys" dài bằng "xs" (cùng các năm). Màu đỏ/xanh của hai nước tự gán theo nhãn.
5. "statement": {"text": str (<= 14 từ), "source": str} — câu chữ lớn giữa màn,
   KHÔNG có số. Dùng cho hook, câu dẫn, câu chuyển, câu kết.
6. "percent": {"title": str, "value": số từ 0 đến 100, "label": str, "source": str,
   "decimals": int} — vòng tròn tô dần tới X%. Dùng khi lời đọc xoay quanh MỘT tỷ lệ
   phần trăm nằm trong khoảng 0-100% ("hơn 60% số ca", "chiếm 38,4%"). Phần trăm
   TĂNG/GIẢM vượt 100% thì dùng "big_number" với suffix "%".
7. "bar_race": {"title": str, "unit": str, "source": str} — CUỘC ĐUA SỐ LIỆU: thanh ngang
   của nhiều nước đổi chỗ theo thứ hạng qua từng mốc năm. CHỈ dùng khi DỮ LIỆU NGUỒN có
   bảng theo năm của từ 3 nước trở lên. KHÔNG chép số — máy tự điền "years"/"items" từ
   bảng. Cảnh này chạy lâu: cho nó gánh 2-3 câu lời đọc kể diễn biến cuộc đua.
8. "map": {"title": str, "unit": str, "source": str} — BẢN ĐỒ châu Á tô màu theo số liệu
   năm mới nhất, Việt Nam và Hàn Quốc có nhãn số riêng. CHỈ dùng khi DỮ LIỆU NGUỒN có bảng
   theo năm của từ 3 nước châu Á trở lên. KHÔNG chép số — máy tự điền "items"/"year" từ bảng.
   Hợp với câu nói về bức tranh cả khu vực ở thời điểm hiện tại.
"""

ANIMATED_LONG = {"bar_race"}     # cảnh chuyển động suốt thời lượng: được gánh nhiều lời hơn


def static_scenes(spec: list, max_words: int) -> list:
    """Các cụm cảnh mà mỗi hình phải đứng yên quá lâu -> danh sách mô tả ngắn.

    Một câu lời có thể trải trên nhiều cảnh liền nhau (cùng 'voice'); thời lượng câu
    được chia đều cho các cảnh đó (assemble.voice_groups). Vì vậy đo theo SỐ TỪ của câu
    chia cho SỐ CẢNH gánh nó."""
    out, k = [], 0
    while k < len(spec):
        v = " ".join(str(spec[k].get("voice") or "").split())
        j = k
        while j + 1 < len(spec) and " ".join(str(spec[j + 1].get("voice") or "").split()) == v:
            j += 1
        words, scenes = len(v.split()), j - k + 1
        # Cuộc đua chuyển động liên tục nên được gánh gấp 3 (trong 2-3 câu kể diễn biến)
        limit = max_words * (3 if spec[k].get("template") in ANIMATED_LONG else 1)
        if v and words / scenes > limit:
            out.append(f"cảnh {k + 1} ({spec[k].get('template')}) mang {words} từ cho {scenes} hình")
        k = j + 1
    return out


FOCUS_LABELS = {"việt nam", "hàn quốc"}
MAX_LINES = 4              # biểu đồ đường trên khung dọc: quá 4 đường là không đọc nổi


def fill_series_from_data(spec: list, data_series: list) -> int:
    """Điền số liệu THẬT vào mọi cảnh line_chart / bar_race từ bảng gốc của ý tưởng (nếu có).

    Model chỉ quyết định vẽ biểu đồ nào và cho nước nào (qua nhãn trong "series");
    số liệu do code chép từ bảng, nên không thể chép sai hay bịa. Nhãn không khớp nước nào
    (hoặc biểu đồ một đường không nhãn) thì vẽ đủ các nước có trong bảng. Cuộc đua luôn
    gồm mọi nước, trên những mốc năm nước nào cũng có số.
    Trả về số cảnh đã điền.
    """
    if not data_series:
        return 0
    filled = 0
    for sc in spec:
        if not isinstance(sc.get("params"), dict):
            continue
        p = sc["params"]
        if sc.get("template") == "map":
            # Bản đồ: năm mới nhất mà nước nào cũng có số
            common = set.intersection(*[set(s["xs"]) for s in data_series])
            if not common:
                continue
            year = max(common)
            p["year"] = year
            p["items"] = [{"label": s["label"], "value": dict(zip(s["xs"], s["ys"]))[year]}
                          for s in data_series]
            filled += 1
            continue
        if sc.get("template") == "bar_race":
            # Cuộc đua: mọi nước trong bảng, trên những mốc năm ai cũng có số
            years = sorted(set.intersection(*[set(s["xs"]) for s in data_series]))
            p["years"] = years
            p["items"] = [{"label": s["label"],
                           "values": [dict(zip(s["xs"], s["ys"]))[y] for y in years]}
                          for s in data_series]
            filled += 1
            continue
        if sc.get("template") != "line_chart":
            continue
        wanted = {str(s.get("label", "")).strip().lower()
                  for s in p.get("series") or [] if isinstance(s, dict)}
        # Không ghi rõ nước nào: vẽ Việt Nam và Hàn Quốc (góc của kênh), không phải cả 10
        # nước của một cuộc đua — 10 đường trên một khung dọc là mớ bòng bong (ca thật #18)
        chosen = ([s for s in data_series if s["label"].lower() in wanted]
                  or [s for s in data_series if s["label"].lower() in FOCUS_LABELS]
                  or data_series)
        if len(chosen) > MAX_LINES:              # cắt bớt nhưng luôn giữ Việt Nam, Hàn Quốc
            keep = sorted(chosen, key=lambda s: s["label"].lower() not in FOCUS_LABELS)[:MAX_LINES]
            chosen = [s for s in chosen if s in keep]
        p["series"] = [{"label": s["label"], "xs": list(s["xs"]), "ys": list(s["ys"])} for s in chosen]
        p["xs"] = sorted({x for s in chosen for x in s["xs"]})
        p.pop("ys", None)
        filled += 1
    return filled


def design_scenes(idea: dict, scenes: list, cfg: dict) -> list:
    """Agent Sản xuất: dịch từng cảnh kịch bản thành scene spec cho engine Manim.

    Luật sắt: mọi con số phải lấy từ kịch bản, không bịa. Tự kiểm độ đa dạng
    template (video toàn big_number = nội dung theo mẫu lặp lại -> cấm).
    """
    import collections

    pacing = cfg.get("pacing", {"scene_seconds_min": 2, "scene_seconds_max": 4})
    listing = "\n".join(
        f"- Cảnh {i+1}: LỜI: {s.get('voice','')} | HÌNH GỢI Ý: {s.get('visual','')}"
        f" | NGUỒN: {s.get('data_source','')}"
        for i, s in enumerate(scenes)
    )
    total_words = sum(len(str(s.get("voice", "")).split()) for s in scenes)
    target_secs = total_words / words_per_second(cfg)
    lo_total, hi_total = int(target_secs * 0.75), int(target_secs * 1.25)

    # Dữ liệu gốc của ý tưởng (bảng số World Bank, tóm tắt bài báo): agent được phép lấy số
    # ở đây để vẽ biểu đồ — một đường xu hướng cần 6-10 điểm, lời đọc không thể đọc hết.
    from .sources.worldbank import parse_series
    source_data = str(idea.get("summary") or "").strip()[:3000]
    data_series = parse_series(source_data)
    data_block = (f"\nDỮ LIỆU NGUỒN (số thật, ĐƯỢC dùng cho biểu đồ kể cả khi lời đọc không nhắc"
                  f" hết):\n\"\"\"\n{source_data}\n\"\"\"\n" if source_data else "")
    if len(data_series) >= 3:
        data_block += (
            f"\nBẢNG CÓ SỐ THEO NĂM CỦA {len(data_series)} NƯỚC: phải có ĐÚNG MỘT cảnh \"bar_race\""
            " (cuộc đua) gánh 2-3 câu kể diễn biến xếp hạng — chỉ ghi title, unit, source, máy tự"
            " điền số. Có thể thêm \"line_chart\" với \"series\": [{\"label\": \"Việt Nam\"},"
            " {\"label\": \"Hàn Quốc\"}] (máy tự điền số) để soi riêng hai nước, và MỘT cảnh"
            " \"map\" (bản đồ năm mới nhất, máy tự điền số) cho câu nói về cả khu vực.\n")
    elif data_series:
        names = ", ".join(f'{{"label": "{s["label"]}"}}' for s in data_series)
        data_block += (
            "\nBẢNG CÓ SỐ THEO NĂM: nên có 1-2 cảnh \"line_chart\" so các nước qua các năm. Với cảnh"
            f" đó KHÔNG chép số — chỉ ghi \"series\": [{names}] (chọn nước cần vẽ) cùng title,"
            " unit, source; máy tự điền đúng xs/ys từ bảng.\n")

    base_description = f"""Video của kênh "{cfg['channel']['name']}", ý tưởng: {idea['title']}

Kịch bản (lời đọc tổng cộng {total_words} từ ≈ {target_secs:.0f} giây):
{listing}
{data_block}
{TEMPLATE_GUIDE}

Yêu cầu:
- Bám thứ tự kịch bản. ĐƯỢC gộp 2-3 cảnh kịch bản liền nhau thành MỘT cảnh đồ họa
  khi các con số cùng nhóm (so hạng -> "bar_chart", theo thời gian -> "line_chart",
  hai phe -> "versus"), nhưng cảnh gộp phải CỘNG DỒN thời lượng lời của các cảnh gốc.
- KHÔNG bỏ câu nào: mọi câu của kịch bản phải nằm nguyên văn trong "voice" của một cảnh.
  "seconds" chỉ là ước lượng thời gian đọc của cảnh (tổng khoảng {lo_total}-{hi_total} giây);
  máy sẽ đo lại theo giọng đọc thật.
- LUẬT SỐ LIỆU (quan trọng nhất): MỌI con số trong spec phải xuất hiện NGUYÊN VĂN
  trong lời kịch bản hoặc trong DỮ LIỆU NGUỒN. Cảnh nào lời đọc KHÔNG chứa con số ->
  BẮT BUỘC dùng "statement" (trừ khi vẽ biểu đồ bằng số của DỮ LIỆU NGUỒN đúng với ý
  câu đó). TUYỆT ĐỐI không tự chế số liệu, không ước lượng, không minh họa tượng trưng.
- LUẬT ĐA DẠNG: "big_number" chiếm tối đa 40%% số cảnh; hai cảnh liền nhau hạn chế
  cùng template; con số nhỏ tầm thường (1, 2, 3...) không đáng làm big_number.
  HAI con số cùng đơn vị của hai đối tượng (hai nước, hai món, trước và sau) -> MỘT cảnh
  "versus" thay vì hai cảnh "big_number". Số của MỘT đối tượng qua nhiều năm -> "line_chart".
  Từ 3 đối tượng cùng đơn vị trở lên -> "bar_chart".
- "seconds" mỗi cảnh thường {pacing['scene_seconds_min']}-{pacing['scene_seconds_max']} giây; cảnh gộp hai câu thì dài hơn.
- "title" ngắn <= 9 từ, tiếng Việt; "source" ghi nguồn của cảnh đó.
- Mỗi cảnh có trường "voice": lời đọc NGUYÊN VĂN của (các) cảnh kịch bản tương ứng,
  không sửa chữ; cảnh gộp thì nối các câu lại.
- Câu lời DÀI (đọc lâu hơn {pacing['scene_seconds_max']} giây) thì chia thành nhiều cảnh
  đồ họa LIỀN NHAU, mỗi cảnh minh họa một ý của câu theo đúng thứ tự ý đó được đọc.
  Các cảnh ấy ghi CÙNG một "voice" nguyên văn cả câu: máy chỉ đọc câu đó MỘT lần
  rồi chia thời lượng cho các cảnh. Không chép "voice" của câu này sang cảnh của câu khác.
- KHÔNG thêm template "intro" (engine tự thêm)."""
    expected = """JSON array, mỗi phần tử:
{"template": "<tên template>", "seconds": <số>, "voice": "<lời đọc nguyên văn>", "params": {...}}"""

    # Tập chữ số có thật — chuẩn đối chiếu chống bịa: lời kịch bản, tiêu đề ý tưởng (kịch
    # bản hay viết số bằng chữ: "tám nghìn...") và dữ liệu nguồn của ý tưởng.
    from .utils import digit_set, digits_of, number_values, spec_values
    allowed_text = (" ".join(str(s.get("voice", "")) for s in scenes)
                    + " " + str(idea.get("title", "")) + " " + str(idea.get("angle", ""))
                    + " " + source_data)
    script_digits, script_values = digit_set(allowed_text), number_values(allowed_text)

    def known(v) -> bool:
        """Con số v có căn cứ: khớp theo chuỗi chữ số (kể cả quy đổi nghìn/triệu/tỷ),
        hoặc khớp theo giá trị ("4,9" với "4,90")."""
        if digits_of(v) & script_digits:
            return True
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        return any(abs(f - x) <= 1e-9 * max(1.0, abs(x)) for x in script_values)

    def fabricated(spec: list) -> list:
        """Những con số trong spec KHÔNG có trong kịch bản/dữ liệu nguồn (trừ trục năm xs)."""
        return [v for sc in spec for v in spec_values(sc.get("params"))
                if digits_of(v) and not known(v)]

    def as_spec(obj) -> list:
        """Đưa câu trả lời về đúng dạng danh sách cảnh (model dự phòng hay trả sai khuôn)."""
        if isinstance(obj, dict):
            obj = next((v for v in obj.values() if isinstance(v, list)), [])
        if not isinstance(obj, list):
            return []
        scenes_out = [s for s in obj if isinstance(s, dict)]
        for s in scenes_out:
            if not isinstance(s.get("params"), dict):
                s["params"] = {}
        return scenes_out

    # Một hình được "gánh" tối đa chừng này từ lời đọc: ~2 lần nhịp đổi cảnh tối đa.
    # (Ca thật #17: cảnh so găng gộp hai câu dài, đứng yên 13 giây.)
    max_words = int(2 * pacing["scene_seconds_max"] * words_per_second(cfg))

    def spoken_words(spec: list) -> int:
        """Số từ lời đọc mà spec mang theo, mỗi câu tính MỘT lần (câu trải nhiều cảnh
        liền nhau được ghi lặp ở các cảnh đó — xem assemble.voice_groups)."""
        n, prev = 0, None
        for s in spec:
            v = " ".join(str(s.get("voice") or "").split())
            if v and v != prev:
                n += len(v.split())
            prev = v
        return n

    description, best, best_problems = base_description, [], None
    for attempt in range(3):
        try:
            spec = as_spec(extract_json(_run_single_task(
                role="Đạo diễn đồ họa dữ liệu",
                goal="Dịch kịch bản thành cảnh đồ họa, số liệu tuyệt đối trung thực",
                description=description, expected_output=expected)))
        except ValueError:
            spec = []
        fill_series_from_data(spec, data_series)
        # Đơn điệu chỉ tính trên các template SỐ LIỆU: kịch bản ít con số thì
        # nhiều statement là đúng đắn, không được ép vẽ biểu đồ (sẽ sinh bịa số).
        counts = collections.Counter(s.get("template") for s in spec)
        data_counts = {k: v for k, v in counts.items() if k not in ("statement", "intro")}
        share = max(data_counts.values(), default=0) / max(len(spec), 1)
        problems = []
        if not spec:
            problems.append("không đọc được danh sách cảnh — phải trả về đúng một JSON array")
        fakes = fabricated(spec)
        if fakes:
            problems.append(f"BỊA SỐ LIỆU: các số {fakes[:8]} không có trong kịch bản lẫn dữ liệu"
                            " nguồn. Cảnh không có số thật thì dùng 'statement'")
        if len(spec) >= 6 and share > 0.45:
            problems.append(f"đơn điệu: {dict(counts)} — hai con số cùng đơn vị ở hai cảnh liền"
                            " nhau thì gộp thành MỘT cảnh 'versus' (voice nối hai câu); số qua"
                            " các năm thì 'line_chart'; từ 3 hạng mục thì 'bar_chart'")
        # Spec phải mang ĐỦ lời đọc. (Trước đây kiểm bằng tổng "seconds" đã kẹp 2-4s mỗi
        # cảnh: gộp hai câu vào một cảnh 'versus' làm tổng tụt xuống và bị trả lại, nên
        # model né 'versus', toàn tách thành 'big_number'.)
        covered = spoken_words(spec)
        if spec and covered < 0.9 * total_words:
            problems.append(f"spec chỉ mang {covered}/{total_words} từ lời đọc — KHÔNG được bỏ câu"
                            " nào của kịch bản; mỗi câu phải nằm nguyên văn trong 'voice' của một cảnh")
        elif covered > 1.15 * total_words:
            problems.append(f"lời đọc bị chép lặp ({covered} từ so với {total_words} từ của kịch"
                            " bản) — mỗi câu chỉ thuộc một cảnh, hoặc các cảnh LIỀN NHAU")
        slow = static_scenes(spec, max_words)
        if slow:
            problems.append("cảnh đứng yên quá lâu: " + "; ".join(slow) + " — tách thành 2-3 cảnh"
                            " LIỀN NHAU (mỗi cảnh một ý của câu, hoặc thêm 'statement' tóm ý),"
                            " các cảnh đó ghi CÙNG 'voice'")
        if best_problems is None or len(problems) <= len(best_problems):
            best, best_problems = spec, problems
        if not problems:
            return spec
        log.warning("Spec bị trả lại (lần %d): %s", attempt + 1, "; ".join(problems))
        description = base_description + "\n\nBẢN TRƯỚC BỊ TRẢ LẠI vì: " + "; ".join(problems)
    spec = best
    # Hết lượt mà vẫn bịa số -> cảnh đó thành cảnh chữ, GIỮ NGUYÊN lời đọc. (Trước đây
    # cắt bỏ cả cảnh: an toàn về số liệu nhưng video mất luôn câu lời của cảnh đó.)
    fakes = set(str(f) for f in fabricated(spec))
    for sc in spec:
        p = sc.get("params", {})
        if any(str(v) in fakes for v in spec_values(p)):
            text = str(p.get("title") or sc.get("voice") or "")
            log.warning("Cảnh '%s' còn số không rõ nguồn sau 3 lần — đổi thành cảnh chữ", text[:40])
            sc["template"] = "statement"
            sc["params"] = {"text": " ".join(text.split()[:14]), "source": p.get("source", "")}
    return spec


# ---------------------------------------------------------------- Kiểm chứng
def fact_check(script: dict, idea: dict, source_text: str, cfg: dict) -> dict:
    """Đối chiếu từng claim với nội dung bài nguồn. Trả về verdict từng claim.

    Giới hạn v1: mới đối chiếu với 1 nguồn gốc (bài báo/paper đã lấy về).
    Khi thêm search API sẽ nâng lên luật '2 nguồn độc lập' như thiết kế.
    """
    out = _run_single_task(
        role="Người kiểm chứng thông tin",
        goal="Không để lọt số liệu sai hoặc không có trong nguồn",
        description=f"""Kịch bản có các khẳng định sau:
{json.dumps(script.get('claims', []), ensure_ascii=False, indent=2)}

Toàn văn bài nguồn ({idea['source_url']}):
---
{source_text[:6000]}
---

Với TỪNG khẳng định, kiểm tra: nguồn có thật sự nói vậy không? Số liệu có khớp
không? Khẳng định nào không tìm thấy trong nguồn thì đánh dấu unsupported.""",
        expected_output="""JSON object:
{"verdicts": [{"claim": "...", "ok": true/false, "note": "<giải thích ngắn>"}],
 "pass": true/false}""",
    )
    try:
        fc = extract_json(out)
    except ValueError:
        fc = None
    if not isinstance(fc, dict):                # model trả sai khuôn = CHƯA kiểm chứng được
        return {"pass": False, "verdicts": [], "note": "Agent Kiểm chứng trả lời sai khuôn"}
    if not isinstance(fc.get("verdicts"), list):
        fc["verdicts"] = []
    fc["verdicts"] = [v for v in fc["verdicts"] if isinstance(v, dict)]
    return fc


# ------------------------------------------------------------------ Đăng bài
def write_metadata(idea: dict, scenes: list, hooks: list, cfg: dict,
                   feedback: str = None) -> dict:
    """Agent Đăng bài: đề xuất tiêu đề, mô tả, hashtag, thẻ cho video đã dựng.

    Chỉ là ĐỀ XUẤT thô — src/publish/metadata.py sẽ ép giới hạn YouTube, soát số
    trong tiêu đề và tự gắn nguồn + dòng khai báo AI (LLM không cần viết các phần đó).
    """
    from .analysis.formula import load_formula
    f = load_formula() or {}
    voice = " ".join(str(s.get("voice", "")) for s in scenes)
    description = f"""Viết thông tin đăng bài cho một video ngắn dọc (YouTube Shorts + TikTok)
của kênh "{cfg['channel']['name']}" — {cfg['channel']['description']}

TOÀN BỘ LỜI ĐỌC của video (đã kiểm chứng):
{voice}

Các câu mở đầu đã viết: {'; '.join(hooks or [])}
Khuôn tiêu đề hay thắng ở kênh cùng mảng (tham khảo, không bắt buộc):
{'; '.join(f.get('title_patterns', []))}

Luật chính sách (ƯU TIÊN CAO HƠN khuôn tiêu đề): {cfg['policy_rules']}

Yêu cầu:
- "title": tiếng Việt, <= 70 ký tự, gây tò mò nhưng TRUNG THỰC với nội dung.
  Không viết hoa cả câu, không doạ dẫm. Nếu dùng con số thì phải là con số có
  NGUYÊN VĂN trong lời đọc ở trên, viết bằng chữ số. Không tự thêm hashtag vào title.
- "description": 1-2 câu tiếng Việt tóm tắt video nói gì, có 1 con số đắt nhất.
  KHÔNG ghi nguồn, KHÔNG ghi hashtag (hệ thống tự thêm).
- "hashtags": 3 hashtag chủ đề, không dấu, viết liền (vd "#khihau").
- "tags": 8-12 từ khoá tìm kiếm tiếng Việt có dấu (vd "biến đổi khí hậu")."""
    if feedback:
        description += f"\n\nBẢN TRƯỚC BỊ TRẢ LẠI vì: {feedback}"
    out = _run_single_task(
        role="Biên tập viên đăng bài video ngắn",
        goal="Tiêu đề khiến người ta dừng lại xem mà không sai một con số nào",
        description=description,
        expected_output="""JSON object:
{"title": "...", "description": "...", "hashtags": ["#...", "#...", "#..."], "tags": ["...", "..."]}""",
    )
    return extract_json(out)
