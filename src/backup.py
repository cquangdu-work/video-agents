"""SAO LƯU bộ nhớ của dây chuyền (soát 21/11/2026: chưa có bản sao lưu nào — DB chỉ nằm trên VM).

Thứ được sao lưu: DB SQLite (ý tưởng, kịch bản, video, bình luận, nhật ký tự học, phong cách dựng...) + data/learned.yaml
(mọi điều các agent đã học). Cả hai rất nhỏ (DB kênh Việt 1,7 MB ngày 21/11) nhưng là thứ không dựng lại được.
- MỖI NGÀY (đầu lượt daily): bản chụp tại chỗ data/backups/pipeline-<ngày>.db bằng sqlite3 backup API — an toàn cả
  khi bot duyệt đang đọc/ghi DB — giữ KEEP bản gần nhất. Chống DB hỏng / lỡ tay xoá.
- MỖI CHỦ NHẬT (lượt Phân tích): nén DB + learned.yaml gửi vào Telegram của Du — bản nằm NGOÀI VM, VM mất vẫn còn.
KHÔNG sao lưu .secrets (token): gửi token qua Telegram là rủi ro; mất thì cấp lại bằng /capquyen, /facebook, /tiktok.

Khôi phục: tắt bot + timer (cuối deploy/setup_vm.sh), chép file .db đè lên data/pipeline.db (và learned.yaml nếu cần),
bật lại.
"""
import logging
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import db, lang

log = logging.getLogger(__name__)
KEEP = 14


def backup_dir() -> Path:
    return Path(db.DB_PATH).parent / "backups"


def snapshot(now: datetime = None, keep: int = KEEP) -> Path:
    """Chụp DB ra data/backups/pipeline-YYYYMMDD.db (cùng ngày thì ghi đè), xoá bản cũ quá `keep` bản."""
    now = now or datetime.now(timezone.utc)
    out_dir = backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"pipeline-{now:%Y%m%d}.db"
    src = sqlite3.connect(str(db.DB_PATH))
    dst = sqlite3.connect(str(out))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(out_dir.glob("pipeline-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    log.info("Sao lưu DB -> %s", out)
    return out


def bundle(now: datetime = None) -> Path:
    """Gói zip: bản chụp DB mới nhất + learned.yaml."""
    from .analysis import learned
    now = now or datetime.now(timezone.utc)
    snap = snapshot(now)
    out = backup_dir() / f"backup-{lang.code()}-{now:%Y%m%d}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(snap, "pipeline.db")
        path = Path(learned.LEARNED_PATH)
        if path.exists():
            z.write(path, "learned.yaml")
    for old in sorted(backup_dir().glob(f"backup-{lang.code()}-*.zip"))[:-4]:
        old.unlink(missing_ok=True)
    return out


def send_weekly(now: datetime = None) -> bool:
    """Gửi gói sao lưu vào Telegram của Du (bot chỉ gửi file <= 50 MB)."""
    from . import telegram_bot as tg
    out = bundle(now)
    size = out.stat().st_size
    if size > 45 * 1024 * 1024:
        log.warning("Gói sao lưu %.1f MB quá lớn cho Telegram — chỉ giữ trên VM", size / 1e6)
        return False
    tg.send_document(out, caption=lang.pick(
        vi=f"💾 Sao lưu tuần ({size / 1e6:.1f} MB): DB + những gì các agent đã học. Giữ tin này; khôi phục: xem"
           " src/backup.py.",
        ko=f"💾 Sao lưu tuần kênh Hàn ({size / 1e6:.1f} MB): DB + những gì các agent đã học. Giữ tin này; khôi phục:"
           " xem src/backup.py."))
    return True
