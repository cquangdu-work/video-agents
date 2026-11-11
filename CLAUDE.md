# Dự án: Đội AI agent tự động sản xuất video ngắn (YouTube + TikTok)

File này tổng hợp các quyết định thiết kế đã thống nhất. Đọc toàn bộ trước khi làm bất cứ việc gì.

## Bối cảnh người dùng
- Du, sinh viên ngành AI/Khoa học máy tính ở Hàn Quốc. Giao tiếp bằng tiếng Việt.
- Thời gian rảnh ít (vừa học vừa làm thêm). Muốn tự động hoá tối đa, chỉ làm những bước bắt buộc.
- Đây cũng là dự án portfolio để xin việc AI engineer remote: **giải thích ngắn gọn từng phần code bạn viết** để Du hiểu và tự sửa được.

## Mục tiêu
Một đội agent chạy theo lịch, mỗi ngày tạo video ngắn dọc (60–90 giây) để đăng lên YouTube Shorts và TikTok, kiếm tiền từ nền tảng.

## Quyết định đã chốt
- Ngôn ngữ video: **tiếng Việt** (sau này có thể thêm phụ đề/lồng tiếng Hàn, Anh để tăng người xem ở thị trường giá quảng cáo cao).
- Kênh YouTube: tạo **kênh mới dạng Brand Account**, quốc gia đặt là **Hàn Quốc** (nơi cư trú thật).
- TikTok: tài khoản đăng ký tại Hàn.
- Video được dựng từ **"chất liệu" đặc trưng riêng** của kênh (không dùng kiểu video stock ghép giọng AI). Chất liệu được chọn sao cho sinh ra tự nhiên từ chủ đề.
- Có bước người duyệt: mỗi ngày Du duyệt video qua Telegram (~5 phút). Không bỏ bước này.

## Đã chốt thêm (11/2026)
- **Chủ đề kênh: "Thế giới qua con số"** (Du chốt 10/11/2026) — biểu đồ, bản đồ động, cuộc đua số liệu dựng bằng code; nguồn mở (OWID, World Bank, KOSIS...); lồng góc Việt–Hàn.
- **Giọng đọc: Gemini TTS** (Du chốt 11/11/2026, model gemini-3.8-flash-tts, giọng đặt trong `.env` TTS_VOICE). Muốn đổi sang giọng nhân bản của Du sau này: chỉ thay `src/audio/tts.py`.
- Nhạc nền: tạm chưa dùng; khi Du tải nhạc từ YouTube Audio Library vào `assets/music/` thì nối vào `src/assemble.py` (đã chừa chỗ, dùng sidechaincompress để nhạc tự hạ khi có giọng).

## Tiêu chí của "chất liệu" tốt
1. Sinh ra tự nhiên từ nội dung.
2. Agent tạo được hoàn toàn bằng code.
3. Mỗi tập tự khác nhau vì dữ liệu khác nhau.
4. Nhìn 1 giây là nhận ra kênh.
5. Kênh khác khó bắt chước.

Kho chất liệu gồm: bộ nhận diện (màu, font, khung phụ đề, intro 1 giây), mẫu đồ hoạ chuyển động có tham số (Manim / Motion Canvas), minh hoạ cùng một phong cách, âm thanh có giấy phép thương mại rõ ràng. Mỗi chất liệu gắn thẻ và lưu trong database. Luật chống lặp: giới hạn số lần dùng một chất liệu mỗi tuần, mỗi video phải có tỷ lệ chất liệu mới tối thiểu.

## Các agent
1. **Săn ý tưởng** — chống nội dung đại trà theo 4 lớp:
   - Lấy từ nguồn gốc: thông cáo khoa học (EurekAlert, ScienceDaily), PubMed, arXiv, câu hỏi thật (r/askscience, r/explainlikeimfive, Stack Exchange, gợi ý tìm kiếm), nguồn tiếng Hàn ít kênh Việt khai thác, kho dữ liệu mở. Google Trends chỉ để đo mức quan tâm, không làm nguồn ý tưởng.
   - Kiểm tra trùng: tìm trên YouTube bằng tiếng Việt qua API; đã có nhiều video lượt xem cao thì loại hoặc chỉ giữ khi có góc mới. So với kho ý tưởng đã làm để không lặp.
   - Bắt buộc có "góc": phát hiện mới 1–2 năm gần đây, hoặc điều ngược suy nghĩ thông thường có nguồn, hoặc kết nối hai lĩnh vực. Thiếu thì loại.
   - Mỗi sáng: ~30 ý tưởng thô → 2–3 ý tưởng, kèm góc, link nguồn gốc, lý do chọn.
2. **Biên tập** — chấm điểm 1–5: độ tò mò, độ mới, kiểm chứng được, ai cũng hiểu, dễ minh hoạ. Giữ cân bằng giữa các mảng.
3. **Biên kịch** — kịch bản 60–90 giây, viết 3 phiên bản câu mở đầu để chọn cái mạnh nhất.
4. **Kiểm chứng** — mỗi thông tin đối chiếu ít nhất 2 nguồn, lưu link; sai thì trả về Biên kịch.
5. **Sản xuất** — chọn chất liệu theo từng câu kịch bản, thiếu thì gọi **Xưởng chất liệu** tạo mới; giọng đọc, phụ đề theo từng từ (khớp bằng Whisper), nhạc nền tự hạ khi có giọng, chuẩn hoá âm lượng, xuất 1080×1920, đổi cảnh mỗi 2–4 giây.
6. **Kiểm định** — kiểm tra lệch phụ đề, khung hình đen, chữ tràn, âm lượng, độ dài; dùng model nhìn ảnh xem hình có khớp lời không; lưu nhật ký nguồn/giấy phép của mọi chất liệu. Đạt mới gửi Telegram.
7. **Đăng bài** — tiêu đề, mô tả, hashtag, đánh dấu nội dung AI, đăng theo giờ tốt. TikTok có thể chỉ đẩy được vào bản nháp nếu ứng dụng chưa được TikTok duyệt.
8. **Phân tích** — mỗi tuần đọc số liệu (tỷ lệ xem hết, điểm người xem rời đi), điều chỉnh trọng số chấm điểm và cập nhật file "công thức".

