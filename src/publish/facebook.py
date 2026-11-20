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
NEEDED = ("pages_show_list", "pages_read_engagement", "pages_manage_posts")
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


def pick_page(pages: list, page_id: str = None) -> dict:
    """Chọn Trang để đăng: đúng page_id trong cấu hình, không thì Trang duy nhất Du quản lý.
    Trang phải cho phép tạo nội dung (task CREATE_CONTENT)."""
    if page_id:
        pages = [p for p in pages if str(p.get("id")) == str(page_id)]
    if not pages:
        raise FacebookAuthError("Token không quản lý Trang nào" + (f" có id {page_id}" if page_id else "")
                                + " — khi lấy token nhớ chọn Trang của kênh")
    if len(pages) > 1:
        names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in pages)
        raise FacebookAuthError(f"Token quản lý nhiều Trang: {names}. Ghi page_id của Trang kênh vào"
                                " config/channel.yaml (publish.facebook.page_id) rồi gửi lại")
    page = pages[0]
    tasks = page.get("tasks")
    if tasks is not None and "CREATE_CONTENT" not in tasks:
        raise FacebookAuthError(f"Tài khoản không có quyền đăng bài trên Trang {page.get('name')}")
    return page


def _save(page: dict, now: datetime = None) -> dict:
    tok = {"page_id": str(page["id"]), "page_name": page.get("name", ""),
           "page_token": page["access_token"],
           "obtained_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)          # Linux: chỉ chủ file đọc được
    except OSError:
        pass
    return tok


def connect(user_token: str, page_id: str = None) -> dict:
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
    tok = _save(pick_page(pages, page_id))
    return {"page_id": tok["page_id"], "page_name": tok["page_name"]}


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
