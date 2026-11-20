"""Đăng Reels lên Trang Facebook của kênh qua Graph API (Reels Publishing API) — chỉ dùng `requests`.

Vì sao Facebook (20/11/2026): Facebook là mạng xã hội lớn nhất Việt Nam (khán giả chính của kênh),
API đăng Reels miễn phí và đăng thẳng được (không cần app được Meta duyệt khi chỉ đăng lên Trang mà
chính Du quản lý), và chương trình Kiếm tiền từ nội dung của Facebook tính cả Reels (có Hàn Quốc —
nơi Du cư trú; theo lời mời, cần ~15 Reels/tháng trên ≥ 10 ngày — dây chuyền hằng ngày đủ).

Luồng đăng (3 bước theo tài liệu Meta):
  1. POST graph.facebook.com/<ver>/<page-id>/video_reels  upload_phase=start  -> video_id
  2. POST rupload.facebook.com/video-upload/<ver>/<video-id>  (gửi nguyên file, header offset/file_size)
  3. POST .../<page-id>/video_reels  upload_phase=finish, video_state=SCHEDULED|PUBLISHED|DRAFT
Vẫn chỉ chạy SAU khi Du bấm ✅ (src/review.py), giống YouTube.

Cấp quyền (một lần, không cần máy chủ web):
  Du tạo app trên developers.facebook.com (để chế độ Development — app chỉ dùng cho Trang của chính Du),
  chép App ID / App Secret vào .env (FACEBOOK_APP_ID, FACEBOOK_APP_SECRET), lấy User token ở Graph API
  Explorer với quyền pages_show_list, pages_read_engagement, pages_manage_posts rồi gửi bot
  "/facebook <token>". Bot đổi sang token dài hạn rồi lấy PAGE token — page token lấy từ user token dài
  hạn KHÔNG hết hạn (chỉ mất khi Du đổi mật khẩu / gỡ quyền app).

    python -m src.publish.facebook whoami     # token đang trỏ vào Trang nào
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN_PATH = ROOT / ".secrets" / "facebook_token.json"

VERSION = "v27.0"                       # bản Graph API trong ví dụ của tài liệu Reels (11/2026)
GRAPH = f"https://graph.facebook.com/{VERSION}"
RUPLOAD = f"https://rupload.facebook.com/video-upload/{VERSION}"
NEEDED = ("pages_show_list", "pages_read_engagement", "pages_manage_posts")      # bắt buộc: đăng Reels
# không bắt buộc — thiếu thì agent tương ứng tự nghỉ (agent Facebook, agent Cộng đồng):
OPTIONAL = {"read_insights": "đọc số liệu Reels + Trang",
            "pages_read_user_content": "đọc bình luận",
            "pages_manage_engagement": "đọc số liệu Reels + đăng trả lời bình luận (chỉ khi Du bấm ✅)",
            # kênh tiếng Hàn: đăng Reels lên tài khoản Instagram LIÊN KẾT với Trang (src/publish/instagram.py)
            "instagram_basic": "đọc tài khoản Instagram liên kết với Trang",
            "instagram_content_publish": "đăng Reels lên Instagram (chỉ sau khi Du bấm ✅)",
            "instagram_manage_insights": "đọc số liệu Reels Instagram (agent Instagram)"}
MAX_SECONDS = 90                        # Reels qua API: 3-90 giây
AUTH_CODES = {102, 190, 200, 10, 3}     # mã lỗi Graph API = thiếu quyền / token hỏng


class FacebookAuthError(RuntimeError):
    """Chưa kết nối / token mất hiệu lực / thiếu quyền — Du gửi lại /facebook <token>."""


class FacebookUploadError(RuntimeError):
    pass


def _check(r: requests.Response) -> dict:
    """Đọc trả lời Graph API; lỗi quyền -> FacebookAuthError, lỗi khác -> FacebookUploadError.
    Không bao giờ đưa URL vào lời báo lỗi (URL có thể chứa token)."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    if err or r.status_code >= 400:
        err = err or {}
        msg = f"Facebook lỗi {r.status_code}: {err.get('message') or r.text[:200]}"
        if err.get("code") in AUTH_CODES or err.get("type") == "OAuthException":
            raise FacebookAuthError(msg)
        raise FacebookUploadError(msg)
    return body


