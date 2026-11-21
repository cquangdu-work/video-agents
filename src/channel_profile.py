"""HỒ SƠ KÊNH trên các nền tảng (Du xin 21/11/2026: "hoàn thành các kênh và mạng xã hội một cách chuyên nghiệp").

Soát 21/11: cả hai kênh YouTube để trống phần mô tả, chưa có ảnh bìa / từ khoá / danh sách phát, kênh Hàn chưa đặt
quốc gia; Trang Facebook chưa có phần giới thiệu, ảnh bìa; Instagram chưa có tiểu sử.

Chữ lấy từ cấu hình kênh (`profile`), ảnh bìa từ src/brand_kit.py (assets/brand/<ngôn ngữ>/).
- YouTube (API, token có quyền youtube.force-ssl): mô tả kênh, từ khoá, ngôn ngữ, quốc gia, ảnh bìa.
- Trang Facebook (API, token Trang có pages_manage_metadata): phần giới thiệu, website, ảnh bìa.
- Phần API KHÔNG làm được -> bot gửi Du bản chạm-để-copy (--kit): link trên trang YouTube, hồ sơ Instagram (Meta
  không có API sửa tiểu sử), TikTok, tên người dùng của Trang, cài đặt "không dành cho trẻ em" của kênh Hàn...
Đây là thay đổi CÔNG KHAI -> chỉ --apply sau khi Du duyệt bản xem trước (CLAUDE.md). Chạy lại an toàn: chỉ gửi phần
khác với hiện tại; ảnh bìa chỉ tải lên lại khi file ảnh đổi (nhớ dấu vân tay ở state).

  python -m src.channel_profile            -> so hồ sơ hiện tại với bản sẽ áp (không đổi gì)
  python -m src.channel_profile --apply    -> áp lên YouTube + Trang Facebook
  python -m src.channel_profile --kit      -> gửi Du qua Telegram phần phải tự làm
(Tên file không phải "profile.py": trùng tên module có sẵn của Python.)
"""
import argparse
import hashlib
import html
import json
import logging
from pathlib import Path
from urllib.parse import quote

import requests

from . import db, lang

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
YT_API = "https://www.googleapis.com/youtube/v3"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3"


def profile(cfg: dict) -> dict:
    return cfg.get("profile") or {}


def asset(name: str) -> Path:
    return ROOT / "assets" / "brand" / lang.code() / name


