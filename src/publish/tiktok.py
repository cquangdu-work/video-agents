"""Đẩy video vào HỘP THƯ TikTok của chủ kênh (bản nháp) qua Content Posting API — chỉ dùng `requests`.

Vì sao là bản nháp (inbox) chứ không đăng thẳng (Direct Post): app chưa qua audit thì mọi bài
đăng thẳng bị khoá riêng tư, và đăng thẳng đòi giao diện xác nhận riêng cho từng bài. Đẩy vào
hộp thư thì Du mở TikTok, chạm thông báo, viết chú thích và bấm đăng (~1 phút) — video vẫn qua
tay Du lần cuối, đúng luật "không tự động hoá 100%".

Cấp quyền (Login Kit cho web, không cần máy chủ web riêng):
  1. bot gửi link https://www.tiktok.com/v2/auth/authorize/?... (lệnh /tiktok trong Telegram);
  2. TikTok chuyển về trang tĩnh tiktok-callback.html trên site của kênh (GitHub Pages) — trang
     chỉ HIỂN THỊ địa chỉ có mã để Du chép, không gửi đi đâu;
  3. Du dán vào Telegram, bot trên VM đổi mã lấy token (mã vô dụng nếu không có client secret).
Token truy cập sống 2 giờ, refresh token 180 ngày và XOAY VÒNG: mỗi lần làm mới phải lưu token mới,
token cũ mất hiệu lực ngay.

    python -m src.publish.tiktok whoami      # token đang trỏ vào tài khoản TikTok nào
"""
import argparse
import json
import logging
import os
import secrets
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN_PATH = ROOT / ".secrets" / "tiktok_token.json"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.upload"
DEFAULT_REDIRECT = "https://cquangdu-work.github.io/thegioiquaconso/tiktok-callback.html"

# Media Transfer Guide: file < 5 MB gửi nguyên; khúc thường 5-64 MB, khúc cuối tới 128 MB;
# số khúc = kích thước // khúc (làm tròn xuống, phần dư dồn vào khúc cuối). "MB" không rõ là
# 10^6 hay 2^20 -> chọn số an toàn với cả hai cách hiểu.
SINGLE_CHUNK_MAX = 60_000_000
CHUNK = 10_000_000


class TikTokAuthError(RuntimeError):
    """Chưa cấp quyền / token hết hạn hoặc bị thu hồi — Du gửi /tiktok để cấp lại."""


class TikTokUploadError(RuntimeError):
    pass


def _client() -> tuple:
    key, secret = os.getenv("TIKTOK_CLIENT_KEY"), os.getenv("TIKTOK_CLIENT_SECRET")
    if not key or not secret:
        raise TikTokAuthError("Thiếu TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET trong .env")
    return key, secret


# ------------------------------------------------------------------ cấp quyền
def start_auth(redirect: str = DEFAULT_REDIRECT) -> dict:
    """-> {"url", "state"}; bên gọi giữ state để đối chiếu khi Du dán địa chỉ về."""
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": _client()[0], "response_type": "code", "scope": SCOPES,
        "redirect_uri": redirect, "state": state, "disable_auto_auth": 1})
    return {"url": url, "state": state}


def _save(body: dict, now: datetime = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tok = {"access_token": body["access_token"], "refresh_token": body["refresh_token"],
           "open_id": body.get("open_id", ""), "scope": body.get("scope", ""),
           "expires_at": (now + timedelta(seconds=int(body.get("expires_in", 7200)))).isoformat(timespec="seconds"),
           "refresh_expires_at": (now + timedelta(seconds=int(body.get("refresh_expires_in", 0)))).isoformat(timespec="seconds"),
           "obtained_at": now.isoformat(timespec="seconds")}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)          # Linux: chỉ chủ file đọc được
    except OSError:
        pass
    return tok


def _token_request(**data) -> dict:
    key, secret = _client()
    r = requests.post(f"{API}/oauth/token/", timeout=30, data={"client_key": key, "client_secret": secret, **data},
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    body = r.json()
    if "access_token" not in body:
        raise TikTokAuthError(f"TikTok từ chối: {body.get('error_description') or body.get('error') or body}")
    return body


def finish_auth(pasted: str, state: str, redirect: str = DEFAULT_REDIRECT) -> dict:
    """Du dán địa chỉ trang tiktok-callback.html (có ?code=...&state=...) -> lưu token."""
    import re
    m = re.search(r"https://\S+\?\S+", pasted or "")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(m.group(0) if m else "").query)   # parse_qs tự giải mã
    if q.get("error"):
        raise TikTokAuthError(f"TikTok từ chối: {q.get('error_description', q['error'])[0]}")
    if not q.get("code"):
        raise TikTokAuthError("Không thấy mã trong địa chỉ — bấm “Sao chép” trên trang rồi dán nguyên văn")
    if q.get("state", [""])[0] != state:
        raise TikTokAuthError("Link cấp quyền này đã cũ — gửi /tiktok để lấy link mới")
    granted = set((q.get("scopes", [""])[0]).split(","))
    if "video.upload" not in granted:
        raise TikTokAuthError("Chưa cho quyền đẩy video (video.upload) — cấp lại và giữ quyền đó bật")
    return _save(_token_request(code=q["code"][0], grant_type="authorization_code", redirect_uri=redirect))


