"""Bốn agent của Giai đoạn 1, điều phối bằng CrewAI (chạy tuần tự).

Luồng: Săn ý tưởng -> Biên tập -> Biên kịch -> Kiểm chứng.
Mỗi bước nhận đầu ra JSON của bước trước. Import crewai để trong hàm
để chế độ --dry-run không cần cài thư viện nặng này.

LLM lấy từ biến môi trường MODEL (chuẩn litellm, ví dụ gemini/gemini-2.5-flash).
"""
import json
import logging
import os

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
    listing = "\n".join(
        f"- [{i['id']}] ({i['source_name']}, {i['lang']}) {i['title']} — {i['summary'][:150]}"
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
bằng biểu đồ/bản đồ/số liệu. Với mỗi ý tưởng, viết góc cụ thể bằng tiếng Việt.""",
        expected_output="""JSON array, mỗi phần tử:
{"id": <id gốc>, "angle": "<góc cụ thể, 1-2 câu tiếng Việt>", "reason": "<vì sao chọn>"}""",
    )
    return extract_json(out)


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
    """Nếu đã chạy phân tích đối thủ thì nhét công thức vào prompt Biên kịch."""
    from .analysis.formula import load_formula
    f = load_formula()
    if not f:
        return ""
    return f"""
CÔNG THỨC rút từ video ăn khách của các kênh cùng mảng (áp dụng linh hoạt, không máy móc):
- Khuôn tiêu đề/hook hay thắng: {'; '.join(f.get('title_patterns', []))}
- Luật viết hook: {'; '.join(f.get('hook_rules', []))}
- Độ dài hay thắng: {f.get('length_seconds', {})}
"""


# ------------------------------------------------------------------ Biên kịch
# Khoảng chấp nhận: video đổi cảnh 2-4s -> 60-90s cần cỡ 15-24 cảnh.
SCRIPT_MIN_SCENES, SCRIPT_MAX_SCENES = 12, 28
SCRIPT_MIN_WORDS, SCRIPT_MAX_WORDS = 150, 280


def _script_stats(script: dict) -> tuple:
    scenes = script.get("scenes", [])
    words = sum(len(str(s.get("voice", "")).split()) for s in scenes)
    return len(scenes), words


def write_script(idea: dict, cfg: dict) -> dict:
    """Viết kịch bản 60-90 giây + 3 phương án câu mở đầu.

    Tự kiểm số cảnh/số từ; hụt chuẩn thì trả lại cho LLM viết lại 1 lần
    kèm nhận xét cụ thể (giống biên tập viên trả bài).
    """
    ch = cfg["channel"]
    base_description = f"""Viết kịch bản video dọc {ch['video_seconds_min']}-{ch['video_seconds_max']} giây
cho kênh "{ch['name']}". Tốc độ đọc ~160 từ/phút -> TỔNG LỜI ĐỌC PHẢI ĐẠT 170-240 từ.

Ý tưởng: {idea['title']}
Góc: {idea['angle']}
Nguồn gốc: {idea['source_url']}
Tóm tắt nguồn: {idea.get('summary', '')}

Luật chính sách (bắt buộc tuân thủ): {cfg['policy_rules']}
{_formula_block()}

Yêu cầu CỨNG về cấu trúc (video đổi cảnh mỗi 2-4 giây):
- Chia thành 15-24 CẢNH. Mỗi cảnh đúng 1 câu lời đọc NGẮN (7-15 từ).
- Cảnh 1 chính là hook. Dàn bài: hook (1 cảnh) -> mở vấn đề (2-3 cảnh)
  -> số liệu chính, mỗi con số một cảnh (8-14 cảnh) -> ngã rẽ/so sánh bất ngờ
  (2-3 cảnh) -> câu kết đọng lại (1-2 cảnh).
- Mỗi cảnh kèm mô tả hình (biểu đồ gì, dữ liệu gì) + nguồn dữ liệu của cảnh đó.
- Viết 3 PHƯƠNG ÁN hook khác nhau, mỗi câu <= 15 từ.
- Kết không kêu gọi hành động sáo rỗng.
- Mọi con số trong lời đọc phải ghi rõ lấy từ nguồn nào."""
    expected = """JSON object:
{"hooks": ["...", "...", "..."],
 "scenes": [{"voice": "<1 câu lời đọc>", "visual": "<mô tả hình/biểu đồ>", "data_source": "<nguồn>"}],
 "claims": [{"claim": "<khẳng định có số liệu>", "source": "<nguồn/link>"}]}"""

    description, script = base_description, None
    for attempt in range(2):
        script = extract_json(_run_single_task(
            role="Biên kịch video ngắn tiếng Việt",
            goal="Kịch bản cuốn hút, chính xác, dựng được bằng biểu đồ",
            description=description, expected_output=expected))
        n, words = _script_stats(script)
        if SCRIPT_MIN_SCENES <= n <= SCRIPT_MAX_SCENES and SCRIPT_MIN_WORDS <= words <= SCRIPT_MAX_WORDS:
            return script
        log.warning("Kịch bản hụt chuẩn (%d cảnh, %d từ) — trả lại viết lần %d",
                    n, words, attempt + 2)
        description = base_description + f"""

BẢN NHÁP TRƯỚC BỊ TRẢ LẠI: chỉ có {n} cảnh và {words} từ lời đọc.
Phải đạt 15-24 cảnh, tổng 170-240 từ. Tách mỗi ý thành một cảnh riêng,
mỗi con số một cảnh, đừng gộp."""
    log.warning("Vẫn hụt chuẩn sau 2 lần — dùng bản cuối")
    return script


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
"""


def design_scenes(idea: dict, scenes: list, cfg: dict) -> list:
    """Agent Sản xuất: dịch từng cảnh kịch bản thành scene spec cho engine Manim.

    Luật sắt: mọi con số trong spec phải lấy từ kịch bản/claims, không được bịa.
    """
    pacing = cfg.get("pacing", {"scene_seconds_min": 2, "scene_seconds_max": 4})
    listing = "\n".join(
        f"- Cảnh {i+1}: LỜI: {s.get('voice','')} | HÌNH GỢI Ý: {s.get('visual','')}"
        f" | NGUỒN: {s.get('data_source','')}"
        for i, s in enumerate(scenes)
    )
    out = _run_single_task(
        role="Đạo diễn đồ họa dữ liệu",
        goal="Dịch kịch bản thành cảnh đồ họa, số liệu tuyệt đối trung thực",
        description=f"""Video của kênh "{cfg['channel']['name']}", ý tưởng: {idea['title']}

Kịch bản:
{listing}

{TEMPLATE_GUIDE}

Yêu cầu:
- Mỗi cảnh kịch bản -> đúng 1 cảnh đồ họa, giữ nguyên thứ tự.
- "seconds" mỗi cảnh: {pacing['scene_seconds_min']}-{pacing['scene_seconds_max']} giây,
  ước theo độ dài lời đọc (~2.7 từ/giây).
- MỌI con số phải lấy nguyên văn từ kịch bản. Cảnh không có số liệu cụ thể thì dùng
  "big_number" với con số đáng chú ý nhất trong lời của cảnh đó.
- "title" ngắn <= 9 từ, tiếng Việt; "source" ghi nguồn của cảnh đó.
- KHÔNG thêm template "intro" (engine tự thêm).""",
        expected_output="""JSON array, mỗi phần tử:
{"template": "<tên template>", "seconds": <số>, "params": {...}}""",
    )
    return extract_json(out)


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
    return extract_json(out)
