# Thế giới qua con số — đội agent sản xuất video ngắn

Pipeline tự động: tìm ý tưởng → chấm điểm → viết kịch bản → kiểm chứng → gửi Telegram cho Du duyệt. (Giai đoạn 1 của lộ trình trong [CLAUDE.md](CLAUDE.md).)

## Chạy

```bash
python -m venv venv
venv\Scripts\activate          # Windows (trên VM: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # rồi điền API key
python -m src.main --dry-run   # thử lấy ý tưởng, KHÔNG cần key nào
python -m src.main --no-telegram  # chạy đủ 4 agent, in kịch bản ra màn hình (cần GEMINI_API_KEY)
python -m src.main             # bản đầy đủ (cần thêm bot Telegram)
```

## Cấu trúc — mỗi file làm gì

| File | Vai trò |
|---|---|
| `config/channel.yaml` | Toàn bộ "não" cấu hình: chủ đề, nguồn, luật góc, trọng số chấm điểm. Sửa kênh = sửa file này, không đụng code. |
| `src/main.py` | Nhạc trưởng: gọi lần lượt các bước, có cờ `--dry-run`. |
| `src/sources/` | Lấy ý tưởng thô: RSS (OWID, EurekAlert, Yonhap...), arXiv API, Reddit JSON — đều **không cần API key**. Nguồn chết thì bỏ qua, không sập pipeline. |
| `src/sources/youtube_check.py` | Lớp chống trùng 2: đếm video tiếng Việt view cao cùng đề tài (cần `YOUTUBE_API_KEY`, chưa có thì tự bỏ qua). |
| `src/db.py` | Kho SQLite (`data/pipeline.db`). Vòng đời ý tưởng: `raw → candidate → selected → scripted → rejected`. Chống lặp bằng URL + độ giống tiêu đề. |
| `src/crew.py` | 4 agent CrewAI: Săn ý tưởng (ép phải có "góc"), Biên tập (chấm 5 tiêu chí × trọng số), Biên kịch (3 hook + kịch bản theo cảnh), Kiểm chứng (đối chiếu claim với bài nguồn). |
| `src/page_text.py` | Tải toàn văn bài nguồn cho agent Kiểm chứng. |
| `src/telegram_bot.py` | Gửi kịch bản đã kiểm chứng vào Telegram (gọi thẳng Bot API cho nhẹ). |
| `src/daily.py` | **Chuỗi hằng ngày**: một lệnh chạy cả dây chuyền, bước nào hỏng thì thử kịch bản kế và báo Telegram. |
| `src/analysis/weekly.py` | **Agent Phân tích**: mỗi tuần đo số liệu video, tìm cảnh người xem rời đi, nhích trọng số, rút bài học. |
| `src/analysis/learned.py` | Đọc/ghi `data/learned.yaml` — thứ kênh tự học được; Biên tập và Biên kịch đọc file này. |
| `deploy/` | Script cài VM + file systemd (lịch mỗi sáng, báo cáo Chủ nhật, bot chờ duyệt). |
| `src/review.py` | **Bước Du duyệt + agent Đăng bài**: gửi video kèm nút ✅/❌ vào Telegram, chờ nút bấm, rồi đăng. |
| `src/publish/metadata.py` | Tiêu đề / mô tả / hashtag: LLM đề xuất, code ép giới hạn YouTube, soát số trong tiêu đề, tự gắn nguồn + khai báo AI. |
| `src/publish/youtube.py` | Cấp quyền OAuth + upload YouTube (resumable), chỉ dùng `requests`. |
| `tests/` | Test không cần mạng: `python -m unittest discover -s tests` |
| `src/utils.py` | Chuẩn hóa tiêu đề, đo độ giống (Jaccard), móc JSON từ câu trả lời LLM. |

## Giới hạn hiện tại (sẽ nâng ở bước sau)
- Kiểm chứng mới đối chiếu **1 nguồn** (bài gốc); thiết kế yêu cầu 2 nguồn độc lập → cần thêm search API.
- Chưa có nguồn KOSIS/World Bank chuyên dụng (mới có OWID qua RSS).
- Duyệt Telegram mới một chiều (gửi); nút bấm duyệt/loại làm ở giai đoạn sau.

## Giai đoạn 4 — duyệt và đăng

```bash
python -m src.assemble 6        # dựng bản phát hành output/final_6.mp4
python -m src.review send 6     # kiểm định -> viết tiêu đề/mô tả -> gửi Telegram kèm nút
python -m src.review listen     # chạy nền, chờ Du bấm ✅ Duyệt đăng / ❌ Loại
```

Vòng đời video (bảng `videos`): `pending_review → approved → published` hoặc `→ rejected`.
Không có đường nào tới bước đăng mà không qua nút ✅. Bấm trùng hai lần cũng chỉ đăng một lần.
Trả lời (reply) tin nhắn video để ghi chú/lý do loại; gửi link YouTube để lưu lại cho agent Phân tích.

