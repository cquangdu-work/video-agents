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
- **Giọng đọc: Gemini TTS** (Du chốt 11/11/2026; model đặt trong `.env` TTS_MODEL — đang dùng bản lite vì quota thoáng hơn, kèm TTS_MODEL_FALLBACKS; giọng đặt trong TTS_VOICE). Muốn đổi sang giọng nhân bản của Du sau này: chỉ thay `src/audio/tts.py`.
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

## Tình trạng giai đoạn 4 (cập nhật 12/11/2026)
- **Dây chuyền đang chạy tự động trên VM từ 12/11/2026.** Code ở `~/video-agents` (remote git `vm`, SSH alias riêng trên laptop); DB chính thức là `data/pipeline.db` trên VM (DB laptop chỉ để thử). Bốn unit systemd cấp người dùng đều đã bật: `video-agents-daily.timer` (06:00 giờ Hàn, cả dây chuyền), `video-agents-daily-retry.timer` (17:40, làm tiếp khi sáng hết quota), `video-agents-weekly.timer` (Chủ nhật 21:00), `video-agents-review.service` (bot chờ nút bấm). Tắt hết: xem cuối `deploy/setup_vm.sh`.
- **Đã chạy thật trọn vẹn** (12/11, qua chính unit systemd): ý tưởng → kịch bản → spec → 1 lần gọi TTS → video 62,9 giây → Kiểm định đạt → Telegram, hết 13 phút. Duyệt hai chiều cũng đã dùng thật: Du bấm ❌ video #1, ✅ video #2.
- **Xong (4.1):** duyệt hai chiều (`src/review.py`), tiêu đề/mô tả (`src/publish/metadata.py`), upload YouTube (`src/publish/youtube.py`, **chưa chạy thật**). Chế độ đăng vẫn là `manual` (bot gửi gói, Du tự đăng) — mặc định tạm, **Du chưa chốt**; lý do: project API chưa audit thì video bị khoá riêng tư (chi tiết trong README).
- **Xong (4.2):** chuỗi hằng ngày `src/daily.py` + bộ triển khai `deploy/`.
- **Xong (4.3):** agent Phân tích `src/analysis/weekly.py`, ghi `data/learned.yaml`. Chưa có số liệu thật vì kênh chưa đăng video nào.
- **Xong (12/11):** nguồn World Bank (25 chỉ số Việt–Hàn, xoay vòng 2 chỉ số/ngày) + biểu đồ đường hai nước trên cùng trục, số liệu do code chép từ bảng gốc. Video đầu tiên dạng này (kịch bản #17, điện tiêu thụ) đã dựng xong trên VM, đạt Kiểm định, chờ lượt 06:00 ngày 13/11 gửi duyệt.
- **Chưa làm:** TikTok (cần Du đăng ký tài khoản developer); mẫu bản đồ và "cuộc đua số liệu" (bar chart race); nhạc nền; Kiểm chứng 2 nguồn độc lập (cần search API); KOSIS (cần key).

## Những điều đã đo/đã học khi chạy thật (đừng làm lại từ đầu)
- **Quota TTS free tier ~15 lần gọi/ngày mỗi model**, hồi lúc nửa đêm giờ Thái Bình Dương (16–17h giờ Hàn). Vì vậy giọng được đọc **cả bài trong một lần gọi** rồi tự cắt theo câu (`src/audio/batch.py`); đừng quay về đọc từng câu.
- **Tốc độ đọc thật ≈ 3,4 từ/giây** (giọng Kore, tiếng Việt) → 60–90 giây cần 204–306 từ (`pacing.words_per_second`). Đổi giọng thì đo lại.
- **Model nhỏ (flash-lite) làm giám khảo rất hay báo nhầm**: mọi phán quyết của nó phải được ép khuôn (phân loại lỗi, JSON) và code đối chiếu lại; đừng cho nó quyền chặn video bằng một nhận xét tự do.
- **Model dự phòng trả lời sai khuôn** (mảng thay vì object) khi Gemini quá tải 503 — ban đêm giờ Hàn hay gặp. Mọi chỗ đọc JSON từ LLM phải chịu được điều này.
- **Phụ đề phải lấy chữ từ kịch bản**, Whisper chỉ cho mốc thời gian (Whisper nghe nhầm "phàn nàn" thành "phan an").
- **Reddit chặn IP của VM** ở đường JSON và trang HTML; chỉ RSS vào được và bị giới hạn tần suất. Bài Reddit vì thế không đọc được nguồn và bị loại trước khi chấm điểm.
- **Kịch bản phải qua cổng chuẩn** trước khi được dựng: đủ từ, ít nhất 4 con số viết bằng chữ số, Kiểm chứng đạt. Biên kịch được đưa toàn văn bài nguồn chứ không chỉ đoạn tóm tắt RSS.
- **Nguồn World Bank (12/11)** cho ý tưởng giàu số nhất; ý tưởng từ bảng số phải được kể thành chuyện (luật `DATA_STORY`, chặn kịch bản nhắc quá 5 mốc năm) — bản đầu tiên đọc 9 mốc năm x 2 nước như đọc bảng.
- **Lớp chống trùng YouTube phải xét cùng đề tài**: đếm mọi video view cao trong kết quả tìm kiếm thì "…Việt Nam và Hàn Quốc…" ra toàn video bóng đá, ý tưởng bị loại oan.
- **Agent Kiểm chứng bằng LLM không đủ để chặn số bịa**: nó chỉ soát danh sách "claims" Biên kịch tự khai. Đã lọt câu mở đầu "Sai lầm 99% người ăn chay..." (kịch bản #10) và ba con số không có trong nguồn ở kịch bản #6 (video #2, Du đã duyệt trước khi có cổng này). Từ 12/11 code đối chiếu TỪNG con số trong lời đọc với bài nguồn (`crew.unsourced_numbers`); đừng gỡ cổng này.

## Cách làm việc
- Làm từng giai đoạn nhỏ, chạy thử được rồi mới sang bước tiếp. Commit git sau mỗi bước.
- Hỏi Du trước khi: cài dịch vụ trả phí, tạo tài khoản, đăng bất cứ thứ gì công khai, xoá dữ liệu.
- Trả lời Du bằng tiếng Việt.
