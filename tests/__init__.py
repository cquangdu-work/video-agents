"""Test viết cho kênh VIỆT (cấu hình mặc định); phần tiếng Hàn tự bật bằng lang.using("ko"). Ép CHANNEL_CONFIG về
kênh Việt để test cho cùng kết quả ở mọi thư mục — ca thật 21/11/2026: chạy test trong ~/video-agents-ko (có .env chọn
config/channel_ko.yaml) thì 125 test đỏ vì đọc nhầm kênh. Chỉ ảnh hưởng tiến trình chạy test."""
import os

os.environ["CHANNEL_CONFIG"] = "config/channel.yaml"
# Bộ đếm hạn mức YouTube dùng chung (src/publish/yt_quota.py): test không được ghi vào file thật của VM
import tempfile as _tempfile  # noqa: E402
os.environ["YT_QUOTA_FILE"] = os.path.join(_tempfile.mkdtemp(prefix="ytq_"), "yt_quota.json")