def access_token(now: datetime = None) -> str:
    """Token truy cập còn hạn; sắp hết (dưới 5 phút) thì làm mới và LƯU refresh token mới."""
    now = now or datetime.now(timezone.utc)
    try:
        tok = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TikTokAuthError("Chưa kết nối TikTok — gửi /tiktok cho bot để cấp quyền")
    if datetime.fromisoformat(tok["expires_at"]) - now > timedelta(minutes=5):
        return tok["access_token"]
    try:
        return _save(_token_request(grant_type="refresh_token", refresh_token=tok["refresh_token"]), now)["access_token"]
    except TikTokAuthError as exc:
        raise TikTokAuthError(f"Quyền TikTok hết hạn hoặc bị thu hồi ({exc}) — gửi /tiktok để cấp lại")


def token_days_left(now: datetime = None):
    """Số ngày refresh token còn sống (180 ngày từ lúc cấp), None nếu chưa có token."""
    try:
        tok = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return (datetime.fromisoformat(tok["refresh_expires_at"]) - (now or datetime.now(timezone.utc))).total_seconds() / 86400
    except (OSError, ValueError, KeyError):
        return None


# ------------------------------------------------------------------ đẩy video
def _api(method: str, path: str, token: str, **kw) -> dict:
    r = requests.request(method, f"{API}{path}", timeout=60,
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, **kw)
    body = r.json() if r.content else {}
    err = (body.get("error") or {})
    if r.status_code != 200 or err.get("code") not in (None, "ok"):
        raise TikTokUploadError(f"{path} lỗi {r.status_code}: {err.get('code')} — {err.get('message')}")
    return body.get("data") or {}


def chunk_plan(size: int) -> tuple:
    """(chunk_size, total_chunk_count) theo luật của TikTok; khúc cuối gánh phần dư."""
    if size <= SINGLE_CHUNK_MAX:
        return size, 1
    return CHUNK, size // CHUNK


def upload_draft(path: Path, wait_seconds: int = 90) -> dict:
    """Đẩy một video vào hộp thư TikTok. -> {"publish_id", "status"} (status: SEND_TO_USER_INBOX khi xong)."""
    path = Path(path)
    size = path.stat().st_size
    chunk_size, total = chunk_plan(size)
    token = access_token()
    data = _api("POST", "/post/publish/inbox/video/init/", token, json={"source_info": {
        "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": total}})
    publish_id, upload_url = data["publish_id"], data["upload_url"]
    with open(path, "rb") as fh:
        for i in range(total):
            start = i * chunk_size
            end = size - 1 if i == total - 1 else start + chunk_size - 1     # khúc cuối gánh phần dư
            fh.seek(start)
            body = fh.read(end - start + 1)
            r = requests.put(upload_url, data=body, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                raise TikTokUploadError(f"Gửi khúc {i + 1}/{total} lỗi {r.status_code}: {r.text[:200]}")
    status = "PROCESSING_UPLOAD"
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        st = _api("POST", "/post/publish/status/fetch/", token, json={"publish_id": publish_id})
        status = st.get("status", status)
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            break
        if status == "FAILED":
            raise TikTokUploadError(f"TikTok xử lý video lỗi: {st.get('fail_reason')}")
        time.sleep(5)
    return {"publish_id": publish_id, "status": status}


def whoami() -> dict:
    """Tài khoản TikTok mà token đang trỏ vào (quyền user.info.basic)."""
    return _api("GET", "/user/info/", access_token(), params={"fields": "open_id,display_name"}).get("user", {})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description="Kiểm tra kết nối TikTok")
    ap.add_argument("cmd", choices=["whoami"])
    ap.parse_args()
    try:
        print(whoami())
    except (TikTokAuthError, TikTokUploadError) as exc:
        sys.exit(f"LỖI: {exc}")


if __name__ == "__main__":
    main()
