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
def write_script(idea: dict, cfg: dict) -> dict:
    """Viết kịch bản 60-90 giây + 3 phương án câu mở đầu."""
    ch = cfg["channel"]
    out = _run_single_task(
        role="Biên kịch video ngắn tiếng Việt",
        goal="Kịch bản cuốn hút, chính xác, dựng được bằng biểu đồ",
        description=f"""Viết kịch bản video dọc {ch['video_seconds_min']}-{ch['video_seconds_max']} giây
(tốc độ đọc ~160 từ/phút, tức khoảng 170-240 từ) cho kênh "{ch['name']}".

Ý tưởng: {idea['title']}
Góc: {idea['angle']}
Nguồn gốc: {idea['source_url']}
Tóm tắt nguồn: {idea.get('summary', '')}

Luật chính sách (bắt buộc tuân thủ): {cfg['policy_rules']}
{_formula_block()}

Yêu cầu:
- Viết 3 PHƯƠNG ÁN câu mở đầu (hook) khác nhau, mỗi câu <= 15 từ.
- Thân bài chia theo từng "cảnh": mỗi cảnh 1-2 câu lời đọc + mô tả hình
  (biểu đồ gì, dữ liệu gì, nguồn dữ liệu nào).
- Kết bằng một câu đọng lại, không kêu gọi hành động sáo rỗng.
- Mọi con số trong lời đọc phải ghi rõ lấy từ nguồn nào.""",
        expected_output="""JSON object:
{"hooks": ["...", "...", "..."],
 "scenes": [{"voice": "<lời đọc>", "visual": "<mô tả hình/biểu đồ>", "data_source": "<nguồn>"}],
 "claims": [{"claim": "<khẳng định có số liệu>", "source": "<nguồn/link>"}]}""",
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
