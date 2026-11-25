"""Bình luận đầu tiên của kênh dưới mỗi video (Du đồng ý 26/11/2026).

Vì sao: tới 26/11 gần như mọi video của cả hai kênh có 0 bình luận, trong khi bình luận là một trong các tín hiệu
"người xem tương tác" của YouTube, và lời gợi ý chủ đề trong bình luận đi thẳng vào hàng chờ chủ đề (agent Cộng
đồng, src/topics.py). Kênh tự mở lời bằng MỘT câu hỏi để người xem có chỗ trả lời.

Luật:
  - Câu do CODE ghép từ mẫu cố định (không gọi model): không có số liệu mới nào cần kiểm chứng, không câu view.
  - Chỉ đăng khi bot đã thấy video CÔNG KHAI (review.check_scheduled) — đúng lúc YouTube bắt đầu phân phối.
  - Mỗi video đúng một lần (state `yt_comment_<id>`), tốn 50 đơn vị hạn mức (yt_quota "insert").
  - YouTube API không ghim được bình luận: Du muốn ghim thì làm tay trong ứng dụng.
  - Tắt: `publish.youtube.first_comment: false` trong file cấu hình kênh.
"""
import logging

from .. import db, lang

log = logging.getLogger(__name__)

# Mẫu xoay vòng theo số video. {source}: tên nguồn số liệu của ý tưởng (World Bank Open Data, Our World in Data...).
TEMPLATES = {
    "vi": [
        "Con số này có giống bạn đoán không? Muốn xem Việt Nam đứng thứ mấy ở chỉ số nào nữa, bình luận để kênh làm"
        " video tiếp nhé 👇",
        "Con số nào trong video làm bạn bất ngờ nhất? 👇 (Số liệu: {source})",
        "Bạn muốn so Việt Nam với nước nào tiếp theo? Gợi ý trong bình luận, kênh sẽ làm thành video. Số liệu:"
        " {source}",
    ],
    "ko": [
        "이 숫자, 예상하셨나요? 한국의 순위가 궁금한 통계가 있다면 댓글로 남겨 주세요. 영상으로 만들어 볼게요 👇",
        "영상에서 가장 의외였던 숫자는 무엇인가요? 👇 (출처: {source})",
        "한국과 비교해 보고 싶은 나라가 있나요? 댓글로 알려 주시면 다음 영상으로 만들어요. 출처: {source}",
    ],
}
LONG_TEMPLATES = {          # video dài hằng tuần (không có một nguồn duy nhất)
    "vi": "Tuần sau bạn muốn kênh làm chủ đề nào? Gợi ý trong bình luận 👇",
    "ko": "다음 주에는 어떤 주제를 다뤄 볼까요? 댓글로 알려 주세요 👇",
}


def text_for(video: dict, source: str = "") -> str:
    """Câu bình luận cho một video. Mẫu có {source} mà không biết nguồn thì dùng mẫu đầu (không có {source})."""
    code = lang.code()
    if not video.get("script_id"):
        return LONG_TEMPLATES[code]
    options = TEMPLATES[code]
    pick = options[int(video.get("id") or 0) % len(options)]
    if "{source}" in pick and not str(source or "").strip():
        pick = options[0]
    return pick.format(source=str(source or "").strip())


def _source_of(con, video: dict) -> str:
    if not video.get("script_id"):
        return ""
    row = con.execute("SELECT i.source_name FROM scripts s JOIN ideas i ON i.id = s.idea_id WHERE s.id = ?",
                      (video["script_id"],)).fetchone()
    return (row[0] if row else "") or ""


def post(con, video: dict, cfg: dict, poster=None) -> str:
    """Đăng bình luận đầu tiên cho video đã công khai. Trả về id bình luận, hoặc "" nếu không đăng (đã đăng rồi,
    tắt trong cấu hình, token thiếu quyền, lỗi — lỗi chỉ ghi log, không làm hỏng việc đăng video)."""
    from . import youtube, yt_quota
    if not cfg.get("publish", {}).get("youtube", {}).get("first_comment", False):
        return ""
    key = f"yt_comment_{video['id']}"
    if db.get_state(con, key) or not video.get("youtube_id"):
        return ""
    if poster is None:
        if not youtube.has_scope(youtube.FORCE_SSL):
            log.info("Bỏ qua bình luận đầu tiên video #%s: token chưa có quyền bình luận", video["id"])
            return ""
        poster = lambda vid, text: youtube.post_comment(vid, text, youtube.access_token())
    text = text_for(video, _source_of(con, video))
    try:
        yt_quota.spend("insert")
        cid = poster(video["youtube_id"], text)
    except Exception as exc:
        log.warning("Chưa đăng được bình luận đầu tiên video #%s: %s", video["id"], exc)
        return ""
    db.set_state(con, key, cid or "posted")
    log.info("Đã đăng bình luận đầu tiên video #%s: %s", video["id"], text)
    return cid or "posted"


def own_comment_ids(con) -> set:
    """Id các bình luận đầu tiên kênh đã đăng — agent Cộng đồng bỏ qua (không tự phân loại câu của chính mình)."""
    return {v for (v,) in con.execute("SELECT value FROM state WHERE key LIKE 'yt_comment_%'") if v}
