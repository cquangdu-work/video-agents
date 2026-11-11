"""Đăng video lên YouTube qua Data API v3 — chỉ dùng `requests`, không cần thư viện Google.

Lệnh (chạy trên máy CÓ TRÌNH DUYỆT, một lần duy nhất):
    python -m src.publish.youtube auth       # Du đăng nhập, cấp quyền -> lưu token
    python -m src.publish.youtube whoami     # kiểm tra token đang trỏ vào kênh nào
    python -m src.publish.youtube status <video_id>   # xem chế độ hiển thị thực tế

Cách hoạt động của OAuth ở đây:
  1. `auth` mở trình duyệt tới trang cấp quyền của Google; Google trả một "mã" về
     http://127.0.0.1:<cổng> — một web server tí hon do chính lệnh này dựng lên.
  2. Đổi mã lấy REFRESH TOKEN (sống lâu) và lưu vào .secrets/youtube_token.json.
  3. Mỗi lần upload, đổi refresh token lấy access token (sống 1 giờ) rồi gọi API.
  VM không có trình duyệt -> chạy `auth` trên laptop rồi chép file token sang VM.

Hai cái bẫy đã biết (xem README):
  - App OAuth để trạng thái "Testing" thì refresh token CHẾT SAU 7 NGÀY.
  - Tài liệu Google: video upload từ dự án API chưa qua audit bị khoá riêng tư.
    Vì vậy upload() luôn trả về chế độ hiển thị THỰC TẾ để bên gọi báo cho Du.
"""
import argparse
import base64
import hashlib
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
TOKEN_PATH = ROOT / ".secrets" / "youtube_token.json"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3"

# Xin luôn quyền đọc số liệu cho agent Phân tích (bước sau) để Du chỉ phải cấp quyền 1 lần
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class YouTubeAuthError(RuntimeError):
    """Chưa cấp quyền, hoặc token hết hạn/bị thu hồi — cần Du chạy lại `auth`."""


class YouTubeUploadError(RuntimeError):
    pass


def _client() -> tuple:
    cid, secret = os.getenv("YT_CLIENT_ID"), os.getenv("YT_CLIENT_SECRET")
    if not cid or not secret:
        raise YouTubeAuthError("Thiếu YT_CLIENT_ID / YT_CLIENT_SECRET trong .env")
    return cid, secret


# ------------------------------------------------------------------ OAuth
def authorize(open_browser: bool = True) -> Path:
    """Luồng cấp quyền một lần (Authorization Code + PKCE, redirect về 127.0.0.1)."""
    import http.server
    import webbrowser

    cid, secret = _client()
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Xong. Quay lại cửa sổ dòng lệnh.".encode("utf-8"))

        def log_message(self, *args):   # không in log HTTP (có chứa mã cấp quyền)
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)   # cổng 0 = hệ điều hành tự chọn
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state,
        "access_type": "offline",     # xin refresh token
        "prompt": "consent",          # luôn hỏi lại để chắc chắn được cấp refresh token
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("Mở link này trong trình duyệt, đăng nhập và CHỌN ĐÚNG KÊNH (Brand Account):\n")
    print(url + "\n")
    if open_browser:
        webbrowser.open(url)
    while "code" not in got and "error" not in got:
        server.handle_request()
    server.server_close()

    if got.get("error"):
        raise YouTubeAuthError(f"Google từ chối: {got['error'][0]}")
    if got.get("state", [""])[0] != state:
        raise YouTubeAuthError("state không khớp — huỷ để an toàn, chạy lại lệnh auth")
    r = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": cid, "client_secret": secret, "code": got["code"][0],
        "code_verifier": verifier, "grant_type": "authorization_code",
        "redirect_uri": redirect})
    body = r.json()
    if "refresh_token" not in body:
        raise YouTubeAuthError(f"Không nhận được refresh token: {body.get('error_description', body)}")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "refresh_token": body["refresh_token"], "scope": body.get("scope", ""),
        "obtained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)      # Linux: chỉ chủ file đọc được (Windows bỏ qua)
    except OSError:
        pass
    return TOKEN_PATH


def access_token() -> str:
    """Đổi refresh token lấy access token dùng trong 1 giờ."""
    cid, secret = _client()
    if not TOKEN_PATH.exists():
        raise YouTubeAuthError("Chưa cấp quyền YouTube — chạy: python -m src.publish.youtube auth")
    refresh = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))["refresh_token"]
    r = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": cid, "client_secret": secret,
        "refresh_token": refresh, "grant_type": "refresh_token"})
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        if body.get("error") == "invalid_grant":
            raise YouTubeAuthError(
                "Refresh token hết hạn hoặc bị thu hồi — chạy lại lệnh auth. Nếu cứ 7 ngày "
                "lại bị: app OAuth đang ở trạng thái Testing, cần chuyển sang In production.")
        raise YouTubeAuthError(f"Không lấy được access token: {body.get('error_description', body)}")
    return body["access_token"]


