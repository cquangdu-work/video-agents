"""Agent CỘNG ĐỒNG (19/11/2026) — mỗi sáng đọc bình luận mới trên các video đã đăng, học từ khán giả:

1. Phân loại (model nhỏ, ép khuôn JSON, code soát lại): câu hỏi / đề xuất chủ đề / báo sai số liệu /
   khen / góp ý cách làm / khác.
2. BÁO SAI SỐ LIỆU -> đứng đầu bản tin gửi Du: uy tín của kênh "qua con số" là số liệu đúng.
3. CÂU HỎI -> nháp câu trả lời CHỈ từ bảng số của chính video đó (code soát: mọi con số trong câu trả
   lời phải có trong nguồn). Du tự đăng: token hiện tại không có quyền đăng bình luận (thêm quyền
   youtube.force-ssl phải hỏi Du — bình luận là nội dung công khai).
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

from . import db
from . import telegram_bot as tg

log = logging.getLogger("community")

KINDS = {"bao_loi": "⚠️ Báo SAI số liệu — kiểm tra lại giúp", "cau_hoi": "❓ Câu hỏi",
         "de_xuat": "💡 Đề xuất chủ đề", "che": "🛠 Góp ý cách làm", "khen": "👍 Khen", "khac": "Khác"}
MAX_NEW = 40              # mỗi lượt phân loại tối đa chừng này bình luận (một lần gọi model)
MAX_REPLIES = 6           # nháp trả lời tối đa chừng này câu hỏi mỗi lượt
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
                if text:
                    out.append({"id": item["id"], "youtube_id": v["youtube_id"], "video_id": v["id"],
                                "title": v.get("title") or "", "author": sn.get("authorDisplayName", ""),
                                "text": text[:1000], "published_at": sn.get("publishedAt", ""),
                                "likes": int(sn.get("likeCount") or 0)})
            page = data.get("nextPageToken")
            if stop or not page:
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
        description=f"""Kênh YouTube "{cfg['channel']['name']}" (video ngắn giải thích số liệu, tiếng Việt).
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
    answer = str(run(
        role="Người trả lời bình luận cho kênh video số liệu",
        goal="Trả lời đúng, ngắn, thân thiện, chỉ dựa trên số liệu có sẵn",
        description=f"""Video "{video.get('title', '')}" dựa trên số liệu sau:
\"\"\"
{data}
\"\"\"
Người xem hỏi: "{comment['text'][:500]}"

Viết câu trả lời tiếng Việt, tối đa 2 câu, thân thiện, xưng "kênh". CHỈ dùng con số có trong số liệu trên
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


def digest(items: list) -> str:
    """Bản tin cho Du: báo sai số liệu lên đầu, rồi câu hỏi (kèm nháp), đề xuất, góp ý; khen/khác chỉ đếm."""
    lines = [f"💬 Bình luận mới: {len(items)} — agent Cộng đồng"]
    for kind in ("bao_loi", "cau_hoi", "de_xuat", "che"):
        group = [c for c in items if c["kind"] == kind]
        if not group:
            continue
        lines += ["", f"{KINDS[kind]} ({len(group)}):"]
        for c in group[:10]:
            lines.append(f"• #{c['video_id']} {_link(c['youtube_id'])}\n  {c['author']}: “{c['text'][:220]}”")
            if kind == "bao_loi" and c.get("claim"):
                lines.append(f"  → cho là sai: {c['claim']}")
            if c.get("note"):
                lines.append(f"  → {c['note']}")
            if c.get("reply"):
                lines.append(f"  ✍️ Gợi ý trả lời: {c['reply']}")
    rest = {k: sum(1 for c in items if c["kind"] == k) for k in ("khen", "khac")}
    lines += ["", f"👍 Khen {rest['khen']} · khác {rest['khac']}",
              "Trả lời trong YouTube Studio / app (bot chưa có quyền đăng bình luận). Góp ý đúng thì dạy"
              " hệ thống: /hoc <luật> hoặc /nhac, /giong, /nhip, /chu."]
    return "\n".join(lines)


def run(cfg: dict, con, dry_run: bool = False, fetch=None, llm=None, send=None) -> list:
    """Một lượt: đọc -> phân loại -> nháp trả lời / xếp hàng chủ đề -> lưu -> gửi bản tin. Trả về
    danh sách bình luận mới đã xử lý."""
    from . import learning, topics
    # Đọc bằng API key: bình luận công khai. Token OAuth hiện có (youtube.readonly) KHÔNG đọc được bình
    # luận — commentThreads đòi youtube.force-ssl (đo 19/11: 403 insufficientPermissions), mà quyền đó
    # cũng cho đăng/xoá bình luận nên không xin khi Du chưa đồng ý.
    api_key = os.getenv("YOUTUBE_API_KEY")
    if fetch is None and not api_key:
        log.warning("Thiếu YOUTUBE_API_KEY — agent Cộng đồng cần nó để đọc bình luận công khai")
        return []
    videos = recent_videos(con, limit=int((cfg.get("community") or {}).get("max_videos", 30)))
    new = fetch_new(con, videos, None, api_key, fetch)[:MAX_NEW]
    if not new:
        log.info("Không có bình luận mới.")
        return []
    by_video = {v["id"]: v for v in videos}
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
                c["reply"] = f"Kênh đã có video về chủ đề này nè: {_link(done[0][1])}"
            elif not dry_run:
                status = topics.request(con, c["match"], c["topic"] or c["text"][:80], "viewer", c["text"])
                c["note"] = {"pending": "đã xếp hàng ưu tiên cho lượt săn ý tưởng kế tiếp",
                             "duplicate": "chủ đề này đã được xếp hàng gần đây",
                             "wish": "kênh chưa có nguồn số liệu — ghi vào danh sách mong muốn"}[status]
    text = digest(new)
    if dry_run:
        print(text)
        return new
    for c in new:
        con.execute("INSERT OR IGNORE INTO comments (id, youtube_id, video_id, author, text, published_at, likes,"
                    " kind, topic, matched, reply, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], c["youtube_id"], c["video_id"], c["author"], c["text"], c["published_at"],
                     c["likes"], c["kind"], c["topic"], c["match"], c.get("reply"), _now()))
        if c["kind"] in ("bao_loi", "che"):
            # người xem chê / báo sai là tín hiệu học — báo cáo tuần đếm; thành luật thì Du quyết (/hoc)
            learning.record(con, "viewer", c["kind"], c["text"][:400], "comment")
    con.commit()
    (send or tg.send_message)(text[:3900])
    return new


def weekly_lines(con, now: datetime = None) -> list:
    """Mục "💬 Cộng đồng" của báo cáo tuần."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).isoformat(timespec="seconds")
    rows = dict(con.execute("SELECT kind, COUNT(*) FROM comments WHERE fetched_at >= ? GROUP BY kind",
                            (since,)).fetchall())
    if not rows:
        return []
    short = {"bao_loi": "báo sai số liệu", "cau_hoi": "câu hỏi", "de_xuat": "đề xuất chủ đề",
             "che": "góp ý cách làm", "khen": "khen", "khac": "khác"}
    return ["", "💬 Cộng đồng (bình luận tuần này): "
            + " · ".join(f"{label} {rows[k]}" for k, label in short.items() if rows.get(k))]


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
