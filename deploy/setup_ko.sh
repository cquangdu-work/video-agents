#!/usr/bin/env bash
# Cài KÊNH TIẾNG HÀN cạnh kênh Việt trên VM (20/11/2026). Chạy TỪ THƯ MỤC KÊNH VIỆT (~/video-agents):
#     bash deploy/setup_ko.sh
# Chạy lại nhiều lần được. Không đụng kênh Việt; KHÔNG tự bật lịch chạy (in lệnh để bật khi đã sẵn sàng).
#
# Bố cục: ~/video-agents-ko = bản clone của ~/video-agents (cùng code), với
#   - .env RIÊNG: CHANNEL_CONFIG=config/channel_ko.yaml (src/lang.py), bot Telegram RIÊNG (hai bot không thể
#     cùng nghe một token), không có khoá TikTok/Facebook (kênh Hàn chưa dùng);
#   - dữ liệu RIÊNG: data/ (DB, learned.yaml), .secrets/ (token YouTube của kênh Hàn), output/;
#   - DÙNG CHUNG qua liên kết: venv/ (thư viện Python), render-web/node_modules (Remotion), assets/music.
# Cập nhật code kênh Hàn sau mỗi lần đẩy code: git -C ~/video-agents-ko pull --ff-only
set -euo pipefail
VI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KO="${KO_DIR:-$HOME/video-agents-ko}"

echo "== 1/4 Mã nguồn: $KO =="
if [[ -d "$KO/.git" ]]; then
    git -C "$KO" pull -q --ff-only
else
    git clone -q "$VI" "$KO"
fi
git -C "$KO" log --oneline -1

echo "== 2/4 Dùng chung venv, node_modules, nhạc nền =="
link() {  # link <đích trong kênh Việt> <đường dẫn trong kênh Hàn>
    if [[ -e "$1" && ! -e "$2" ]]; then
        mkdir -p "$(dirname "$2")"
        ln -s "$1" "$2"
        echo "  liên kết $2 -> $1"
    fi
}
link "$VI/venv" "$KO/venv"
link "$VI/render-web/node_modules" "$KO/render-web/node_modules"
link "$VI/assets/music" "$KO/assets/music"

echo "== 3/4 .env của kênh Hàn =="
if [[ ! -f "$KO/.env" ]]; then
    # chép khoá dùng chung (Gemini, YouTube API/OAuth client, KOSIS...), bỏ thứ phải RIÊNG
    grep -v -E '^(TELEGRAM_BOT_TOKEN|TIKTOK_|FACEBOOK_|CHANNEL_CONFIG)=' "$VI/.env" > "$KO/.env"
    {
        echo ""
        echo "# --- kênh tiếng Hàn (deploy/setup_ko.sh) ---"
        echo "CHANNEL_CONFIG=config/channel_ko.yaml"
        echo "# Bot Telegram RIÊNG cho kênh Hàn (tạo bằng @BotFather), rồi điền vào đây:"
        echo "TELEGRAM_BOT_TOKEN="
    } >> "$KO/.env"
    chmod 600 "$KO/.env"
    echo "  đã tạo $KO/.env — CẦN điền TELEGRAM_BOT_TOKEN của bot mới"
else
    echo "  đã có $KO/.env (giữ nguyên)"
fi
grep -q '^CHANNEL_CONFIG=config/channel_ko.yaml' "$KO/.env" || { echo "LỖI: .env kênh Hàn thiếu CHANNEL_CONFIG"; exit 1; }
(cd "$KO" && venv/bin/python -c "from src import lang; print('  ngôn ngữ kênh:', lang.code(), '|', lang.config_path().name)")

echo "== 4/4 Lịch chạy (systemd cấp người dùng, tên có -ko) =="
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
mk() {  # mk <file mẫu> <tên mới> [sed thêm]
    sed -e "s#@REPO@#$KO#g" -e "s#video-agents:#video-agents-ko:#" ${3:+-e "$3"} "$VI/deploy/$1" > "$UNIT_DIR/$2"
}
# Giờ LỆCH kênh Việt (06:00 / 17:40 / CN 21:00) để hai bản không dựng video cùng lúc (RAM của VM)
mk video-agents-daily.service        video-agents-ko-daily.service
mk video-agents-daily.timer          video-agents-ko-daily.timer        "s#06:00:00#07:30:00#"
mk video-agents-daily-retry.service  video-agents-ko-daily-retry.service
mk video-agents-daily-retry.timer    video-agents-ko-daily-retry.timer  "s#17:40:00#18:40:00#"
mk video-agents-weekly.service       video-agents-ko-weekly.service
mk video-agents-weekly.timer         video-agents-ko-weekly.timer       "s#21:00:00#22:30:00#"
mk video-agents-review.service       video-agents-ko-review.service
# timer gọi đúng service cùng tên (-ko-) vì systemd ghép theo tên file
systemctl --user daemon-reload
echo
echo "Xong phần cài. CHƯA bật lịch chạy. Khi đã có bot Telegram mới (TELEGRAM_BOT_TOKEN trong $KO/.env):"
echo "  systemctl --user enable --now video-agents-ko-review.service"
echo "  # gửi /capquyen cho BOT MỚI, chọn kênh YouTube tiếng Hàn -> token lưu ở $KO/.secrets/"
echo "  systemctl --user enable --now video-agents-ko-daily.timer video-agents-ko-daily-retry.timer video-agents-ko-weekly.timer"
echo "Tắt hết kênh Hàn:"
echo "  systemctl --user disable --now video-agents-ko-review.service video-agents-ko-daily.timer video-agents-ko-daily-retry.timer video-agents-ko-weekly.timer"