# ------------------------------------------------------------------ cấp quyền
def _app() -> tuple:
    app_id, secret = os.getenv("FACEBOOK_APP_ID"), os.getenv("FACEBOOK_APP_SECRET")
    if not app_id or not secret:
        raise FacebookAuthError("Thiếu FACEBOOK_APP_ID / FACEBOOK_APP_SECRET trong .env")
    return app_id, secret


def pick_page(pages: list, page_id: str = None, prefer_name: str = None) -> dict:
    """Chọn Trang để đăng: đúng page_id (FACEBOOK_PAGE_ID trong .env, hoặc publish.facebook.page_id), không thì Trang
    TRÙNG TÊN KÊNH (ca thật 21/11: token của Du quản lý 3 Trang, gồm cả Trang của hai kênh), không nữa thì Trang duy
    nhất. Trang phải cho phép tạo nội dung (task CREATE_CONTENT)."""
    if page_id:
        pages = [p for p in pages if str(p.get("id")) == str(page_id)]
    elif prefer_name and len(pages) > 1:
        same = [p for p in pages if " ".join(str(p.get("name", "")).split()).casefold()
                == " ".join(str(prefer_name).split()).casefold()]
        pages = same or pages
    if not pages:
        raise FacebookAuthError("Token không quản lý Trang nào" + (f" có id {page_id}" if page_id else "")
                                + " — khi lấy token nhớ chọn Trang của kênh")
    if len(pages) > 1:
        names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in pages)
        raise FacebookAuthError(f"Token quản lý nhiều Trang: {names}, không Trang nào trùng tên kênh. Ghi"
                                " FACEBOOK_PAGE_ID=<id Trang của kênh> vào .env trên VM rồi gửi lại")
    page = pages[0]
    tasks = page.get("tasks")
    if tasks is not None and "CREATE_CONTENT" not in tasks:
        raise FacebookAuthError(f"Tài khoản không có quyền đăng bài trên Trang {page.get('name')}")
    return page


def _save(page: dict, now: datetime = None, permissions=()) -> dict:
    tok = {"page_id": str(page["id"]), "page_name": page.get("name", ""),
           "page_token": page["access_token"], "permissions": sorted(permissions),
           "obtained_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)          # Linux: chỉ chủ file đọc được
    except OSError:
        pass
    return tok


def connect(user_token: str, page_id: str = None, prefer_name: str = None) -> dict:
    """User token ngắn hạn (Graph API Explorer) -> user token dài hạn -> page token không hết hạn, lưu lại.
    -> {"page_id", "page_name"}."""
    app_id, secret = _app()
    user_token = (user_token or "").strip()
    if len(user_token) < 20:
        raise FacebookAuthError("Token trống hoặc quá ngắn — chép nguyên ô Access Token ở Graph API Explorer")
    long_lived = _check(requests.get(f"{GRAPH}/oauth/access_token", timeout=30, params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret,
        "fb_exchange_token": user_token}))["access_token"]
    granted = _check(requests.get(f"{GRAPH}/me/permissions", timeout=30,
                                  params={"access_token": long_lived})).get("data", [])
    have = {p.get("permission") for p in granted if p.get("status") == "granted"}
    missing = [p for p in NEEDED if p not in have]
    if missing:
        raise FacebookAuthError("Token thiếu quyền: " + ", ".join(missing) + " — tích thêm ở Graph API Explorer")
    pages = _check(requests.get(f"{GRAPH}/me/accounts", timeout=30, params={
        "access_token": long_lived, "fields": "id,name,access_token,tasks"})).get("data", [])
    tok = _save(pick_page(pages, page_id or os.getenv("FACEBOOK_PAGE_ID"), prefer_name), permissions=have)
    return {"page_id": tok["page_id"], "page_name": tok["page_name"],
            "missing_optional": [p for p in OPTIONAL if p not in have]}


