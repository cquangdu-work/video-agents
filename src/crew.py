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


def _llm():
    from crewai import LLM
    return LLM(model=os.getenv("MODEL", "gemini/gemini-2.5-flash"), temperature=0.7)


def _run_single_task(role: str, goal: str, description: str, expected_output: str) -> str:
    """Tạo một crew 1-agent-1-task rồi chạy. Đơn giản, dễ debug từng bước."""
    from crewai import Agent, Crew, Task

    agent = Agent(role=role, goal=goal, backstory="", llm=_llm(), verbose=False)
    task = Task(description=description, expected_output=expected_output, agent=agent)
    crew = Crew(agents=[agent], tasks=[task], verbose=False)
    return str(crew.kickoff())


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
