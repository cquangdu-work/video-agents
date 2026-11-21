"""Đăng Reels lên INSTAGRAM (kênh tiếng Hàn 숫자세계, Du xin 20/11/2026) — chỉ sau khi Du bấm ✅.

Vì sao đi đường "Facebook Login" (tài khoản Instagram chuyên nghiệp LIÊN KẾT với một Trang Facebook): đọc tài liệu
Meta 20/11/2026 — đường "Instagram Login" (graph.instagram.com) CHỈ nhận video ở một địa chỉ web công khai
(video_url), không tải file lên được, mà VM không công khai file; tải thẳng file (resumable upload qua
rupload.facebook.com) chỉ có ở đường Facebook Login. Đường này dùng lại TOKEN TRANG của src/publish/facebook.py
(gửi "/facebook <token>" cho bot của kênh Hàn, tích thêm instagram_basic + instagram_content_publish) — Trang chỉ để
liên kết, kênh Hàn không đăng gì lên Trang đó.

Luồng (tài liệu Meta, Graph API v27):
  1. POST graph.facebook.com/<ver>/<ig-user-id>/media  media_type=REELS, upload_type=resumable, caption,
     share_to_feed, is_ai_generated  -> id "hộp chứa" (container), sống 24 giờ
  2. POST rupload.facebook.com/ig-api-upload/<ver>/<container-id>  (gửi nguyên file; header offset, file_size)
  3. GET  /<container-id>?fields=status_code  tới khi FINISHED (ERROR / EXPIRED -> lỗi)
  4. POST /<ig-user-id>/media_publish  creation_id=<container-id>  -> id bài
API KHÔNG hẹn giờ được -> bot tự đăng đúng giờ (review.publish_instagram_due, chạy trong vòng lặp của bot duyệt).
Giới hạn 100 bài/24 giờ — kênh đăng 1 video/ngày.
"""
import logging
import time
from pathlib import Path

import requests

from . import facebook

log = logging.getLogger(__name__)

RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{facebook.VERSION}"
NEEDED = ("instagram_basic", "instagram_content_publish")
MAX_SECONDS = 15 * 60                  # Reels qua API: 3 giây - 15 phút, tối đa 300 MB


class InstagramError(RuntimeError):
    pass


def ready() -> bool:
    """Đã kết nối Trang (token Trang) với đủ quyền Instagram."""
    return facebook.connected() and all(facebook.can(p) for p in NEEDED)


def account(get=None) -> dict:
    """Tài khoản Instagram chuyên nghiệp liên kết với Trang -> {"id", "username"}. Chưa liên kết -> InstagramError."""
    body = facebook.graph_get(facebook.page_id(), get, fields="instagram_business_account{id,username}")
    acc = body.get("instagram_business_account") or {}
    if not acc.get("id"):
        raise InstagramError("Trang Facebook chưa liên kết tài khoản Instagram chuyên nghiệp — vào Instagram: Cài đặt"
                             " → Tài khoản → chuyển sang tài khoản Chuyên nghiệp, rồi liên kết với Trang")
    return {"id": str(acc["id"]), "username": acc.get("username", "")}


def upload_reel(path: Path, caption: str, ai_generated: bool = True, wait_seconds: int = 600,
                get=None, post=None) -> dict:
    """Đăng một Reel. -> {"id", "url"}. Lỗi quyền -> facebook.FacebookAuthError; lỗi khác -> InstagramError."""
    get, post = get or requests.get, post or requests.post
    tok = facebook._token()
    token = tok["page_token"]
    ig = account(get)["id"]
    created = facebook._check(post(f"{facebook.GRAPH}/{ig}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200], "share_to_feed": "true",
        "is_ai_generated": "true" if ai_generated else "false", "access_token": token}))
    cid = str(created["id"])
    size = Path(path).stat().st_size
    with open(path, "rb") as fh:
        up = facebook._check(post(f"{RUPLOAD}/{cid}", data=fh, timeout=900, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))
    if up.get("success") is False:
        raise InstagramError(f"Tải video lên Instagram không thành công: {up}")
    return _finish(ig, cid, token, get, post, wait_seconds, interval=20)


def _finish(ig: str, cid: str, token: str, get, post, wait_seconds: int, interval: int) -> dict:
    """Chờ "hộp chứa" xử lý xong (FINISHED) rồi đăng (media_publish). -> {"id", "url"}."""
    deadline, status = time.time() + wait_seconds, "IN_PROGRESS"
    while True:
        status = str(facebook._check(get(f"{facebook.GRAPH}/{cid}", timeout=30, params={
            "fields": "status_code,status", "access_token": token})).get("status_code") or status)
        if status in ("FINISHED", "PUBLISHED"):
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram xử lý lỗi: {status}")
        if time.time() >= deadline:
            raise InstagramError(f"Instagram xử lý quá {wait_seconds} giây (trạng thái {status})")
        time.sleep(interval)
    media = facebook._check(post(f"{facebook.GRAPH}/{ig}/media_publish", timeout=60,
                                 data={"creation_id": cid, "access_token": token}))
    mid = str(media["id"])
    try:
        link = facebook._check(get(f"{facebook.GRAPH}/{mid}", timeout=30, params={
            "fields": "permalink", "access_token": token})).get("permalink", "")
    except Exception:
        link = ""
    return {"id": mid, "url": link or f"https://www.instagram.com/{account(get).get('username', '')}"}


def hosted_url(path: Path, get=None, post=None) -> str:
    """Địa chỉ web công khai của một ảnh trên máy: Instagram chỉ nhận ẢNH qua image_url (không tải thẳng được như
    video), còn VM không công khai file. Cách không cần máy chủ riêng: tải lên Trang Facebook liên kết dạng ảnh TẠM
    không đăng (published=false, temporary=true — như bài hẹn giờ của facebook.post_photo: không hiện trên Trang, tự hết
    hạn) rồi lấy địa chỉ CDN của Meta."""
    get, post = get or requests.get, post or requests.post
    tok = facebook._token()
    page, token = tok["page_id"], tok["page_token"]
    with open(path, "rb") as fh:
        photo = facebook._check(post(f"{facebook.GRAPH}/{page}/photos", timeout=120,
                                     files={"source": (Path(path).name, fh)},
                                     data={"published": "false", "temporary": "true", "access_token": token}))
    images = facebook._check(get(f"{facebook.GRAPH}/{photo['id']}", timeout=30, params={
        "fields": "images", "access_token": token})).get("images") or []
    if not images:
        raise InstagramError("Không lấy được địa chỉ ảnh từ Facebook")
    return max(images, key=lambda i: int(i.get("width") or 0))["source"]


def post_image(path: Path, caption: str, wait_seconds: int = 120, get=None, post=None) -> dict:
    """Đăng một bài ẢNH (JPEG — Instagram không nhận PNG qua API). -> {"id", "url"}. Dùng cho bài giới thiệu kênh."""
    get, post = get or requests.get, post or requests.post
    token = facebook._token()["page_token"]
    ig = account(get)["id"]
    url = hosted_url(path, get, post)
    created = facebook._check(post(f"{facebook.GRAPH}/{ig}/media", timeout=60, data={
        "image_url": url, "caption": caption[:2200], "access_token": token}))
    return _finish(ig, str(created["id"]), token, get, post, wait_seconds, interval=5)


def caption(video: dict, cfg: dict) -> str:
    """Chú thích = tiêu đề + mô tả YouTube, bỏ #Shorts (như Facebook)."""
    return facebook.caption(video)
