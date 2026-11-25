"""Agent CỘNG ĐỒNG (19/11/2026) — mỗi sáng đọc bình luận mới trên các video đã đăng, học từ khán giả:

1. Phân loại (model nhỏ, ép khuôn JSON, code soát lại): câu hỏi / đề xuất chủ đề / báo sai số liệu /
   khen / góp ý cách làm / khác.
2. BÁO SAI SỐ LIỆU -> đứng đầu bản tin gửi Du: uy tín của kênh "qua con số" là số liệu đúng.
3. CÂU HỎI -> nháp câu trả lời CHỈ từ bảng số của chính video đó (code soát: mọi con số trong câu trả
   lời phải có trong nguồn). Mỗi bình luận cần xử lý thành MỘT tin Telegram có nút ✅ Đăng / ❌ Bỏ: chỉ
   khi Du bấm ✅ kênh mới đăng (Du đồng ý 19/11 thêm quyền youtube.force-ssl cho việc này). Du trả lời tin
   bằng câu khác -> thành nháp mới, bot hỏi lại trước khi đăng.
4. ĐỀ XUẤT CHỦ ĐỀ -> model chọn chỉ số khớp trong danh mục kênh đang có (code kiểm khoá có thật):
   đã có video về nó -> nháp trả lời kèm link; chưa có -> xếp hàng ưu tiên (src/topics.py) cho lượt
   Săn ý tưởng kế tiếp; không có nguồn -> danh sách mong muốn trong báo cáo tuần.
5. GÓP Ý CÁCH LÀM (giọng, nhạc, chữ...) -> vào bản tin; Du thấy đúng thì dạy hệ thống bằng /hoc hoặc
   chỉnh cách dựng bằng /nhac, /giong, /nhip, /chu.

    python -m src.community            # một lượt (daily gọi mỗi sáng, cấu hình community.enabled)
    python -m src.community --dry-run  # đọc + phân loại + in ra, không ghi DB, không gửi Telegram
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from . import db, lang
from . import telegram_bot as tg

log = logging.getLogger("community")

KINDS = {"bao_loi": "⚠️ Báo SAI số liệu — kiểm tra lại giúp", "cau_hoi": "❓ Câu hỏi",
         "de_xuat": "💡 Đề xuất chủ đề", "che": "🛠 Góp ý cách làm", "khen": "👍 Khen", "khac": "Khác"}
SHORT = {"bao_loi": "báo sai số liệu", "cau_hoi": "câu hỏi", "de_xuat": "đề xuất chủ đề",
         "che": "góp ý cách làm", "khen": "khen", "khac": "khác"}
CARD_KINDS = ("bao_loi", "cau_hoi", "de_xuat", "che")   # loại cần Du xem — mỗi bình luận một tin có nút
MAX_NEW = 40              # mỗi lượt phân loại tối đa chừng này bình luận (một lần gọi model)
MAX_REPLIES = 6           # nháp trả lời tối đa chừng này câu hỏi mỗi lượt
MAX_CARDS = 8             # gửi riêng tối đa chừng này bình luận mỗi sáng (còn lại: xem trong YouTube Studio)
NO_ANSWER = "KHONG_DU_SO_LIEU"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def recent_videos(con, days: int = 60, limit: int = 30) -> list:
    """Video đã đăng gần đây (có youtube_id) kèm bảng số / tóm tắt của ý tưởng — để trả lời câu hỏi."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        "SELECT v.id, v.youtube_id, v.title, i.summary, i.source_url FROM videos v"
        " LEFT JOIN scripts s ON s.id = v.script_id LEFT JOIN ideas i ON i.id = s.idea_id"
        " WHERE v.status = 'published' AND v.youtube_id IS NOT NULL"
        " AND COALESCE(v.published_at, v.created_at) >= ? ORDER BY v.id DESC LIMIT ?", (since, limit)).fetchall()
    return [dict(r) for r in rows]


