"""DANH SÁCH PHÁT tự động trên YouTube (Du xin 21/11/2026: "hoàn thành các kênh một cách chuyên nghiệp").

Mỗi video đăng xong (kể cả đang hẹn giờ — video riêng tư trong danh sách công khai chỉ hiện khi tới giờ công khai) vào
một danh sách theo DẠNG video (learning.video_kind): bản đồ / cuộc đua / biểu đồ / bài báo, video dài vào "tổng hợp".
Lý do: người xem xem hết một video thì danh sách đưa tiếp video cùng loại (giờ xem — nhánh YPP Du chọn), trang kênh
có các mục rõ ràng thay vì một dòng video lẫn lộn.

Tên + mô tả danh sách ở cấu hình kênh (publish.youtube.playlists; xoá mục đó = tắt). Danh sách được tạo (công khai)
lần đầu cần tới, id nhớ ở state "playlist_<dạng>"; video đã vào danh sách nhớ ở "playlisted_<id video>" — chạy lại
không thêm trùng. Quota YouTube: tạo danh sách 50, thêm một video 50 đơn vị (hạn mức 10.000/ngày).

  python -m src.publish.playlists            -> xem video nào sẽ vào danh sách nào (không đổi gì)
  python -m src.publish.playlists --apply    -> tạo danh sách + thêm các video đã đăng
"""
import argparse
import logging

import requests

from .. import db, lang

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"
LONG = "tong-hop"
# SERIES cố định (24/11/2026, Du chốt "phát triển sâu ngách"): ý tưởng có tiền tố tiêu đề này vào danh sách phát RIÊNG
# (nếu cấu hình kênh có khoá đó), mô tả video mở bằng tên series + hashtag + link danh sách — người xem nhận ra, đi
# tìm, xem tiếp cả series. Không có khoá trong cấu hình (kênh Việt) -> theo dạng video như cũ.
SERIES = [("thang-nay", "이번 달 통계"), ("han-quoc", "한국 지도")]       # (khoá danh sách, tiền tố tiêu đề ý tưởng)
PLAYLIST_URL = "https://www.youtube.com/playlist?list="


def config(cfg: dict) -> dict:
    return ((cfg.get("publish") or {}).get("youtube") or {}).get("playlists") or {}


def series_of(idea_title, cfg: dict):
    """Khoá series của một ý tưởng (theo tiền tố tiêu đề do nguồn bảng số tự đặt), hoặc None."""
    title = str(idea_title or "")
    return next((key for key, prefix in SERIES if title.startswith(prefix) and key in config(cfg)), None)


def with_series(con, meta: dict, idea_title, cfg: dict) -> dict:
    """Mô tả video mở bằng dòng series ("▶ 시리즈 「지도로 보는 한국」 #지도로보는한국") + link danh sách phát nếu đã có."""
    key = series_of(idea_title, cfg)
    if not key:
        return meta
    name = config(cfg)[key]["title"]
    line = f"▶ 시리즈 「{name}」 #{name.replace(' ', '')}"
    pid = db.get_state(con, f"playlist_{key}")
    if pid:
        line += f"\n전체 보기: {PLAYLIST_URL}{pid}"
    return dict(meta, description=f"{line}\n\n{meta['description']}")


