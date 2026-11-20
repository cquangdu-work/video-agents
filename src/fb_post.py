"""BÀI VIẾT FACEBOOK kèm mỗi video (kênh Việt, Du xin 20/11/2026): ảnh biểu đồ + chữ, đăng lên Trang ngoài Reel.

Vì sao: chương trình Kiếm tiền từ nội dung của Facebook tính cả bài viết (ảnh, chữ) chứ không chỉ video, và bài
viết tới được người lướt bảng tin không xem Reels. Một video đã kiểm chứng -> một bài viết, không tốn thêm nguồn.

- CHỮ: model viết từ CHÍNH lời đọc + bảng số đã kiểm chứng, rồi qua đúng các cổng code của kịch bản: mọi con số có
  trong nguồn (crew.unsourced_numbers), câu so sánh / nguyên nhân / "liên tục tăng" / câu chữ trái bảng số
  (src/claims.py), không khuôn câu view (story.hook_problems). Trượt 2 lần -> không có bài viết (video vẫn đăng).
- ẢNH: Remotion vẽ lại MỘT khung của chính video (props đã dựng), bỏ phụ đề, chọn cảnh giàu hình nhất
  (bản đồ > cuộc đua > biểu đồ...) ở lúc hoạt ảnh đã xong.
- DUYỆT: bài hiện ngay dưới video trong tin duyệt; ✅ ở video là duyệt cả bài. Du TRẢ LỜI tin bài viết bằng câu khác
  -> thành nội dung bài (review._handle_message). Đăng: src/review.push_fb_post, hẹn giờ publish.facebook.post_time_local.
"""
import json
import logging
import re
import subprocess
from pathlib import Path

from . import lang

log = logging.getLogger("fb_post")

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "data" / "render"
MIN_CHARS, MAX_CHARS = 250, 1300
# cảnh đẹp nhất để làm ảnh: hình giàu thông tin trước (kind trong props của Remotion, src/render/web.py)
IMAGE_KINDS = ("map", "bar_race", "line_solo", "bar_chart", "versus", "percent", "big_number")


def problems(text: str, idea: dict, voices: list) -> list:
    """Lỗi của một bài viết — CÙNG các cổng code với kịch bản. Rỗng = đạt."""
    from . import claims, crew, story
    text = str(text or "").strip()
    out = []
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        out.append(f"độ dài {len(text)} ký tự (cần {MIN_CHARS}-{MAX_CHARS})")
    if re.search(r"https?://|www\.", text):
        out.append("có đường link (Facebook giảm tiếp cận bài có link; nguồn ghi bằng chữ)")
    first = text.splitlines()[0] if text else ""
    out += [f"câu mở đầu: {p}" for p in story.hook_problems(first)]
    # số trong bài phải có trong bảng số / bài nguồn / lời đọc đã kiểm chứng
    fake = crew.unsourced_numbers({"scenes": [{"voice": text}]}, idea, " ".join(voices))
    if fake:
        out.append(f"số không có trong nguồn: {', '.join(fake[:5])}")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    summary = idea.get("summary")
    out += claims.comparison_problems(sentences, summary)
    out += claims.cause_claims(sentences, summary)
    out += claims.trend_problems(sentences, summary)
    out += claims.wording_problems(sentences, summary)
    return out