# ---------------------------------------------------------------- Hẹn giờ
def compute_publish_at(yt_cfg: dict, now: datetime = None):
    """Giờ công khai kế tiếp theo cấu hình (vd "19:00" giờ Việt Nam) -> chuỗi UTC.

    Trả về None nếu không cấu hình hẹn giờ. Luôn cách hiện tại ít nhất 15 phút.
    Dùng độ lệch UTC cố định thay vì tên múi giờ: Việt Nam không đổi giờ mùa hè,
    và Python trên Windows không có sẵn dữ liệu múi giờ.
    """
    hhmm = yt_cfg.get("publish_time_local")
    if not hhmm:
        return None
    tz = timezone(timedelta(hours=float(yt_cfg.get("utc_offset_hours", 7))))
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    hour, minute = (int(x) for x in str(hhmm).split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now + timedelta(minutes=15):
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ Upload
def build_body(title: str, description: str, tags: list, yt_cfg: dict,
               publish_at: str = None) -> dict:
    """Phần metadata của lệnh upload. Tách riêng để test được mà không cần mạng."""
    privacy = yt_cfg.get("privacy", "private")
    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": bool(yt_cfg.get("made_for_kids", False)),
        "containsSyntheticMedia": bool(yt_cfg.get("contains_synthetic_media", True)),
    }
    if publish_at:
        # YouTube chỉ cho hẹn giờ với video đang ở chế độ riêng tư
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    snippet = {"title": title, "description": description,
               "categoryId": str(yt_cfg.get("category_id", "27")),
               "defaultLanguage": "vi", "defaultAudioLanguage": "vi"}
    if tags:                       # API báo lỗi 400 nếu gửi tags rỗng
        snippet["tags"] = tags
    return {"snippet": snippet, "status": status}


def upload(path: Path, title: str, description: str, tags: list, yt_cfg: dict,
           max_retries: int = 5) -> dict:
    """Upload kiểu "resumable": xin một phiên upload rồi đẩy file; đứt mạng thì hỏi
    YouTube đã nhận tới byte nào và gửi tiếp từ đó (không gửi lại từ đầu).

    Trả về {"id", "url", "privacy" (thực tế), "requested_privacy", "publish_at"}.
    """
    path = Path(path)
    size = path.stat().st_size
    token = access_token()
    publish_at = compute_publish_at(yt_cfg)
    body = build_body(title, description, tags, yt_cfg, publish_at)

    r = requests.post(
        UPLOAD_URL, timeout=60,
        params={"uploadType": "resumable", "part": "snippet,status",
                "notifySubscribers": str(bool(yt_cfg.get("notify_subscribers", True))).lower()},
        headers={"Authorization": f"Bearer {token}",
                 "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(size)},
        json=body)
    if r.status_code != 200 or "Location" not in r.headers:
        raise YouTubeUploadError(f"Không mở được phiên upload ({r.status_code}): {r.text[:300]}")
    session = r.headers["Location"]

    sent, resp = 0, None
    for attempt in range(max_retries + 1):
        try:
            with open(path, "rb") as fh:
                fh.seek(sent)
                resp = requests.put(
                    session, data=fh, timeout=600,
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "video/mp4",
                             "Content-Length": str(size - sent),
                             "Content-Range": f"bytes {sent}-{size - 1}/{size}"})
            if resp.status_code in (200, 201):
                break
            if resp.status_code < 500 and resp.status_code != 308:
                raise YouTubeUploadError(f"Upload bị từ chối ({resp.status_code}): {resp.text[:300]}")
        except requests.RequestException as exc:
            log.warning("Upload đứt (lần %d): %s", attempt + 1, type(exc).__name__)
        if attempt == max_retries:
            raise YouTubeUploadError("Upload thất bại sau nhiều lần thử")
        time.sleep(min(2 ** attempt, 30))
        # Hỏi YouTube đã nhận tới đâu: trả 308 kèm header Range: bytes=0-N
        q = requests.put(session, timeout=60,
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Length": "0", "Content-Range": f"bytes */{size}"})
        if q.status_code in (200, 201):          # hoá ra lần trước đã xong
            resp = q
            break
        if q.status_code == 308:
            rng = q.headers.get("Range")
            sent = int(rng.rsplit("-", 1)[1]) + 1 if rng else 0
        else:
            raise YouTubeUploadError(f"Phiên upload hỏng ({q.status_code}): {q.text[:300]}")

    video = resp.json()
    actual = video.get("status", {}).get("privacyStatus")
    return {"id": video["id"], "url": f"https://youtube.com/shorts/{video['id']}",
            "privacy": actual, "requested_privacy": body["status"]["privacyStatus"],
            "publish_at": publish_at}


def get_status(video_id: str) -> dict:
    """Chế độ hiển thị + tình trạng xử lý hiện tại của một video trên kênh."""
    r = requests.get(f"{API_URL}/videos", timeout=30,
                     params={"part": "status", "id": video_id},
                     headers={"Authorization": f"Bearer {access_token()}"})
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0]["status"] if items else {}


