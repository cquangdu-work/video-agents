#!/usr/bin/env bash
# Cài đặt dự án trên VM Oracle (Ubuntu ARM64). Chạy TỪ THƯ MỤC DỰ ÁN trên VM:
#     bash deploy/setup_vm.sh
# Chạy lại nhiều lần được (không phá gì). Script HỎI trước mỗi việc cần sudo
# và KHÔNG tự bật lịch chạy — cuối cùng in ra lệnh để Du tự bật khi đã thử xong.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

ask() {  # ask "câu hỏi" -> trả về 0 nếu Du gõ y
    read -r -p "$1 [y/N] " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]]
}

echo "== 1/5 Kiểm tra tài nguyên (VM đang chạy dịch vụ khác) =="
avail_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
disk_mb=$(df -Pm "$REPO" | awk 'NR==2 {print $4}')
echo "RAM còn trống: ${avail_mb} MB   |   Ổ đĩa còn trống: ${disk_mb} MB   |   CPU: $(uname -m)"
if (( avail_mb < 3000 )); then
    echo "CẢNH BÁO: RAM trống dưới 3 GB. Whisper + Manim cần khoảng 2-3 GB lúc dựng video."
    ask "Vẫn tiếp tục?" || exit 1
fi
if (( disk_mb < 6000 )); then
    echo "CẢNH BÁO: ổ đĩa trống dưới 6 GB (thư viện Python ~3 GB, model Whisper ~0.5 GB)."
    ask "Vẫn tiếp tục?" || exit 1
fi

echo
echo "== 2/5 Gói hệ thống =="
PKGS="python3-venv python3-dev build-essential pkg-config ffmpeg libcairo2-dev libpango1.0-dev fonts-noto-core"
if ! command -v apt-get >/dev/null; then
    echo "Máy này không dùng apt. Hãy tự cài các gói tương đương rồi chạy lại: $PKGS"
    exit 1
fi
missing=""
for p in $PKGS; do
    dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
done
if [[ -n "$missing" ]]; then
    echo "Cần cài:$missing"
    ask "Chạy 'sudo apt-get install' cho các gói trên?" || exit 1
    sudo apt-get update
    # shellcheck disable=SC2086
    sudo apt-get install -y $missing
else
    echo "Đủ rồi."
fi

echo
echo "== 3/5 Môi trường Python (venv) =="
[[ -d venv ]] || python3 -m venv venv
venv/bin/pip install --upgrade pip >/dev/null
venv/bin/pip install -r requirements.txt
venv/bin/python -m unittest discover -s tests 2>&1 | tail -3

echo
echo "== 4/5 Kiểm tra file bí mật và dữ liệu =="
ok=1
[[ -f .env ]] || { echo "THIẾU .env  -> chép từ laptop sang (scp)"; ok=0; }
[[ -f data/pipeline.db ]] || echo "Chưa có data/pipeline.db -> sẽ tự tạo DB trống (nên chép từ laptop để giữ kho ý tưởng cũ)"
[[ -f .secrets/youtube_token.json ]] || echo "Chưa có .secrets/youtube_token.json -> chỉ cần nếu dùng mode api"
(( ok )) || { echo "Bổ sung file thiếu rồi chạy lại script."; exit 1; }
chmod 600 .env
[[ -d .secrets ]] && chmod 700 .secrets

echo
echo "== 5/5 Cài lịch chạy (systemd cấp người dùng) =="
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
for f in video-agents-daily.service video-agents-daily.timer video-agents-review.service \
         video-agents-weekly.service video-agents-weekly.timer; do
    sed "s|@REPO@|$REPO|g" "deploy/$f" > "$UNIT_DIR/$f"
done
systemctl --user daemon-reload
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
    echo "Cần bật 'linger' để dịch vụ vẫn chạy khi Du không đăng nhập SSH."
    ask "Chạy 'sudo loginctl enable-linger $USER'?" && sudo loginctl enable-linger "$USER"
fi

cat <<MSG

XONG PHẦN CÀI ĐẶT. Chưa có gì tự chạy. Làm lần lượt:

  1. Thử từng khâu bằng tay:
       venv/bin/python -m src.daily --dry-run
       venv/bin/python -m src.daily --skip-ideas
  2. Bật bot chờ duyệt (chạy suốt):
       systemctl --user enable --now video-agents-review.service
  3. Khi đã ưng, bật lịch chạy mỗi sáng và báo cáo mỗi Chủ nhật:
       systemctl --user enable --now video-agents-daily.timer video-agents-weekly.timer

  Xem lịch:   systemctl --user list-timers
  Xem log:    journalctl --user -u video-agents-daily -n 50     (và thư mục logs/)
  Tắt hết:    systemctl --user disable --now video-agents-daily.timer video-agents-weekly.timer video-agents-review.service
MSG