Hai chế độ đăng, đổi ở `config/channel.yaml` → `publish.youtube.mode`:

- **`manual` (mặc định):** sau khi duyệt, bot gửi file gốc + tiêu đề/mô tả chạm-để-copy; Du tự đăng bằng app.
- **`api`:** bot tự upload. Cần làm một lần:
  1. Google Cloud Console → tạo project → bật *YouTube Data API v3* và *YouTube Analytics API*.
  2. OAuth consent screen (External) → thêm chính mình làm test user → tạo *OAuth client ID* loại **Desktop app**.
  3. Điền `YT_CLIENT_ID`, `YT_CLIENT_SECRET` vào `.env`, chạy `python -m src.publish.youtube auth` trên laptop
     (chọn đúng kênh Brand Account), kiểm tra bằng `python -m src.publish.youtube whoami`.
  4. Lên VM: chép `.secrets/youtube_token.json` sang.

Hai cái bẫy của chế độ `api`:

- App OAuth ở trạng thái **Testing** → refresh token chết sau 7 ngày. Chuyển *Publishing status* sang **In production**.
- Tài liệu chính thức của Google ghi: video upload từ project API **chưa qua audit** bị khoá ở chế độ riêng tư,
  muốn gỡ phải nộp đơn audit. Vì vậy mặc định `privacy: private`, và bot luôn báo chế độ hiển thị THỰC TẾ
  YouTube trả về. Upload thử một video trước khi tin vào chế độ này.

## Chạy hằng ngày

```bash
python -m src.daily --dry-run     # xem sẽ chọn kịch bản nào, chạy bước nào (không chạy gì)
python -m src.daily --skip-ideas  # dùng kịch bản đã có trong DB
python -m src.daily               # cả dây chuyền: ý tưởng -> kịch bản -> video -> gửi duyệt
```

Cách chọn kịch bản: đã qua Kiểm chứng, chưa gửi duyệt, không quá `daily.max_script_age_days` ngày;
ưu tiên cái đã dựng xong video, rồi tới điểm Biên tập cao. Mỗi ngày `daily.videos_per_day` video;
chạy lại trong ngày không làm dư. Kịch bản dựng hỏng 2 lần thì bị bỏ qua. Log: `logs/daily_<ngày>.log`.

## Triển khai lên VM Oracle

Chuyển code bằng git qua SSH (không cần GitHub):

```bash
# trên VM (một lần)
git init --bare ~/video-agents.git
# trên laptop
git remote add vm ssh://<user>@<ip-vm>/~/video-agents.git
git push vm master
scp .env <user>@<ip-vm>:~/           # file bí mật không nằm trong git -> chép riêng
scp data/pipeline.db <user>@<ip-vm>:~/
# trên VM
git clone ~/video-agents.git ~/video-agents && cd ~/video-agents
mv ~/.env . && mv ~/pipeline.db data/
bash deploy/setup_vm.sh              # kiểm RAM, cài gói, tạo venv, cài systemd; hỏi trước mỗi lệnh sudo
```

Script không tự bật lịch chạy; nó in ra 3 lệnh để thử tay rồi mới bật. Cập nhật code về sau:
`git push vm master` trên laptop, `git pull` trên VM, rồi `systemctl --user restart video-agents-review`.

## Agent Phân tích (hằng tuần)

```bash
python -m src.analysis.weekly --dry-run     # in báo cáo từ số liệu đã lưu, không gọi mạng
python -m src.analysis.weekly               # đo + phân tích + báo cáo Telegram
```

- **Nguồn số liệu:** đã cấp quyền OAuth (`python -m src.publish.youtube auth`) thì lấy được % xem trung bình
  và đường giữ chân; chưa cấp thì chỉ có lượt xem/thích/bình luận công khai (qua `YOUTUBE_API_KEY`).
  Video phải có link trong DB: đăng tay thì gửi link vào Telegram cho bot.
- **Điểm rời đi:** chỗ rớt mạnh nhất sau 3 giây đầu được quy ra đúng cảnh (template + lời đọc) trong spec.
- **Trọng số Biên tập:** chỉ chỉnh khi có từ 10 video đủ 3 ngày tuổi, tương quan hạng từ 0.5 trở lên,
  mỗi tuần nhích 0.1, kẹp trong 0.5–2.5. Ít video thì báo cáo ghi rõ "chưa chỉnh".
- **Bài học:** từ 3 video trở lên, LLM rút tối đa 5 bài học; Biên kịch đọc chúng ở lần viết sau.
- Mọi thứ học được nằm trong `data/learned.yaml` (không nằm trong git). Xoá file = quay về cấu hình gốc.
