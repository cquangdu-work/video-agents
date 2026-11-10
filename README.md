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
| `src/utils.py` | Chuẩn hóa tiêu đề, đo độ giống (Jaccard), móc JSON từ câu trả lời LLM. |

## Giới hạn hiện tại (sẽ nâng ở bước sau)
- Kiểm chứng mới đối chiếu **1 nguồn** (bài gốc); thiết kế yêu cầu 2 nguồn độc lập → cần thêm search API.
- Chưa có nguồn KOSIS/World Bank chuyên dụng (mới có OWID qua RSS).
- Duyệt Telegram mới một chiều (gửi); nút bấm duyệt/loại làm ở giai đoạn sau.