def _token() -> dict:
    try:
        tok = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        assert tok["page_id"] and tok["page_token"]
        return tok
    except (OSError, ValueError, KeyError, AssertionError):
        raise FacebookAuthError("Chưa kết nối Trang Facebook — gửi /facebook cho bot để xem cách kết nối")


def connected() -> bool:
    try:
        _token()
        return True
    except FacebookAuthError:
        return False


def can(permission: str) -> bool:
    """Token Trang đang lưu có quyền này không (kết nối trước 20/11 chưa ghi quyền -> False)."""
    try:
        return permission in (_token().get("permissions") or [])
    except FacebookAuthError:
        return False


def graph_get(path: str, get=None, **params) -> dict:
    """GET Graph API bằng token Trang. `get` để test thay requests.get."""
    tok = _token()
    return _check((get or requests.get)(f"{GRAPH}/{path.lstrip('/')}", timeout=60,
                                        params={**params, "access_token": tok["page_token"]}))


def page_id() -> str:
    return _token()["page_id"]


def whoami() -> dict:
    tok = _token()
    return _check(requests.get(f"{GRAPH}/{tok['page_id']}", timeout=30,
                               params={"access_token": tok["page_token"], "fields": "id,name,link,followers_count"}))


# ------------------------------------------------------------------ đăng Reels
def finish_params(description: str, state: str = "PUBLISHED", publish_at: int = None,
                  ai_generated: bool = True) -> dict:
    """Tham số bước 3. Tách riêng để test được mà không cần mạng."""
    state = (state or "PUBLISHED").upper()
    if state not in ("PUBLISHED", "SCHEDULED", "DRAFT"):
        raise ValueError(f"video_state không hợp lệ: {state}")
    p = {"upload_phase": "finish", "video_state": state, "description": description[:2200],
         "is_ai_generated": "true" if ai_generated else "false"}
    if state == "SCHEDULED":
        if not publish_at:
            raise ValueError("SCHEDULED cần giờ hẹn")
        now = time.time()
        if not (now + 600 < publish_at < now + 29 * 86400):     # Meta: hơn 10 phút, trong 29 ngày
            raise ValueError("Giờ hẹn Facebook phải cách hiện tại hơn 10 phút và trong 29 ngày")
        p["scheduled_publish_time"] = int(publish_at)
    return p


