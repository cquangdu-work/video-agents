"""Sửa nhãn ngôn ngữ (defaultLanguage / defaultAudioLanguage) của các video ĐÃ ĐĂNG cho khớp ngôn ngữ kênh.

Vì sao (26/11/2026): trước đó src/publish/youtube.build_body ghi cứng "vi" -> 7 video đầu tiên của kênh Hàn bị YouTube
coi là video tiếng Việt (nhãn này dùng cho tìm kiếm, phụ đề tự động, đưa video tới người xem theo ngôn ngữ). Code
đăng đã sửa; công cụ này sửa các video cũ. Du đồng ý 26/11/2026 (thay đổi trên video công khai).

    python tools/fix_video_language.py            # chỉ liệt kê video lệch nhãn (1 đơn vị quota mỗi 50 video)
    python tools/fix_video_language.py --apply    # sửa (videos.update: 50 đơn vị mỗi video)

Chạy trong thư mục của kênh (kênh Hàn: CHANNEL_CONFIG=config/channel_ko.yaml, thư mục ~/video-agents-ko).
videos.update ghi đè CẢ phần snippet -> gửi lại nguyên tiêu đề, mô tả, thẻ, danh mục đang có, chỉ đổi hai trường
ngôn ngữ (bỏ sót thẻ là YouTube xoá thẻ).
"""
import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import db, lang  # noqa: E402
from src.publish import youtube, yt_quota  # noqa: E402

KEEP = ("title", "description", "tags", "categoryId")


def snippets(ids: list, token: str) -> dict:
    out = {}
    for k in range(0, len(ids), 50):
        r = requests.get(f"{youtube.API_URL}/videos", timeout=30, params={"part": "snippet", "id": ",".join(ids[k:k + 50])},
                         headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        out.update({it["id"]: it["snippet"] for it in r.json().get("items", [])})
    return out


def main():
    from dotenv import load_dotenv
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="sửa thật (thay đổi trên video công khai)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(ROOT / ".env")
    want = lang.code()
    con = db.connect()
    rows = con.execute("SELECT id, youtube_id FROM videos WHERE youtube_id IS NOT NULL ORDER BY id").fetchall()
    con.close()
    token = youtube.access_token()
    snips = snippets([r["youtube_id"] for r in rows], token)
    wrong = [(r["id"], r["youtube_id"], snips[r["youtube_id"]]) for r in rows if r["youtube_id"] in snips
             and (snips[r["youtube_id"]].get("defaultLanguage"), snips[r["youtube_id"]].get("defaultAudioLanguage"))
             != (want, want)]
    print(f"Kênh “{want}”: {len(rows)} video, {len(wrong)} lệch nhãn ngôn ngữ")
    for vid, yid, sn in wrong:
        print(f"  #{vid} {yid}: {sn.get('defaultLanguage')}/{sn.get('defaultAudioLanguage')} — {sn['title'][:60]}")
        if not a.apply:
            continue
        body = {k: sn[k] for k in KEEP if k in sn}
        body.update(defaultLanguage=want, defaultAudioLanguage=want)
        yt_quota.spend("insert")                 # videos.update: 50 đơn vị, cùng mức với "insert"
        r = requests.put(f"{youtube.API_URL}/videos", timeout=30, params={"part": "snippet"},
                         headers={"Authorization": f"Bearer {token}"}, json={"id": yid, "snippet": body})
        if r.status_code != 200:
            print(f"    LỖI {r.status_code}: {r.text[:200]}")
            continue
        got = r.json()["snippet"]
        ok = (got.get("tags") or []) == (sn.get("tags") or []) and got["title"] == sn["title"]
        print(f"    -> {got.get('defaultLanguage')}/{got.get('defaultAudioLanguage')}"
              f" {'(tiêu đề, thẻ giữ nguyên)' if ok else '⚠️ tiêu đề/thẻ khác trước — kiểm lại'}")
    if wrong and not a.apply:
        print("Chạy lại với --apply để sửa.")


if __name__ == "__main__":
    main()