Trước khi sản xuất hàng loạt: chạy phân tích đối thủ — tìm **video đột biến** (lượt xem gấp nhiều lần trung bình của chính kênh đó) trên 20–30 kênh giải thích ngắn (Việt, Hàn, Anh; ưu tiên kênh nhỏ lớn nhanh 6 tháng gần đây) qua YouTube Data API. Ghi lại câu mở đầu, kiểu tiêu đề, độ dài, nhịp cảnh, loại giọng, loại hình. Kết quả là file "công thức" mà các agent đọc.

## Luật chính sách bắt buộc (YouTube, cập nhật 7/2026)
Ba loại nội dung không được kiếm tiền:
1. Nội dung chung chung, lặp lại, theo mẫu, ít khác biệt giữa các video.
2. Nội dung gây khó chịu hoặc thao túng cảm xúc để câu view.
3. Nhân vật AI đóng vai chuyên gia đưa lời khuyên về sức khoẻ, pháp lý, tài chính, chính trị.

Vì vậy: không tự động hoá 100% (giữ bước Du duyệt), không dùng giọng máy đều đều không chỉnh, chủ đề sức khoẻ/tài chính chỉ giải thích dữ liệu, không khuyên người xem làm gì. Mọi chất liệu phải rõ giấy phép.

## Hạ tầng
- Phát triển trên máy Windows này; triển khai chạy thật trên **VM Oracle Cloud Free Tier (ARM64, Linux, tối đa 4 OCPU / 24GB RAM, không GPU)**. VM đang chạy sẵn một số dịch vụ khác: kiểm tra RAM trước khi cài thêm.
- Không chạy LLM local để suy luận cho agent (CPU ARM quá chậm). Dùng API giá rẻ / có free tier. Model ảnh trên CPU chỉ chạy hàng loạt ban đêm.
- Code phải chạy được trên cả x64 (máy này) và ARM64 (VM). Ưu tiên Docker hoặc venv + requirements rõ ràng.

## Công nghệ
Python, CrewAI (điều phối agent), cron/systemd timer (lịch chạy), bot Telegram (duyệt), ffmpeg + Manim hoặc Motion Canvas (dựng), Whisper (khớp phụ đề), SQLite/PostgreSQL (kho ý tưởng + kho chất liệu). Khoá API để trong `.env`, không commit.

## Lộ trình
1. **Giai đoạn 1:** Săn ý tưởng → Biên tập → Biên kịch → Kiểm chứng; mỗi sáng gửi 2–3 kịch bản đã kiểm chứng vào Telegram.
2. **Giai đoạn 2:** Kho chất liệu + engine dựng biểu đồ/bản đồ thành cảnh video.
3. **Giai đoạn 3:** Giọng đọc, phụ đề, nhạc, agent Kiểm định.
4. **Giai đoạn 4:** Đăng bài + agent Phân tích + triển khai lên VM Oracle.

## Tình trạng giai đoạn 4 (cập nhật 11/11/2026)
- **Xong (4.1):** duyệt hai chiều qua Telegram (`src/review.py`), agent viết tiêu đề/mô tả (`src/publish/metadata.py`), module upload YouTube (`src/publish/youtube.py`), bảng `videos` + `state` trong DB, test offline trong `tests/`.
- Phần này mới chạy với API giả lập (viết từ xa, máy không có mạng). **Chưa chạy thật** với Telegram/YouTube: việc đầu tiên khi ngồi vào laptop là `python -m src.review send 6` rồi `python -m src.review listen`.
- Chế độ đăng mặc định là `manual` (bot gửi gói, Du tự đăng). Đây là mặc định tạm, **Du chưa chốt**. Lý do: tài liệu Google ghi project API chưa audit thì video bị khoá riêng tư. Chi tiết trong README.
- **Xong (4.2):** chuỗi hằng ngày `src/daily.py` (main → produce → assemble → review send, tự thử kịch bản kế khi hỏng, báo Telegram), bộ triển khai `deploy/` (script cài VM + systemd timer 06:00 giờ Hàn + dịch vụ bot chờ duyệt). Cũng **chưa chạy thật**: `deploy/setup_vm.sh` chưa từng chạy trên VM, chưa biết các thư viện (manim, faster-whisper) cài trên ARM64 có trơn không.
- **Xong (4.3):** agent Phân tích `src/analysis/weekly.py` (đo số liệu, điểm rời đi theo cảnh, nhích trọng số, bài học cho Biên kịch) ghi vào `data/learned.yaml`; `main.load_config()` và `crew._formula_block()` đọc file đó. Chưa chạy với số liệu thật vì kênh chưa đăng video nào.
- **Chưa làm:** TikTok (cần Du đăng ký tài khoản developer trước).

## Cách làm việc
- Làm từng giai đoạn nhỏ, chạy thử được rồi mới sang bước tiếp. Commit git sau mỗi bước.
- Hỏi Du trước khi: cài dịch vụ trả phí, tạo tài khoản, đăng bất cứ thứ gì công khai, xoá dữ liệu.
- Trả lời Du bằng tiếng Việt.