def whoami() -> dict:
    """Kênh mà token đang trỏ vào — kiểm tra đã chọn đúng Brand Account chưa."""
    r = requests.get(f"{API_URL}/channels", timeout=30,
                     params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {access_token()}"})
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return {}
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"],
            "country": items[0]["snippet"].get("country")}


# -------------------------------------------------- Số liệu (agent Phân tích)
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
_METRICS_FULL = ("views,engagedViews,averageViewDuration,averageViewPercentage,"
                 "likes,comments,shares,subscribersGained")
_METRICS_CORE = "views,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained"


def _report(token: str, **params) -> dict:
    r = requests.get(ANALYTICS_URL, timeout=30, params={"ids": "channel==MINE", **params},
                     headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise YouTubeUploadError(f"Analytics API {r.status_code}: {r.text[:200]}")
    return r.json()


def analytics_video(video_id: str, start: str, end: str, token: str) -> dict:
    """Số liệu riêng tư của MỘT video trong khoảng ngày (YYYY-MM-DD): lượt xem, % xem
    trung bình, giây xem trung bình... Chỉ chủ kênh (OAuth) mới lấy được.

    Thử bộ chỉ số đầy đủ trước; API từ chối tổ hợp đó thì lùi về bộ cốt lõi.
    """
    for metrics in (_METRICS_FULL, _METRICS_CORE):
        try:
            data = _report(token, startDate=start, endDate=end, metrics=metrics,
                           filters=f"video=={video_id}")
        except YouTubeUploadError:
            if metrics == _METRICS_CORE:
                raise
            continue
        rows = data.get("rows") or []
        if not rows:
            return {}
        names = [h["name"] for h in data["columnHeaders"]]
        return dict(zip(names, rows[0]))
    return {}


def analytics_retention(video_id: str, start: str, end: str, token: str) -> list:
    """Đường giữ chân người xem: [(vị trí 0..1 trong video, tỷ lệ còn xem), ...].
    Trống nếu video còn quá ít lượt xem (YouTube không trả đường này)."""
    data = _report(token, startDate=start, endDate=end, metrics="audienceWatchRatio",
                   dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}",
                   sort="elapsedVideoTimeRatio")
    return [(float(a), float(b)) for a, b in (data.get("rows") or [])]


def public_stats(video_ids: list, api_key: str) -> dict:
    """Số liệu CÔNG KHAI (xem/thích/bình luận) bằng API key thường — dùng khi chưa cấp
    quyền OAuth (vd đang đăng tay). Trả về {video_id: {"views", "likes", "comments"}}."""
    out = {}
    for i in range(0, len(video_ids), 50):          # API cho tối đa 50 id mỗi lần
        r = requests.get(f"{API_URL}/videos", timeout=30,
                         params={"part": "statistics", "id": ",".join(video_ids[i:i + 50]),
                                 "key": api_key})
        r.raise_for_status()
        for item in r.json().get("items", []):
            st = item.get("statistics", {})
            out[item["id"]] = {"views": int(st.get("viewCount", 0)),
                               "likes": int(st.get("likeCount", 0)),
                               "comments": int(st.get("commentCount", 0))}
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Cấp quyền / kiểm tra kết nối YouTube")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth", help="Cấp quyền một lần (cần trình duyệt)")
    a.add_argument("--no-browser", action="store_true", help="Chỉ in link, không tự mở")
    sub.add_parser("whoami", help="Token đang trỏ vào kênh nào")
    s = sub.add_parser("status", help="Xem chế độ hiển thị thực tế của một video")
    s.add_argument("video_id")
    args = ap.parse_args()
    try:
        if args.cmd == "auth":
            print(f"Đã lưu token: {authorize(open_browser=not args.no_browser)}")
            print("Kênh:", whoami())
        elif args.cmd == "whoami":
            print(whoami() or "Tài khoản này chưa có kênh YouTube")
        else:
            print(get_status(args.video_id) or "Không thấy video (sai id hoặc khác kênh)")
    except (YouTubeAuthError, YouTubeUploadError) as exc:
        sys.exit(f"LỖI: {exc}")


if __name__ == "__main__":
    main()