def upload_reel(path: Path, description: str, state: str = "PUBLISHED", publish_at: int = None,
                ai_generated: bool = True, wait_seconds: int = 120) -> dict:
    """Đăng một Reel lên Trang. -> {"video_id", "url", "state", "status"}."""
    path = Path(path)
    params = finish_params(description, state, publish_at, ai_generated)   # kiểm tham số TRƯỚC khi tải lên
    tok = _token()
    page, token = tok["page_id"], tok["page_token"]
    start = _check(requests.post(f"{GRAPH}/{page}/video_reels", timeout=60,
                                 json={"upload_phase": "start", "access_token": token}))
    video_id = str(start["video_id"])
    size = path.stat().st_size
    with open(path, "rb") as fh:
        up = _check(requests.post(f"{RUPLOAD}/{video_id}", data=fh, timeout=900, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream"}))
    if not up.get("success"):
        raise FacebookUploadError(f"Tải video lên Facebook không thành công: {up}")
    done = _check(requests.post(f"{GRAPH}/{page}/video_reels", timeout=60,
                                data={**params, "video_id": video_id, "access_token": token}))
    if not done.get("success", True):
        raise FacebookUploadError(f"Facebook không nhận lệnh đăng: {done}")
    status = wait_processed(video_id, token, wait_seconds)
    return {"video_id": video_id, "url": f"https://www.facebook.com/reel/{video_id}",
            "state": params["video_state"], "status": status}


def wait_processed(video_id: str, token: str, wait_seconds: int = 120) -> str:
    """Chờ Facebook xử lý xong (video_status: ready / processing...). Lỗi xử lý -> FacebookUploadError.
    Hết thời gian chờ thì trả trạng thái hiện tại — Facebook vẫn tự xử lý tiếp."""
    deadline, status = time.time() + wait_seconds, "processing"
    while True:
        st = _check(requests.get(f"{GRAPH}/{video_id}", timeout=30,
                                 params={"fields": "status", "access_token": token})).get("status") or {}
        status = st.get("video_status", status)
        for phase in ("uploading_phase", "processing_phase", "publishing_phase"):
            if (st.get(phase) or {}).get("status") == "error":
                err = (st.get(phase) or {}).get("errors") or (st.get(phase) or {}).get("error")
                raise FacebookUploadError(f"Facebook xử lý video lỗi ({phase}): {err}")
        if status in ("error", "upload_failed", "expired"):
            raise FacebookUploadError(f"Facebook xử lý video lỗi: {status}")
        if status == "ready" or time.time() >= deadline:
            return status
        time.sleep(6)


# ------------------------------------------------------------------ bài viết ảnh (src/fb_post.py)
def post_photo(image: Path, message: str, publish_at: int = None, post=None) -> dict:
    """Đăng một bài ẢNH + chữ lên Trang. Có publish_at (Unix, cách hiện tại 10 phút - 30 ngày) thì HẸN GIỜ theo đúng
    quy trình tài liệu Meta: tải ảnh lên dạng tạm (published=false, temporary=true), rồi tạo bài trên /feed gắn ảnh đó
    (attached_media) với scheduled_publish_time. -> {"id": id bài, "scheduled": bool}."""
    post = post or requests.post
    tok = _token()
    page, token = tok["page_id"], tok["page_token"]
    if publish_at:
        now = time.time()
        if not (now + 600 < publish_at < now + 30 * 86400):
            raise ValueError("Giờ hẹn bài viết Facebook phải cách hiện tại hơn 10 phút và trong 30 ngày")
    with open(image, "rb") as fh:
        data = ({"published": "false", "temporary": "true"} if publish_at
                else {"caption": message, "published": "true"})
        photo = _check(post(f"{GRAPH}/{page}/photos", timeout=120, files={"source": (Path(image).name, fh)},
                            data={**data, "access_token": token}))
    if not publish_at:
        return {"id": str(photo.get("post_id") or photo.get("id")), "scheduled": False}
    body = _check(post(f"{GRAPH}/{page}/feed", timeout=60, data={
        "message": message, "attached_media": json.dumps([{"media_fbid": str(photo["id"])}]),
        "published": "false", "scheduled_publish_time": int(publish_at), "unpublished_content_type": "SCHEDULED",
        "access_token": token}))
    return {"id": str(body.get("id")), "scheduled": True}


def post_engagement(post_id: str, get=None) -> dict:
    """Cảm xúc / bình luận / chia sẻ của một bài viết (agent Facebook, báo cáo tuần). Thiếu trường nào -> 0."""
    body = graph_get(post_id, get, fields="shares,reactions.summary(total_count).limit(0),"
                                          "comments.summary(total_count).limit(0)")
    total = lambda k: int(((body.get(k) or {}).get("summary") or {}).get("total_count") or 0)
    return {"reactions": total("reactions"), "comments": total("comments"),
            "shares": int((body.get("shares") or {}).get("count") or 0)}


# ------------------------------------------------------------------ đọc số liệu / bình luận
REEL_METRICS = ("blue_reels_play_count", "post_impressions_unique", "post_video_avg_time_watched",
                "post_video_view_time", "post_video_followers", "post_video_likes_by_reaction_type",
                "post_video_social_actions", "post_video_retention_graph")


def _value(v):
    """Giá trị một chỉ số: số, hoặc dict (theo loại cảm xúc / mốc thời gian) -> giữ nguyên."""
    if isinstance(v, dict):
        return {str(k): float(x) for k, x in v.items() if isinstance(x, (int, float))}
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def reel_insights(video_id: str, get=None) -> dict:
    """Số liệu trọn đời của một Reel (GET /{video-id}/video_insights, quyền read_insights +
    pages_manage_engagement). -> {tên chỉ số: giá trị}; chỉ số nào Facebook không trả thì vắng mặt."""
    body = graph_get(f"{video_id}/video_insights", get, metric=",".join(REEL_METRICS))
    out = {}
    for item in body.get("data") or []:
        vals = item.get("values") or []
        if item.get("name") and vals:
            out[item["name"]] = _value(vals[-1].get("value"))
    return out


def page_insights(get=None) -> dict:
    """Số liệu cả Trang: người theo dõi (trường followers_count) + 28 ngày gần nhất (lượt theo dõi mới / bỏ
    theo dõi, lượt xem nội dung, người xem). Chỉ số Meta đã bỏ (page_fans, page_impressions...) không dùng.
    Trang dưới 100 lượt thích thì Meta chưa trả insights -> chỉ có followers_count."""
    pid = page_id()
    out = {}
    info = graph_get(pid, get, fields="followers_count,fan_count,name")
    out["followers"] = info.get("followers_count")
    out["name"] = info.get("name")
    for metric in ("page_daily_follows_unique", "page_daily_unfollows_unique", "page_media_view",
                   "page_total_media_view_unique", "page_video_views"):
        try:
            body = graph_get(f"{pid}/insights", get, metric=metric, period="days_28")
            vals = ((body.get("data") or [{}])[0].get("values") or [])
            if vals:
                out[metric] = _value(vals[-1].get("value"))
        except (FacebookAuthError, FacebookUploadError) as exc:
            log.info("Không đọc được %s: %s", metric, str(exc)[:120])
    return out


def comments(video_id: str, after: str = None, get=None) -> dict:
    """Bình luận gốc của một Reel, mới nhất trước. -> {"data": [...], "next": con trỏ trang sau | None}."""
    params = {"fields": "id,message,from{name},created_time,like_count", "filter": "toplevel",
              "order": "reverse_chronological", "limit": 100}
    if after:
        params["after"] = after
    body = graph_get(f"{video_id}/comments", get, **params)
    paging = body.get("paging") or {}
    return {"data": body.get("data") or [],
            "next": (paging.get("cursors") or {}).get("after") if paging.get("next") else None}


def reply_comment(comment_id: str, message: str, post=None) -> str:
    """Trang trả lời một bình luận. CHỈ gọi từ nút ✅ của Du (src/community.post_reply). -> id câu trả lời."""
    tok = _token()
    body = _check((post or requests.post)(f"{GRAPH}/{comment_id}/comments", timeout=60,
                                          data={"message": message, "access_token": tok["page_token"]}))
    return str(body.get("id") or "")


def caption(video: dict) -> str:
    """Chú thích Reel = tiêu đề + mô tả YouTube, bỏ hashtag riêng của YouTube (#Shorts)."""
    desc = str(video.get("description") or "")
    lines = []
    for line in desc.splitlines():
        if line.strip().startswith("#"):
            line = " ".join(w for w in line.split() if w.lower() != "#shorts")
        lines.append(line)
    body = "\n".join(lines).strip()
    return "\n\n".join(x for x in ((video.get("title") or "").strip(), body) if x)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="Kiểm tra kết nối Trang Facebook")
    ap.add_argument("cmd", choices=["whoami"])
    ap.parse_args()
    try:
        print(whoami())
    except (FacebookAuthError, FacebookUploadError) as exc:
        sys.exit(f"LỖI: {exc}")


if __name__ == "__main__":
    main()