def _sha1(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def contact_line(p: dict) -> str:
    email = (p.get("contact_email") or "").strip()
    return lang.pick(vi=f"📩 Liên hệ hợp tác: {email}", ko=f"📩 문의: {email}") if email else ""


# ------------------------------------------------------------------ YouTube
def youtube_plan(cfg: dict) -> dict:
    """Các trường brandingSettings.channel sẽ đặt."""
    p = profile(cfg)
    yt = p.get("youtube") or {}
    desc = "\n\n".join(x for x in (yt.get("description", "").strip(), contact_line(p)) if x)
    plan = {"description": desc,
            "keywords": " ".join(f'"{k}"' if " " in k else k for k in yt.get("keywords") or [])}
    if yt.get("language"):
        plan["defaultLanguage"] = yt["language"]
    if yt.get("country"):
        plan["country"] = yt["country"]
    return {k: v for k, v in plan.items() if v}


def yt_channel(token: str, get=None) -> dict:
    r = (get or requests.get)(f"{YT_API}/channels", timeout=30, headers={"Authorization": f"Bearer {token}"},
                              params={"part": "brandingSettings,snippet", "mine": "true"})
    if r.status_code != 200:
        raise RuntimeError(f"YouTube {r.status_code}: {r.text[:300]}")
    return r.json()["items"][0]


def channel_url(ch: dict) -> str:
    handle = (ch.get("snippet") or {}).get("customUrl")
    return f"https://www.youtube.com/{quote(handle, safe='@')}" if handle else f"https://www.youtube.com/channel/{ch['id']}"


def upload_banner(path: Path, token: str, post=None) -> str:
    """Tải ảnh bìa lên (channelBanners.insert, ≤ 6 MB, 16:9, tối thiểu 2048x1152) -> URL để gắn vào kênh."""
    r = (post or requests.post)(f"{YT_UPLOAD}/channelBanners/insert", timeout=120, params={"uploadType": "media"},
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
                                data=Path(path).read_bytes())
    if r.status_code != 200:
        raise RuntimeError(f"Tải ảnh bìa YouTube lỗi {r.status_code}: {r.text[:300]}")
    return r.json()["url"]


def apply_youtube(con, cfg: dict, apply: bool = False, token: str = None, get=None, post=None, put=None) -> list:
    """So / áp hồ sơ YouTube. -> danh sách thay đổi (chữ để báo Du).

    channels.update XOÁ trường nào của brandingSettings không gửi kèm -> luôn gửi lại đủ các trường đang có (kể cả
    ảnh bìa hiện tại) rồi mới đè phần mới."""
    if token is None:
        from .publish import youtube
        token = youtube.access_token()
    ch = yt_channel(token, get)
    bs = ch.get("brandingSettings") or {}
    cur = dict(bs.get("channel") or {})
    plan = youtube_plan(cfg)
    changes = [f"YouTube: {k}" for k, v in plan.items() if cur.get(k) != v]
    banner = asset("youtube_banner.png")
    image = dict(bs.get("image") or {})
    new_banner = banner.exists() and (not image.get("bannerExternalUrl")
                                      or db.get_state(con, "profile_yt_banner_sha1") != _sha1(banner))
    if new_banner:
        changes.append("YouTube: ảnh bìa")
    if not apply or not changes:
        return changes
    if new_banner:
        image["bannerExternalUrl"] = upload_banner(banner, token, post)
    body = {"id": ch["id"], "brandingSettings": {"channel": {**cur, **plan}}}
    if image.get("bannerExternalUrl"):
        body["brandingSettings"]["image"] = {"bannerExternalUrl": image["bannerExternalUrl"]}
    r = (put or requests.put)(f"{YT_API}/channels", timeout=60, params={"part": "brandingSettings"},
                              headers={"Authorization": f"Bearer {token}"}, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"Cập nhật kênh YouTube lỗi {r.status_code}: {r.text[:400]}")
    if new_banner:
        db.set_state(con, "profile_yt_banner_sha1", _sha1(banner))
    return changes


# ------------------------------------------------------------------ Trang Facebook
def facebook_plan(cfg: dict, website: str = None) -> dict:
    p = profile(cfg)
    plan = {}
    if p.get("facebook_about"):
        plan["about"] = p["facebook_about"]
    if website:
        plan["website"] = website
    if (p.get("contact_email") or "").strip():
        plan["emails"] = [p["contact_email"].strip()]
    return plan


def apply_facebook(con, cfg: dict, website: str = None, apply: bool = False, get=None, post=None) -> list:
    """So / áp phần giới thiệu, website, email và ảnh bìa của Trang (token Trang cần pages_manage_metadata)."""
    from .publish import facebook
    if not facebook.connected():
        return []
    page = facebook.page_id()
    cur = facebook.graph_get(page, get, fields="about,website,emails,cover")
    plan = facebook_plan(cfg, website)
    changes = [f"Facebook: {k}" for k, v in plan.items() if cur.get(k) != v]
    cover = asset("facebook_cover.png")
    new_cover = cover.exists() and (not cur.get("cover") or db.get_state(con, "profile_fb_cover_sha1") != _sha1(cover))
    if new_cover:
        changes.append("Facebook: ảnh bìa")
    if not apply or not changes:
        return changes
    if not facebook.can("pages_manage_metadata"):
        raise facebook.FacebookAuthError("Token Trang thiếu quyền pages_manage_metadata — gửi lại /facebook")
    token = facebook._token()["page_token"]
    post = post or requests.post
    data = {k: (json.dumps(v) if isinstance(v, list) else v) for k, v in plan.items() if cur.get(k) != v}
    if new_cover:
        with open(cover, "rb") as fh:          # ảnh không đăng lên dòng thời gian, chỉ để làm ảnh bìa
            photo = facebook._check(post(f"{facebook.GRAPH}/{page}/photos", timeout=120,
                                         files={"source": (cover.name, fh)},
                                         data={"published": "false", "access_token": token}))
        data.update(cover=str(photo["id"]), no_feed_story="true", no_notification="true")
    if data:
        facebook._check(post(f"{facebook.GRAPH}/{page}", timeout=60, data={**data, "access_token": token}))
    if new_cover:
        db.set_state(con, "profile_fb_cover_sha1", _sha1(cover))
    return changes


# ------------------------------------------------------------------ phần Du tự làm (Telegram)
def _pre(text: str) -> str:
    return f"<pre>{html.escape(str(text))}</pre>"


def kit_text(cfg: dict, yt_url: str = None, fb_link: str = None, ig_username: str = None,
             yt_settings: dict = None, long_videos: bool = False) -> str:
    """Tin Telegram: những việc API không làm được, kèm chữ chạm-để-copy. Không có việc nào -> "".

    Xác minh số điện thoại chỉ nhắc khi kênh CÓ video dài (`long_videos`): nó mở hình thu nhỏ tự chọn / video trên 15
    phút — Shorts không cần. Ca thật 21/11: số điện thoại Hàn của Du đã xác minh đủ 2 kênh (YouTube giới hạn 2 kênh
    mỗi số mỗi năm), kênh Hàn chỉ có Shorts nên không cần bước này."""
    p = profile(cfg)
    ko = lang.code() == "ko"
    steps = []
    links = []
    if fb_link and not ko:
        links.append(f"• Facebook: {_pre(fb_link)}")
    if ig_username:
        links.append(f"• Instagram: {_pre('https://www.instagram.com/' + ig_username)}")
    if not ko:
        links.append("• TikTok: link hồ sơ TikTok của kênh")
    if links:
        steps.append("YouTube Studio → <b>Tuỳ chỉnh</b> → <b>Thông tin cơ bản</b> → <b>Đường liên kết</b> → thêm:\n"
                     + "\n".join(links))
    st = yt_settings or {}
    if "madeForKids" not in st and "selfDeclaredMadeForKids" not in st:
        steps.append("YouTube Studio → <b>Cài đặt</b> → <b>Kênh</b> → <b>Cài đặt nâng cao</b> → Đối tượng người xem:"
                     " chọn <b>Không, kênh này không dành cho trẻ em</b> (kênh này chưa đặt).")
    if long_videos and st.get("longUploadsStatus") in ("eligible", "disallowed"):
        steps.append("YouTube Studio → <b>Cài đặt</b> → <b>Kênh</b> → <b>Điều kiện sử dụng tính năng</b> → xác minh"
                     " số điện thoại (mở hình thu nhỏ tự chọn cho video dài, video trên 15 phút). Mỗi số chỉ xác minh"
                     " được 2 kênh mỗi năm.")
    if ig_username or p.get("instagram_bio"):
        ig = ["Instagram → <b>Chỉnh sửa trang cá nhân</b>:"]
        if p.get("instagram_name"):
            ig.append(f"• Tên: {_pre(p['instagram_name'])}")
        if p.get("instagram_bio"):
            ig.append(f"• Tiểu sử: {_pre(p['instagram_bio'])}")
        if yt_url:
            ig.append(f"• Liên kết (YouTube): {_pre(yt_url)}")
        steps.append("\n".join(ig))
    if p.get("tiktok_bio"):
        steps.append(f"TikTok → <b>Sửa hồ sơ</b> → Tiểu sử: {_pre(p['tiktok_bio'])}")
    tail = (fb_link or "").rstrip("/").split("/")[-1]
    if fb_link and not ko and ("profile.php" in fb_link or tail.isdigit()):    # Trang kênh Hàn chỉ để liên kết
        steps.append("Trang Facebook → <b>Cài đặt</b> → tên người dùng: đặt <b>@thegioiquaconso</b> (nếu còn trống)"
                     " để link Trang gọn, dễ nhớ.")
    if not (p.get("contact_email") or "").strip():
        steps.append("Có Gmail riêng của kênh thì gửi mình địa chỉ: mình thêm dòng liên hệ vào mô tả YouTube + Trang;"
                     " Du điền thêm ở YouTube Studio → Tuỳ chỉnh → Thông tin cơ bản → Thông tin liên hệ.")
    if not steps:
        return ""
    head = lang.pick(vi="🧰 <b>Hồ sơ kênh — phần Du tự làm</b> (API không làm được, mỗi việc ~1 phút):",
                     ko="🧰 <b>Hồ sơ kênh Hàn — phần Du tự làm</b> (API không làm được, mỗi việc ~1 phút):")
    return head + "\n\n" + "\n\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def send_kit(cfg: dict) -> bool:
    from . import telegram_bot as tg
    from .publish import facebook, youtube
    yt_url, st = None, {}
    try:
        token = youtube.access_token()
        ch = yt_channel(token)
        yt_url = channel_url(ch)
        r = requests.get(f"{YT_API}/channels", timeout=30, headers={"Authorization": f"Bearer {token}"},
                         params={"part": "status", "mine": "true"})
        st = (r.json().get("items") or [{}])[0].get("status") or {}
    except Exception as exc:
        log.warning("Chưa đọc được kênh YouTube: %s", exc)
    fb_link = ig = None
    if facebook.connected():
        try:
            fb_link = facebook.graph_get(facebook.page_id(), fields="link").get("link")
        except Exception as exc:
            log.warning("Chưa đọc được Trang: %s", exc)
        if (cfg.get("publish") or {}).get("instagram", {}).get("enabled"):
            try:
                from .publish import instagram
                ig = instagram.account().get("username")
            except Exception as exc:
                log.warning("Chưa đọc được Instagram: %s", exc)
    con = db.connect()
    try:                                        # kênh có video dài (script_id rỗng) chưa?
        long_videos = con.execute("SELECT 1 FROM videos WHERE script_id IS NULL LIMIT 1").fetchone() is not None
    finally:
        con.close()
    text = kit_text(cfg, yt_url, fb_link, ig, st, long_videos)
    return bool(text) and bool(tg.send_message(text, as_html=True))


def main():
    from dotenv import load_dotenv
    from .review import load_config
    ap = argparse.ArgumentParser(description="Hồ sơ kênh trên YouTube / Facebook / Instagram / TikTok")
    ap.add_argument("--apply", action="store_true", help="áp lên YouTube + Trang Facebook (thay đổi công khai)")
    ap.add_argument("--kit", action="store_true", help="gửi Du qua Telegram phần phải tự làm")
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, con = load_config(), db.connect()
    from .publish import youtube
    ch = yt_channel(youtube.access_token())
    yt_url = channel_url(ch)
    print("Kênh:", ch["snippet"]["title"], yt_url)
    for name, fn in (("YouTube", lambda: apply_youtube(con, cfg, a.apply)),
                     ("Facebook", lambda: apply_facebook(con, cfg, yt_url, a.apply))):
        try:
            changes = fn()
            print(f"{name}: {'ĐÃ ÁP' if a.apply else 'sẽ đổi'} {changes or 'không có gì'}")
        except Exception as exc:
            print(f"{name}: LỖI {exc}")
    if not a.apply:
        print("\n--- Mô tả YouTube sẽ đặt ---\n" + youtube_plan(cfg).get("description", ""))
    if a.kit:
        print("Gửi Telegram:", send_kit(cfg))


if __name__ == "__main__":
    main()
