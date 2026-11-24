"""Hạn mức YouTube Data API — DÙNG CHUNG giữa hai kênh (24/11/2026).

Hai kênh chạy cùng một project Google (một client OAuth, một API key) nên chung một trần 10.000 đơn vị/ngày,
ngày tính theo giờ Thái Bình Dương (đặt lại lúc 0:00 PT = 17:00 giờ Hàn mùa đông). Kênh Hàn lên 2 video/ngày thì
thứ Bảy (thêm hai video dài) ước ~10.300 đơn vị — vượt trần. Bộ đếm này ghi các lệnh ĐẮT (tải video 1.600, tìm kiếm
100, hình thu nhỏ / thêm vào danh sách phát 50) vào MỘT file chung cho cả hai thư mục kênh trên VM; lệnh đọc 1 đơn vị
không đếm (chừa biên `UPLOAD_CEILING`). Tải video mà vượt trần -> bot giữ video lại, tải sau khi hạn mức đặt lại
(review.retry_quota_waits), giờ công khai vẫn theo khung giờ như thường.

Đây là ƯỚC TÍNH phía mình (giá theo bảng chi phí của YouTube Data API); số thật xem ở Google Cloud Console -> APIs &
Services -> YouTube Data API v3 -> Quotas. Lỗi đọc/ghi file không bao giờ chặn việc đăng."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

COSTS = {"upload": 1600, "search": 100, "thumbnail": 50, "insert": 50}
LIMIT = 10_000
UPLOAD_CEILING = 9_000          # chừa ~1.000 đơn vị cho các lệnh đọc 1 đơn vị (danh sách video, thống kê...)
KEEP_DAYS = 14


def path() -> Path:
    """File đếm chung: YT_QUOTA_FILE, mặc định ~/.local/share/video-agents/yt_quota.json (cùng user trên VM -> cả
    hai thư mục kênh ghi vào một chỗ)."""
    return Path(os.getenv("YT_QUOTA_FILE") or "~/.local/share/video-agents/yt_quota.json").expanduser()


def _pacific(now: datetime = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:                       # máy không có dữ liệu múi giờ (Windows thiếu tzdata): giờ chuẩn PST
        return now.astimezone(timezone(timedelta(hours=-8)))


def quota_day(now: datetime = None) -> str:
    return _pacific(now).strftime("%Y-%m-%d")


def reset_at(now: datetime = None) -> datetime:
    """Lúc hạn mức đặt lại kế tiếp (0:00 giờ Thái Bình Dương), dạng UTC."""
    p = _pacific(now)
    nxt = (p + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(timezone.utc)


def _update(fn):
    """Đọc-sửa-ghi file đếm, có khoá file (hai kênh có thể ghi cùng lúc) trên Linux."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:                 # Windows (máy phát triển): không khoá
            pass
        f.seek(0)
        try:
            data = json.loads(f.read() or "{}")
        except ValueError:
            data = {}
        out = fn(data)
        f.seek(0)
        f.truncate()
        f.write(json.dumps(data))
        return out


def spend(kind: str, n: int = 1, now: datetime = None) -> None:
    """Ghi n lệnh loại `kind` (COSTS) vào ngày hạn mức hiện tại. Lỗi -> chỉ ghi log."""
    cost = COSTS.get(kind, 1) * n
    day = quota_day(now)

    def add(data):
        data[day] = int(data.get(day, 0)) + cost
        for old in sorted(data)[:-KEEP_DAYS]:
            data.pop(old, None)
    try:
        _update(add)
    except Exception as exc:
        log.warning("Không ghi được bộ đếm hạn mức YouTube: %s", exc)


def used(now: datetime = None) -> int:
    try:
        return int(_update(lambda data: data.get(quota_day(now), 0)))
    except Exception as exc:
        log.warning("Không đọc được bộ đếm hạn mức YouTube: %s", exc)
        return 0


def can_upload(now: datetime = None) -> bool:
    return used(now) + COSTS["upload"] <= UPLOAD_CEILING
