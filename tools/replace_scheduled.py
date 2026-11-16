"""Thay một video ĐÃ TẢI LÊN nhưng CHƯA tới giờ công khai bằng file dựng lại (vd sửa lỗi, đổi mẫu hình).

YouTube không cho thay file của video đã tải lên, nên công cụ này:
  1. tải file mới lên, hẹn ĐÚNG giờ hẹn cũ (đọc từ state yt_publish_at_<id>),
  2. ghi id mới vào DB (bot soát sau giờ hẹn sẽ soát video mới),
  3. bỏ hẹn giờ video cũ -> nó nằm riêng tư vô thời hạn (KHÔNG xoá; Du tự xoá trong Studio nếu muốn),
  4. kiểm lại trên YouTube cả hai video rồi báo Telegram.

    python tools/replace_scheduled.py 7 [--title "..."] [--music-credit "Tên — Tác giả"] [--yes]

Không có --yes thì chỉ in kế hoạch, không đụng gì (đây là thao tác công khai — chạy thật khi Du yêu cầu).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def new_description(desc: str, credit: str, library: str) -> str:
    """Đổi dòng 'Nhạc nền: ...' cho khớp bài nhạc của bản dựng lại (ghi công phải đúng bài)."""
    lines = desc.splitlines()
    out = [f"Nhạc nền: {credit} ({library})" if l.startswith("Nhạc nền:") and credit else l for l in lines]
    return "\n".join(out)


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from src import db, telegram_bot as tg
    from src.publish import metadata, youtube
    from src.review import load_config, _local_times

    ap = argparse.ArgumentParser()
    ap.add_argument("video_id", type=int)
    ap.add_argument("--title", default=None, help="tiêu đề mới (bỏ trống: giữ tiêu đề cũ)")
    ap.add_argument("--music-credit", default=None, help="mặc định: đọc meta.json của bản dựng lại")
    ap.add_argument("--yes", action="store_true", help="làm thật")
    a = ap.parse_args()

    cfg = load_config()
    yt = cfg["publish"]["youtube"]
    con = db.connect()
    v = dict(con.execute("SELECT * FROM videos WHERE id=?", (a.video_id,)).fetchone())
    at = db.get_state(con, f"yt_publish_at_{v['id']}")
    if v["status"] != "published" or not v["youtube_id"] or not at:
        sys.exit(f"Video #{v['id']} không ở trạng thái 'đã tải lên + đang chờ giờ hẹn' — dừng")
    if datetime.fromisoformat(at.replace("Z", "+00:00")) < datetime.now(timezone.utc) + timedelta(minutes=20):
        sys.exit(f"Còn chưa tới 20 phút là tới giờ hẹn {at} — không kịp thay an toàn, dừng")
    old = youtube.get_status(v["youtube_id"])
    if old.get("privacyStatus") != "private":
        sys.exit(f"Video cũ đang '{old.get('privacyStatus')}', không phải riêng tư chờ giờ — dừng")

    meta = json.loads((ROOT / "data" / "render" / f"audio_{v['script_id']}" / "meta.json").read_text(encoding="utf-8"))
    credit = a.music_credit or meta.get("music_credit")
    title = metadata._truncate_words(metadata._clean_line(a.title or v["title"]), metadata.TITLE_MAX)
    desc = new_description(v["description"], credit, cfg.get("music", {}).get("library", "YouTube Audio Library"))
    tags = json.loads(v["tags"]) if isinstance(v["tags"], str) else (v["tags"] or [])
    path = ROOT / v["file"]
    print(f"Video #{v['id']}: thay {v['youtube_id']} (hẹn {at}) bằng {path.name}")
    print(f"  tiêu đề: {title}\n  nhạc: {credit}")
    if not a.yes:
        print("(chưa làm gì — thêm --yes để làm thật)")
        return

    res = youtube.upload(path, title, desc, tags, yt, publish_at=at)
    db.update_video(con, v["id"], youtube_id=res["id"], youtube_url=res["url"], youtube_privacy=res["privacy"],
                    title=title, description=desc)
    db.set_state(con, f"yt_publish_at_{v['id']}", res["publish_at"])
    youtube.unschedule(v["youtube_id"])
    new_st, old_st = youtube.get_status(res["id"]), youtube.get_status(v["youtube_id"])
    ok = new_st.get("publishAt") and not old_st.get("publishAt") and old_st.get("privacyStatus") == "private"
    print(json.dumps({"new": res, "new_status": new_st, "old_status": old_st}, ensure_ascii=False, indent=1))
    tg.send_message(
        f"🔁 Đã thay video #{v['id']} bằng bản dựng lại: {res['url']}\n"
        f"Hẹn công khai lúc {_local_times(res['publish_at'], yt)} (giữ giờ cũ).\n"
        f"Bản cũ {v['youtube_url']} đã bỏ hẹn giờ, nằm riêng tư — không ai thấy; muốn xoá thì vào YouTube Studio."
        + ("" if ok else "\n⚠️ Kiểm lại trên YouTube thấy chưa đúng như mong đợi — Du xem Studio giúp."))
    if not ok:
        sys.exit("Kiểm lại trạng thái chưa đúng — xem log")


if __name__ == "__main__":
    main()