def fetch_new(con, videos: list, token: str = None, api_key: str = None, fetch=None) -> list:
    """Bình luận gốc CHƯA thấy bao giờ của các video. Đọc từ mới tới cũ, gặp bình luận đã lưu thì dừng."""
    from .publish import youtube
    fetch = fetch or youtube.comment_threads
    from .publish.first_comment import own_comment_ids
    own = own_comment_ids(con)            # bình luận đầu tiên do chính kênh đăng: không tự phân loại câu của mình
    out = []
    for v in videos:
        page = None
        for _ in range(5):                                    # tối đa 500 bình luận mỗi video mỗi lượt
            try:
                data = fetch(v["youtube_id"], token=token, api_key=api_key, page_token=page)
            except Exception as exc:          # video còn riêng tư / bị gỡ: bỏ qua video đó, không hỏng cả lượt
                log.info("Không đọc được bình luận video #%s: %s", v["id"], str(exc)[:120])
                break
            stop = False
            for item in data.get("items") or []:
                if con.execute("SELECT 1 FROM comments WHERE id = ?", (item["id"],)).fetchone():
                    stop = True
                    break
                sn = ((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
                text = str(sn.get("textOriginal") or sn.get("textDisplay") or "").strip()
                if text and item["id"] not in own:
                    out.append({"id": item["id"], "youtube_id": v["youtube_id"], "video_id": v["id"],
                                "title": v.get("title") or "", "author": sn.get("authorDisplayName", ""),
                                "text": text[:1000], "published_at": sn.get("publishedAt", ""),
                                "likes": int(sn.get("likeCount") or 0)})
            page = data.get("nextPageToken")
            if stop or not page:
                break
    return out


def recent_reels(con, days: int = 60, limit: int = 30) -> list:
    """Reel Facebook đã công khai gần đây kèm bảng số của ý tưởng (cùng khuôn recent_videos)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        "SELECT v.id, v.facebook_id, v.title, i.summary, i.source_url FROM videos v"
        " LEFT JOIN scripts s ON s.id = v.script_id LEFT JOIN ideas i ON i.id = s.idea_id"
        " WHERE v.facebook_id IS NOT NULL AND v.facebook_at >= ? AND v.facebook_at <= ?"
        " ORDER BY v.id DESC LIMIT ?", (since, now, limit)).fetchall()
    return [dict(r) for r in rows]


def fetch_new_fb(con, reels: list, fetch=None) -> list:
    """Bình luận gốc mới trên các Reel Facebook (Graph API, token Trang). Gặp bình luận đã lưu thì dừng."""
    from .publish import facebook
    fetch = fetch or (lambda fb_id, after: facebook.comments(fb_id, after))
    out = []
    for v in reels:
        after = None
        for _ in range(5):
            try:
                data = fetch(v["facebook_id"], after)
            except Exception as exc:
                log.info("Không đọc được bình luận Facebook của video #%s: %s", v["id"], str(exc)[:120])
                break
            stop = False
            for item in data.get("data") or []:
                if con.execute("SELECT 1 FROM comments WHERE id = ?", (item.get("id"),)).fetchone():
                    stop = True
                    break
                text = str(item.get("message") or "").strip()
                if item.get("id") and text:
                    out.append({"id": item["id"], "youtube_id": None, "video_id": v["id"], "platform": "facebook",
                                "link": f"https://www.facebook.com/reel/{v['facebook_id']}",
                                "title": v.get("title") or "", "author": (item.get("from") or {}).get("name", ""),
                                "text": text[:1000], "published_at": item.get("created_time", ""),
                                "likes": int(item.get("like_count") or 0)})
            after = data.get("next")
            if stop or not after:
                break
    return out


def classify(comments: list, cfg: dict, run=None) -> list:
    """[{kind, topic, match, claim}] cùng thứ tự `comments`. Model chỉ đề xuất; code ép loại về danh sách
    cố định và chỉ nhận khoá chủ đề có thật trong danh mục (src/topics.catalog)."""
    from . import topics
    from .utils import extract_json
    if not comments:
        return []
    if run is None:
        from .crew import _run_single_task as run
    cat = topics.catalog(cfg)
    listing = "\n".join(f"{k + 1}. [video: {c['title'][:70]}] {c['text'][:400]}" for k, c in enumerate(comments))
    menu = "\n".join(f"{key} — {name}" for key, name in cat.items())
    answer = run(
        role="Trợ lý cộng đồng của kênh video ngắn giải thích số liệu",
        goal="Phân loại bình luận đúng, không suy diễn",
        description=f"""Kênh YouTube "{cfg['channel']['name']}" (video ngắn giải thích số liệu, {lang.locale()['name']}).
Phân loại TỪNG bình luận dưới đây vào đúng một loại:
- "cau_hoi": hỏi một điều về nội dung / số liệu của video (cần trả lời)
- "de_xuat": muốn kênh làm video về một chủ đề
- "bao_loi": cho rằng một con số / thông tin trong video SAI
- "khen": khen, cảm ơn
- "che": góp ý cách làm video (giọng đọc, nhạc, chữ, độ dài, hình...)
- "khac": còn lại (chào hỏi, quảng cáo, tranh cãi ngoài lề...)
Với "de_xuat": "topic" = chủ đề ngắn gọn; "match" = KHOÁ của chỉ số trong DANH MỤC dưới đây nếu chỉ số đó
trả lời ĐÚNG điều người xem muốn — không chắc thì null (đừng gán gần đúng).
Với "bao_loi": "claim" = điều người xem cho là sai.

DANH MỤC CHỈ SỐ KÊNH ĐANG CÓ NGUỒN:
{menu}

BÌNH LUẬN:
{listing}""",
        expected_output='JSON array: [{"i": 1, "kind": "cau_hoi|de_xuat|bao_loi|khen|che|khac", '
                        '"topic": "...", "match": null, "claim": "..."}]')
    try:
        data = extract_json(answer)
    except ValueError:
        data = []
    if isinstance(data, dict):                     # model dự phòng hay gói mảng trong object
        data = next((v for v in data.values() if isinstance(v, list)), [])
    out = [{"kind": "khac", "topic": "", "match": None, "claim": ""} for _ in comments]
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            k = int(d.get("i")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= k < len(comments):
            continue
        kind = d.get("kind") if d.get("kind") in KINDS else "khac"
        match = d.get("match") if d.get("match") in cat else None
        out[k] = {"kind": kind, "topic": str(d.get("topic") or "")[:120],
                  "match": match if kind == "de_xuat" else None, "claim": str(d.get("claim") or "")[:200]}
    return out


def draft_reply(comment: dict, video: dict, cfg: dict, run=None):
    """Nháp trả lời một câu hỏi CHỈ bằng số liệu của video. Con số nào không có trong nguồn (hoặc chính
    câu hỏi) -> bỏ nháp, để Du tự trả lời. Trả về chuỗi hoặc None."""
    from .utils import digit_set
    if run is None:
        from .crew import _run_single_task as run
    data = str(video.get("summary") or "")[:2500]
    if not data.strip():
        return None
    reply_lang = lang.pick(vi='tiếng Việt, xưng "kênh"',
                           ko='TIẾNG HÀN lịch sự (해요체), xưng "저희 채널"; số viết kiểu Hàn đúng như trong số liệu')
    answer = str(run(
        role="Người trả lời bình luận cho kênh video số liệu",
        goal="Trả lời đúng, ngắn, thân thiện, chỉ dựa trên số liệu có sẵn",
        description=f"""Video "{video.get('title', '')}" dựa trên số liệu sau:
\"\"\"
{data}
\"\"\"
Người xem hỏi: "{comment['text'][:500]}"

Viết câu trả lời {reply_lang}, tối đa 2 câu, thân thiện. CHỈ dùng con số có trong số liệu trên
(viết bằng chữ số), không đoán, không khuyên ai làm gì. Số liệu trên không trả lời được câu hỏi thì trả về
đúng chữ {NO_ANSWER}.""",
        expected_output="Một đoạn văn ngắn, không markdown") or "").strip().strip('"')
    if not answer or NO_ANSWER in answer.upper().replace(" ", "_") or len(answer) > 600:
        return None
    allowed = digit_set(data + " " + str(video.get("title") or "") + " " + comment["text"])
    if not digit_set(answer) <= allowed:
        log.info("Bỏ nháp trả lời bình luận %s: có số không nằm trong nguồn", comment["id"])
        return None
    return answer


def _link(youtube_id: str) -> str:
    return f"https://youtube.com/shorts/{youtube_id}"


def digest(items: list, can_post: bool, carded: int) -> str:
    """Tin TÓM TẮT gửi trước; từng bình luận cần xử lý đi theo sau thành tin riêng có nút (card_text)."""
    counts = {k: sum(1 for c in items if c["kind"] == k) for k in SHORT}
    lines = [f"💬 {len(items)} bình luận mới — agent Cộng đồng: "
             + " · ".join(f"{SHORT[k]} {n}" for k, n in counts.items() if n)]
    if carded:
        lines.append(f"{carded} bình luận cần xử lý gửi riêng bên dưới (báo sai số liệu trước).")
    extra = sum(counts[k] for k in CARD_KINDS) - carded
    if extra > 0:
        lines.append(f"Còn {extra} bình luận cần xem nữa — mở YouTube Studio.")
    if not can_post:
        lines.append("🔑 Bot chưa có quyền đăng trả lời: gửi /capquyen một lần (tích cả quyền quản lý bình"
                     " luận). Trước đó Du trả lời tay trong YouTube Studio.")
    lines.append("Góp ý đúng thì dạy hệ thống: /hoc <luật> hoặc /nhac, /giong, /nhip, /chu.")
    return "\n".join(lines)


def card_text(c: dict) -> str:
    """Tin riêng cho MỘT bình luận: nội dung, ghi chú của agent, nháp trả lời (nếu có)."""
    where = ("📘 Facebook " + str(c.get("link") or "") if c.get("platform") == "facebook"
             else _link(c["youtube_id"]))
    lines = [f"{KINDS.get(c['kind'], c['kind'])} — video #{c['video_id']} {where}",
             f"{c['author']}: “{str(c['text'])[:300]}”"]
    if c["kind"] == "bao_loi" and c.get("claim"):
        lines.append(f"→ cho là sai: {c['claim']}")
    if c.get("note"):
        lines.append(f"→ {c['note']}")
    if c.get("text_vi"):                      # kênh tiếng Hàn: bản dịch để Du hiểu (dịch máy)
        lines.append(f"🇻🇳 {c['text_vi']}")
    if c.get("reply"):
        lines += [f"✍️ Nháp trả lời: {c['reply']}"] + ([f"🇻🇳 {c['reply_vi']}"] if c.get("reply_vi") else []) + [
                  "Bấm ✅ để kênh đăng câu này, hoặc TRẢ LỜI tin này bằng câu khác để sửa nháp."]
    else:
        lines.append("Muốn trả lời: TRẢ LỜI tin này bằng câu Du muốn đăng (bot hỏi lại trước khi đăng).")
    return "\n".join(lines)


def translate_cards(cards: list, llm=None) -> None:
    """Kênh không phải tiếng Việt: dịch bình luận + nháp trả lời sang tiếng Việt cho Du (MỘT lần gọi model cho cả
    mẻ). Lỗi thì thôi — thẻ vẫn gửi, chỉ thiếu bản dịch."""
    import re
    from .crew import translate_for_review
    lines, where = [], []
    for k, c in enumerate(cards):
        lines.append(str(c.get("text") or "")[:300]); where.append((k, "text_vi"))
        if c.get("reply"):
            lines.append(str(c["reply"])); where.append((k, "reply_vi"))
    try:
        out = translate_for_review(lines, run=llm)
    except Exception as exc:
        log.warning("Không dịch được bình luận: %s", exc)
        return
    for m in re.finditer(r"(?m)^\s*(\d+)[.)]\s*(.+)$", str(out or "")):
        i = int(m.group(1)) - 1
        if 0 <= i < len(where):
            k, field = where[i]
            cards[k][field] = m.group(2).strip()[:400]


def card_buttons(c: dict) -> list:
    row = [("✅ Đăng trả lời", f"cok:{c['id']}")] if c.get("reply") else []
    return [row + [("❌ Bỏ qua", f"cno:{c['id']}")]]


def set_draft(con, comment_id: str, text: str) -> dict:
    """Du trả lời tin của một bình luận bằng câu của mình -> thành nháp mới, CHỜ Du bấm ✅ (không đăng
    thẳng: Du trả lời "ok" để ghi nhận cũng không bị đăng lên YouTube)."""
    con.execute("UPDATE comments SET reply = ?, status = 'new' WHERE id = ? AND COALESCE(status, '') != 'posted'",
                (" ".join(str(text or "").split())[:1000], comment_id))
    con.commit()
    return dict(con.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone())


def post_reply(con, comment_id: str) -> str:
    """Đăng nháp đã được duyệt. CHỈ gọi từ nút ✅ của Du (src/review.py). Mỗi bình luận đăng đúng MỘT lần:
    chuyển trạng thái new -> posting một cách nguyên tử; lỗi thì trả về new để Du bấm lại."""
    from .publish import youtube
    row = con.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not row:
        raise ValueError("không tìm thấy bình luận này")
    if not row["reply"]:
        raise ValueError("chưa có nháp trả lời — trả lời tin bằng câu Du muốn đăng")
    cur = con.execute("UPDATE comments SET status = 'posting' WHERE id = ? AND status = 'new'", (comment_id,))
    con.commit()
    if cur.rowcount != 1:
        raise ValueError(f"bình luận này đã xử lý rồi ({row['status']})")
    try:
        if (row["platform"] or "youtube") == "facebook":       # bình luận trên Reel của Trang
            from .publish import facebook
            posted = facebook.reply_comment(comment_id, row["reply"])
        else:
            posted = youtube.reply_comment(comment_id, row["reply"], youtube.access_token())
    except Exception:
        con.execute("UPDATE comments SET status = 'new' WHERE id = ?", (comment_id,))
        con.commit()
        raise
    con.execute("UPDATE comments SET status = 'posted', posted_id = ?, posted_at = ? WHERE id = ?",
                (posted, _now(), comment_id))
    con.commit()
    return posted


def run(cfg: dict, con, dry_run: bool = False, fetch=None, llm=None, send=None, fb_fetch=None) -> list:
    """Một lượt: đọc (YouTube + Reels Facebook) -> phân loại -> nháp trả lời / xếp hàng chủ đề -> lưu -> gửi
    bản tin. Trả về danh sách bình luận mới đã xử lý."""
    from . import learning, topics
    from .publish import facebook
    # Đọc bằng API key: bình luận công khai. Token OAuth hiện có (youtube.readonly) KHÔNG đọc được bình
    # luận — commentThreads đòi youtube.force-ssl (đo 19/11: 403 insufficientPermissions), mà quyền đó
    # cũng cho đăng/xoá bình luận nên không xin khi Du chưa đồng ý.
    api_key = os.getenv("YOUTUBE_API_KEY")
    limit = int((cfg.get("community") or {}).get("max_videos", 30))
    videos, new = [], []
    if fetch is None and not api_key:
        log.warning("Thiếu YOUTUBE_API_KEY — agent Cộng đồng không đọc được bình luận YouTube")
    else:
        videos = recent_videos(con, limit=limit)
        new = fetch_new(con, videos, None, api_key, fetch)
    reels = []
    if fb_fetch is not None or facebook.connected():          # Trang Facebook (src/publish/facebook.py)
        reels = recent_reels(con, limit=limit)
        new += fetch_new_fb(con, reels, fb_fetch)
    new = new[:MAX_NEW]
    if not new:
        log.info("Không có bình luận mới.")
        return []
    by_video = {v["id"]: v for v in reels + videos}
    for c, verdict in zip(new, classify(new, cfg, llm)):
        c.update(verdict)
    replies = 0
    for c in new:
        if c["kind"] == "cau_hoi" and replies < MAX_REPLIES:
            replies += 1
            try:
                c["reply"] = draft_reply(c, by_video.get(c["video_id"], {}), cfg, llm)
            except Exception as exc:
                log.warning("Không nháp được trả lời cho %s: %s", c["id"], exc)
            if not c.get("reply"):
                c["note"] = "câu hỏi ngoài số liệu của video — Du trả lời giúp"
        elif c["kind"] == "de_xuat":
            done = topics.covered(con, c["match"]) if c["match"] else []
            if done:
                c["reply"] = lang.pick(vi=f"Kênh đã có video về chủ đề này nè: {_link(done[0][1])}",
                                       ko=f"이 주제는 저희 채널에 이미 영상이 있어요: {_link(done[0][1])}")
            elif not dry_run:
                status = topics.request(con, c["match"], c["topic"] or c["text"][:80], "viewer", c["text"])
                c["note"] = {"pending": "đã xếp hàng ưu tiên cho lượt săn ý tưởng kế tiếp",
                             "duplicate": "chủ đề này đã được xếp hàng gần đây",
                             "wish": "kênh chưa có nguồn số liệu — ghi vào danh sách mong muốn"}[status]
    from .publish import youtube
    cards = sorted([c for c in new if c["kind"] in CARD_KINDS], key=lambda c: CARD_KINDS.index(c["kind"]))
    cards = cards[:MAX_CARDS]
    if lang.code() != "vi" and cards:
        translate_cards(cards, llm)
    text = digest(new, youtube.has_scope(youtube.FORCE_SSL), len(cards))
    if any(c.get("platform") == "facebook" for c in new) and not facebook.can("pages_manage_engagement"):
        text += ("\n🔑 Trang Facebook chưa có quyền pages_manage_engagement: bot chưa đăng được trả lời trên Reels"
                 " — gửi /facebook để xem cách cấp thêm. Trước đó Du trả lời tay trên Facebook.")
    if dry_run:
        print("\n\n".join([text] + [card_text(c) for c in cards]))
        return new
    for c in new:
        con.execute("INSERT OR IGNORE INTO comments (id, youtube_id, video_id, author, text, published_at, likes,"
                    " kind, topic, matched, reply, fetched_at, status, platform, link)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], c["youtube_id"], c["video_id"], c["author"], c["text"], c["published_at"],
                     c["likes"], c["kind"], c["topic"], c["match"], c.get("reply"), _now(),
                     "new" if c["kind"] in CARD_KINDS else "done", c.get("platform", "youtube"), c.get("link")))
        if c["kind"] in ("bao_loi", "che"):
            # người xem chê / báo sai là tín hiệu học — báo cáo tuần đếm; thành luật thì Du quyết (/hoc)
            learning.record(con, "viewer", c["kind"], c["text"][:400], "comment")
    con.commit()
    send = send or tg.send_message
    send(text[:3900])
    for c in cards:                         # mỗi bình luận một tin có nút: Du duyệt TỪNG câu trước khi đăng
        mid = send(card_text(c)[:3900], buttons=card_buttons(c))
        if mid:
            con.execute("UPDATE comments SET tg_message_id = ? WHERE id = ?", (mid, c["id"]))
    con.commit()
    return new


def weekly_lines(con, now: datetime = None) -> list:
    """Mục "💬 Cộng đồng" của báo cáo tuần."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat(timespec="seconds")
    rows = dict(con.execute("SELECT kind, COUNT(*) FROM comments WHERE fetched_at >= ? GROUP BY kind",
                            (since,)).fetchall())
    if not rows:
        return []
    posted = con.execute("SELECT COUNT(*) FROM comments WHERE posted_at >= ?", (since,)).fetchone()[0]
    return ["", "💬 Cộng đồng (bình luận tuần này): "
            + " · ".join(f"{label} {rows[k]}" for k, label in SHORT.items() if rows.get(k))
            + (f" — kênh đã trả lời {posted} (Du duyệt từng câu)" if posted else "")]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Agent Cộng đồng: đọc và phân loại bình luận")
    ap.add_argument("--dry-run", action="store_true", help="Không ghi DB, không gửi Telegram")
    args = ap.parse_args()
    from .main import load_config
    con = db.connect()
    try:
        got = run(load_config(), con, dry_run=args.dry_run)
        print(f"Đã xử lý {len(got)} bình luận mới.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