def draft(idea: dict, voices: list, cfg: dict, run=None) -> str:
    """Viết bài (2 lần thử). Trả về chữ đã qua mọi cổng, hoặc "" nếu không đạt."""
    if run is None:
        from .crew import _run_single_task as run
    ch = cfg["channel"]
    base = f"""Viết MỘT BÀI ĐĂNG FACEBOOK ({lang.locale()['name']}) cho Trang "{ch['name']}" — {ch['description']}
Bài đi kèm một ẢNH biểu đồ/bản đồ lấy từ video. Người đọc lướt bảng tin: câu đầu phải giữ họ lại.

LỜI ĐỌC CỦA VIDEO (đã kiểm chứng — nguồn sự thật chính):
{chr(10).join('- ' + v for v in voices)}

BẢNG SỐ GỐC (chỉ dùng số có ở đây hoặc trong lời đọc):
{str(idea.get('summary') or '')[:2500]}

Yêu cầu:
- {MIN_CHARS}-{MAX_CHARS} ký tự, 3-5 đoạn ngắn. Câu đầu: điều bất ngờ nhất, nói rõ đang đo cái gì, có con số.
- 2-4 con số đắt nhất, viết bằng CHỮ SỐ, chép ĐÚNG như bảng số/lời đọc; không tự tính số mới.
- Một câu nói ý nghĩa con số (dùng "cách nói dễ hình dung" nếu bảng có). Không nêu nguyên nhân bảng không nói,
  không khuyên người đọc làm gì, không giật tít ("sốc", "không thể tin"...), không "nhất lịch sử".
- Kết bằng MỘT câu hỏi mở thật về chủ đề để người đọc bình luận (không xin like/share).
- Dòng cuối: "Nguồn: <tên nguồn>" (KHÔNG có đường link). Không hashtag (máy tự thêm).
Luật chính sách: {cfg.get('policy_rules', '')}"""
    prompt = base
    for attempt in range(2):
        text = str(run(role="Biên tập viên mạng xã hội của kênh dữ liệu",
                       goal="Bài viết cuốn hút mà không sai một con số nào",
                       description=prompt, expected_output="Chỉ nội dung bài viết, văn bản thường") or "").strip()
        text = re.sub(r"(?m)^\s*#\S+(\s+#\S+)*\s*$", "", text).strip()      # model hay tự chèn dòng hashtag
        bad = problems(text, idea, voices)
        if not bad:
            return text
        log.info("Bài viết Facebook bị trả lại (lần %d): %s", attempt + 1, "; ".join(bad))
        prompt = base + f"\n\nBẢN TRƯỚC BỊ TRẢ LẠI vì: {'; '.join(bad)}. Viết lại cho đạt."
    return ""


def with_hashtags(text: str, cfg: dict, tags=()) -> str:
    """Thêm hashtag cố định của kênh (bỏ #Shorts — chỉ YouTube dùng) + vài hashtag chủ đề."""
    fixed = [h for h in (cfg.get("publish") or {}).get("hashtags_fixed", []) if h.lower() != "#shorts"]
    tags = [t for t in tags if t and t.lower() != "#shorts" and t not in fixed][:2]
    line = " ".join(fixed + list(tags))
    return f"{text}\n\n{line}".strip() if line else text


def pick_frame(props: dict, fps: int = 30):
    """(số khung, kind) của khung đẹp nhất: cảnh giàu hình nhất, 0,3 giây trước khi cảnh hết (hoạt ảnh đã xong)."""
    scenes = props.get("scenes") or []
    for kind in IMAGE_KINDS:
        sc = next((s for s in scenes if s.get("kind") == kind and s.get("end", 0) - s.get("start", 0) > 0.8), None)
        if sc:
            return max(0, int((float(sc["end"]) - 0.3) * fps)), kind
    if scenes:                                   # không có cảnh nào kể trên: giữa video
        return int(float(props.get("duration", 1)) / 2 * fps), scenes[0].get("kind")
    return None, None


def image(script_id: int, out: Path = None) -> Path:
    """Ảnh của bài viết: một khung của chính video, vẽ lại không có phụ đề. Lỗi -> None."""
    from .render import web
    src = RENDER / f"web_{script_id}.props.json"
    try:
        props = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.info("Chưa có props Remotion của kịch bản #%s (video dựng bằng Manim?) — bài viết không ảnh", script_id)
        return None
    frame, kind = pick_frame(props)
    if frame is None:
        return None
    props = {**props, "words": [], "sfx": []}            # bỏ phụ đề: ảnh là biểu đồ sạch
    # JPEG: Facebook nhận ảnh tới 4 MB, khuyên PNG dưới 1 MB — khung 1080x1920 dạng PNG đã ~1 MB
    out = out or RENDER / f"fbpost_{script_id}.jpg"
    pf = out.with_suffix(".props.json")
    pf.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    npx, env = web.node_env()
    try:
        subprocess.run([npx, "remotion", "still", "src/index.ts", "Story", str(out.resolve()), f"--props={pf.resolve()}",
                        f"--frame={frame}", "--image-format=jpeg", "--jpeg-quality=90", "--log=error"],
                       cwd=web.WEB, env=env, check=True, timeout=600,
                       capture_output=True, shell=str(npx).endswith(".cmd"))
    except Exception as exc:
        log.warning("Không vẽ được ảnh bài viết: %s", exc)
        return None
    log.info("Ảnh bài viết Facebook: khung %d (cảnh %s) -> %s", frame, kind, out.name)
    return out