def kind_of(con, video: dict, cfg: dict = None) -> str:
    """Danh sách của video: video dài (không có kịch bản) -> "tong-hop"; Shorts -> series (SERIES) nếu có, không thì
    learning.video_kind của ý tưởng."""
    from ..learning import video_kind
    if not video.get("script_id"):
        return LONG
    row = con.execute("SELECT i.title, i.source_name FROM scripts s JOIN ideas i ON i.id = s.idea_id WHERE s.id = ?",
                      (video["script_id"],)).fetchone()
    if not row:
        return "bieu-do"
    return series_of(row[0], cfg or {}) or video_kind(row[0], row[1])


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check(r) -> dict:
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def ensure(con, kind: str, cfg: dict, token: str, http=requests) -> str:
    """id danh sách phát của một dạng video; chưa có thì tìm danh sách CÙNG TÊN trên kênh (lần chạy trước lỗi giữa
    chừng) rồi mới tạo mới. Dạng không có trong cấu hình -> None."""
    want = config(cfg).get(kind)
    if not want:
        return None
    key = f"playlist_{kind}"
    pid = db.get_state(con, key)
    if pid:
        return pid
    page = None
    while not pid:
        params = {"part": "snippet", "mine": "true", "maxResults": 50, **({"pageToken": page} if page else {})}
        body = _check(http.get(f"{API}/playlists", params=params, headers=_headers(token), timeout=30))
        pid = next((it["id"] for it in body.get("items", []) if it["snippet"]["title"] == want["title"]), None)
        page = body.get("nextPageToken")
        if not page:
            break
    if not pid:
        snippet = {"title": want["title"], "description": want.get("description", ""), "defaultLanguage": lang.code()}
        from . import yt_quota
        yt_quota.spend("insert")
        body = _check(http.post(f"{API}/playlists", params={"part": "snippet,status"}, headers=_headers(token),
                                json={"snippet": snippet, "status": {"privacyStatus": "public"}}, timeout=30))
        pid = body["id"]
        log.info("Tạo danh sách phát %s: %s", want["title"], pid)
    db.set_state(con, key, pid)
    return pid


def add(con, video: dict, cfg: dict, token: str = None, http=requests) -> str:
    """Thêm một video đã có trên YouTube vào danh sách của dạng nó (lên ĐẦU danh sách: mới nhất trước). -> id danh
    sách, hoặc None nếu tắt / video chưa lên YouTube / dạng không có danh sách."""
    if not config(cfg) or not video.get("youtube_id"):
        return None
    done = db.get_state(con, f"playlisted_{video['id']}")
    if done:
        return done
    if token is None:
        from . import youtube
        token = youtube.access_token()
    pid = ensure(con, kind_of(con, video, cfg), cfg, token, http)
    if not pid:
        return None
    from . import yt_quota
    yt_quota.spend("insert")
    r = http.post(f"{API}/playlistItems", params={"part": "snippet"}, headers=_headers(token), timeout=30,
                  json={"snippet": {"playlistId": pid, "position": 0,
                                    "resourceId": {"kind": "youtube#video", "videoId": video["youtube_id"]}}})
    if r.status_code == 409 or "videoAlreadyInPlaylist" in (r.text or ""):
        log.info("Video #%s đã có trong danh sách %s", video["id"], pid)
    else:
        _check(r)
    db.set_state(con, f"playlisted_{video['id']}", pid)
    return pid


def pending(con) -> list:
    """Video đã lên YouTube mà chưa vào danh sách phát nào, cũ trước."""
    rows = con.execute("SELECT * FROM videos WHERE youtube_id IS NOT NULL AND youtube_id != '' ORDER BY id").fetchall()
    return [dict(r) for r in rows if not db.get_state(con, f"playlisted_{r['id']}")]


def backfill(con, cfg: dict, token: str = None, http=requests) -> int:
    """Bổ sung mọi video còn thiếu (đăng tay, lỗi lúc đăng, video có trước khi có tính năng này). -> số video đã thêm."""
    todo = pending(con) if config(cfg) else []
    if not todo:
        return 0
    if token is None:
        from . import youtube
        token = youtube.access_token()
    n = 0
    for v in todo:
        try:
            if add(con, v, cfg, token, http):
                n += 1
        except Exception as exc:
            log.warning("Chưa thêm được video #%s vào danh sách phát: %s", v["id"], exc)
    return n


def main():
    from dotenv import load_dotenv
    from ..review import load_config
    ap = argparse.ArgumentParser(description="Danh sách phát YouTube theo dạng video")
    ap.add_argument("--apply", action="store_true", help="tạo danh sách + thêm video (mặc định chỉ xem trước)")
    a = ap.parse_args()
    load_dotenv(db.DB_PATH.parent.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, con = load_config(), db.connect()
    pl = config(cfg)
    for v in pending(con):
        kind = kind_of(con, v, cfg)
        print(f"#{v['id']} {v['youtube_id']} [{kind}] -> {pl.get(kind, {}).get('title', '(không có danh sách)')}"
              f" | {v['title']}")
    if a.apply:
        print("Đã thêm", backfill(con, cfg), "video")


if __name__ == "__main__":
    main()
