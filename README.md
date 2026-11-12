# Thế giới qua con số — đội agent sản xuất video ngắn

Dây chuyền tự động chạy mỗi sáng trên VM: tìm ý tưởng → chấm điểm → viết kịch bản → kiểm chứng → dựng spec cảnh → giọng đọc + hình + phụ đề → kiểm định → gửi video vào Telegram cho Du duyệt → Du bấm ✅ thì ra gói đăng. (Lộ trình và các quyết định thiết kế nằm trong [CLAUDE.md](CLAUDE.md).)

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
| `src/sources/` | Lấy ý tưởng thô: RSS (OWID, ScienceDaily, Hankyoreh, Donga...), arXiv API, Reddit (JSON, bị chặn thì tự sang RSS) — đều **không cần API key**. Nguồn chết thì bỏ qua, không sập pipeline. |
| `src/sources/worldbank.py` | Kho dữ liệu mở World Bank, không cần key. Ba dạng ý tưởng: "Việt Nam – Hàn Quốc qua một con số" (25 chỉ số, kèm góc "Việt Nam hôm nay bằng Hàn Quốc năm nào"), "cuộc đua" 10 nền kinh tế châu Á (7 chỉ số, kèm xếp hạng và "ai vượt ai" tính sẵn), và **"bản đồ thế giới"** (12 chỉ số: Việt Nam đứng thứ mấy trong ~210 nước và vùng lãnh thổ, nơi cao nhất/thấp nhất, thứ hạng trong Đông Nam Á). Tóm tắt chính là bảng số liệu thật. |
| `src/sources/kosis.py` | KOSIS — thống kê quốc gia Hàn Quốc (cần `KOSIS_API_KEY`). Hai dạng ý tưởng: cuộc đua các cộng đồng người nước ngoài ở Hàn theo quốc tịch, và người Việt ở Hàn theo loại visa. Tự đọc cấu trúc bảng (không mã hoá cứng mã phân loại); ghi chú sẵn những chỗ dễ kể sai (KOSIS tách "Trung Quốc" và "Trung Quốc gốc Hàn"). |
| `src/sources/datatable.py` | Hàm dùng chung cho nguồn dạng bảng: viết số kiểu Việt, xếp hạng "ai vượt ai", khuôn dòng "<Tên> theo năm: ..." mà biểu đồ đọc ngược lại được. |
| `src/sources/youtube_check.py` | Lớp chống trùng 2: tìm bằng từ khóa tiếng Việt do Săn ý tưởng viết, chỉ đếm video view cao **cùng đề tài** (tiêu đề chứa phần lớn từ khóa đặc trưng). Cần `YOUTUBE_API_KEY`, chưa có thì tự bỏ qua. |
| `src/db.py` | Kho SQLite (`data/pipeline.db`). Vòng đời ý tưởng: `raw → candidate → selected → scripted → rejected`. Chống lặp bằng URL + độ giống tiêu đề. |
| `src/crew.py` | 4 agent CrewAI: Săn ý tưởng (ép phải có "góc"), Biên tập (chấm 5 tiêu chí × trọng số), Biên kịch (3 hook + kịch bản theo cảnh), Kiểm chứng (đối chiếu claim với bài nguồn). |
| `src/story.py` | **Luật kể chuyện** (code, không nhờ LLM): cấm câu mở đầu theo khuôn/câu view ("Đừng…", "Sai lầm…", "Bạn có biết…", từ giật gân), chấm điểm và **chọn câu mở đầu mạnh nhất** trong 3 phương án (phương án bịa số không được chọn), cấm mở giống video gần đây, gọt câu đệm kiểu báo cáo, bắt số viết bằng chữ và chữ Hàn sót, đo chuỗi câu có số đứng liền. |
| `src/page_text.py` | Tải toàn văn bài nguồn: Biên kịch lấy số liệu từ đó, Kiểm chứng đối chiếu lại. |
| `src/produce.py` | **Agent Sản xuất**: kịch bản → spec cảnh (`data/specs/script_<id>.yaml`). Cửa kiểm spec: bỏ cảnh hỏng, không làm tròn mất số lẻ, xoay vòng kiểu cảnh chữ. |
| `src/render/` | Engine Manim: `templates.py` là kho mẫu hình (số lớn, so găng, thanh ngang, **cuộc đua số liệu** — thanh ngang đổi chỗ qua các năm, **bản đồ châu Á** tô màu theo số liệu, đường xu hướng một hoặc nhiều đường — Việt Nam đỏ, Hàn Quốc xanh, vòng phần trăm, cảnh chữ 3 kiểu), `geo.py` đọc bản đồ và chiếu toạ độ, `base.py` là bộ nhận diện chung, `engine.py` dựng và nối cảnh. Biểu đồ đường, cuộc đua và bản đồ lấy số **thẳng từ bảng gốc** của ý tưởng, model chỉ chọn vẽ gì. |
| `assets/geo/asia.json`, `tools/build_asia_map.py` | Ranh giới các nước Đông Á – Đông Nam Á – Nam Á cắt từ Natural Earth 1:50m (phạm vi công cộng). Hoàng Sa, Trường Sa do `geo.VN_ISLANDS` vẽ thêm (Natural Earth không có ở tỷ lệ này). |
| `assets/geo/world.json`, `tools/build_world_map.py` | Bản đồ thế giới (235 nước/vùng, chiếu Equal Earth), ranh giới **theo góc nhìn Việt Nam** (cột `ADM0_A3_VN` của Natural Earth), mã ISO trùng mã World Bank, tên tiếng Việt quen dùng ("Mỹ", "Anh", "Hồng Kông (Trung Quốc)"). Bản đồ thế giới có ô phóng to Việt Nam + Biển Đông để ghi rõ tên Hoàng Sa, Trường Sa. Cảnh `map` tự chọn: mọi nước ở châu Á → bản đồ châu Á, có nước ngoài châu Á → thế giới. |
| `src/assemble.py` | **Lắp ráp bản phát hành**: giọng + hình + phụ đề + chuẩn âm lượng → `output/final_<id>.mp4`. |
| `src/audio/tts.py` | Giọng đọc Gemini TTS, tự đổi model dự phòng khi hết quota. Đổi nhà cung cấp giọng = chỉ thay file này. |
| `src/audio/batch.py` | Đọc **cả bài bằng một lần gọi TTS** rồi tự cắt theo câu (Whisper dóng chữ + đo khoảng lặng). |
| `src/audio/subtitles.py` | Whisper lấy mốc từng từ → phụ đề `.ass` theo cụm 3 từ, không vắt ngang hai câu. |
| `src/audio/music.py` | **Nhạc nền tự chọn**: đọc `assets/music/`, đoán tâm trạng lời đọc (calm/bright/serious), chọn bài ít dùng nhất 7 ngày, trộn bằng ffmpeg — có giọng thì nhạc tự nhỏ (sidechaincompress). Kho trống thì video không nhạc như cũ. |
| `src/qc.py` | **Agent Kiểm định**: độ dài, khung đen, âm lượng, giấy phép, lời đọc có khớp kịch bản không, model nhìn ảnh soát hình. |
| `src/assets_db.py` | Kho chất liệu: mỗi mẫu hình có giấy phép + nhật ký dùng, cảnh báo khi lạm dụng một mẫu. |
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
- Đã có World Bank (25 chỉ số Việt–Hàn) và KOSIS (2 bảng của Bộ Tư pháp Hàn Quốc; thêm bảng: sửa
  `sources.kosis.tables` trong `config/channel.yaml`). Số liệu KOSIS chia theo quốc tịch chỉ có từ 2022.
- Bản đồ có hai khung: châu Á và thế giới. Chưa có bản đồ một nước theo tỉnh (ví dụ 63 tỉnh Việt Nam).
- Nhạc nền: code đã xong, chờ Du chép nhạc vào `assets/music/` trên **cả laptop và VM** (nhạc không vào
  git). Đặt tên `calm - ...`, `bright - ...`, `serious - ...` — xem `assets/music/README.md`.
  Tắt nhạc: `music.enabled: false` trong `config/channel.yaml`; to/nhỏ: `music.gain_db`.
- API World Bank treo ở lần gọi đầu của mỗi truy vấn mới (máy chủ tính xong ở phía sau rồi lưu đệm):
  code gọi "đánh thức" rồi gọi lại, nên mỗi chỉ số mới có thể mất 1–2 phút.
- TikTok chưa làm (cần tài khoản developer). YouTube đang ở chế độ `manual`: bot gửi gói, Du tự đăng.
- Free tier của Gemini: giọng đọc ~15 lần gọi/ngày mỗi model. Đủ cho 1 video/ngày nhờ đọc gộp,
  nhưng muốn 2-3 video/ngày hoặc thử nghiệm nhiều thì phải tính tới gói trả phí.

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

- **`api` (Du chốt 12/11/2026):** sau khi Du bấm ✅, bot tự upload, hẹn công khai lúc 19:00 giờ Việt Nam
  (`publish_time_local`), khai báo nội dung AI (`containsSyntheticMedia`). Chưa cấp quyền YouTube thì bot
  tự lùi về gửi gói để Du tự đăng lần đó, kèm lời nhắc.
- **`manual`:** sau khi duyệt, bot gửi file gốc + tiêu đề/mô tả chạm-để-copy; Du tự đăng bằng app.

### Đăng tự động qua API — làm một lần

1. https://console.cloud.google.com → tạo project (vd "the-gioi-qua-con-so") → *APIs & Services → Library*:
   bật **YouTube Data API v3** và **YouTube Analytics API**.
2. *OAuth consent screen* (Google Auth Platform): loại **External**, điền tên app + email; thêm chính
   tài khoản Google của Du vào *Test users*. Sau đó ở *Audience* bấm **Publish app → In production**
   (để Testing thì token chết sau 7 ngày; app chưa xác minh vẫn dùng được cho chính mình, chỉ hiện
   cảnh báo "Google chưa xác minh" lúc cấp quyền → bấm *Advanced → Go to ...*).
3. *Clients → Create client* → loại **Desktop app** → lấy *Client ID* và *Client secret*.
4. Điền `YT_CLIENT_ID`, `YT_CLIENT_SECRET` vào `.env` trên **laptop và VM** (không commit).
5. Trên laptop: `python -m src.publish.youtube auth` → trình duyệt mở ra → đăng nhập → **chọn đúng kênh
   Brand Account "Thế giới qua con số"** → cho phép. Kiểm tra: `python -m src.publish.youtube whoami`.
6. Chép token lên VM: `scp .secrets/youtube_token.json <vm>:video-agents/.secrets/`
   (thư mục `.secrets/` không vào git).
**Gia hạn quyền (12/11: app đang ở Testing vì Production đòi trang chủ + chính sách quyền riêng
tư):** token sống 7 ngày. Bot nhắc trước 1 ngày; Du gửi **/capquyen** cho bot → mở link trên điện
thoại → cho phép → chép địa chỉ `http://127.0.0.1:8765/?...` (trang báo không kết nối được — đúng
vậy) gửi lại bot → bot trên VM tự lưu token mới. Không cần laptop.

**Video hẹn giờ:** quá giờ hẹn 30 phút, bot hỏi YouTube chế độ hiển thị thật; vẫn riêng tư (bị khoá
vì chưa audit) thì báo Du vào Studio bấm Công khai.

7. **Audit của YouTube API:** theo tài liệu của Google, video upload từ project API **chưa qua audit**
   bị khoá ở chế độ **riêng tư**. Trước khi audit xong: bot vẫn upload (đỡ việc tải file + gõ chữ), báo
   rõ chế độ hiển thị thực tế, Du chỉ cần vào YouTube Studio bấm Công khai. Nộp đơn audit tại
   https://support.google.com/youtube/contact/yt_api_form (mất vài tuần, cần mô tả app + chính sách
   riêng tư). Audit xong thì video tự công khai theo giờ hẹn.

### Đẩy lên TikTok (bản nháp vào hộp thư)

Sau khi Du bấm ✅, ngoài YouTube bot còn đẩy video vào **hộp thư TikTok** (`src/publish/tiktok.py`,
Content Posting API, quyền `video.upload`) và gửi chú thích chạm-để-copy. Du mở TikTok → Hộp thư →
hoàn tất, bật "Nội dung do AI tạo", đăng. Không dùng Direct Post: app chưa audit thì bài đăng thẳng
bị khoá riêng tư, và đăng thẳng đòi giao diện xác nhận riêng.

Kết nối: gửi **/tiktok** cho bot → mở link → cho phép → TikTok chuyển về
`site/tiktok-callback.html` (trang tĩnh trên GitHub Pages, chỉ hiện mã) → bấm Sao chép → dán vào
bot. Token truy cập 2 giờ, refresh token 180 ngày, tự làm mới (token xoay vòng: luôn lưu token mới).

Cấu hình app TikTok: Platform **Web**, Website/Terms/Privacy = 3 trang của site (URL prefix đã xác
minh bằng file chữ ký); **Login Kit** redirect URI = `https://cquangdu-work.github.io/thegioiquaconso/tiktok-callback.html`;
**Content Posting API** chỉ quyền `video.upload` (tắt Direct Post); bỏ mọi sản phẩm/quyền khác.
App chưa từng được duyệt thì phải thử ở **Sandbox** (tài khoản kênh là Target user) rồi mới quay
video demo nộp duyệt. Đoạn giải thích cho ô "Explain how each product and scope works"
(930/1000 ký tự):

> Thế giới qua con số uploader is a private tool used only by the owner of the Thế giới qua con số channel (a Vietnamese data-explainer channel) to send the channel's own videos to its own TikTok account. Login Kit (user.info.basic): the owner opens the authorization link sent by the channel's private Telegram bot, logs in with the channel's TikTok account and grants access. TikTok redirects to https://cquangdu-work.github.io/thegioiquaconso/tiktok-callback.html, which only displays the code for the owner to paste back to the bot; our server exchanges it for tokens. user.info.basic only shows which account is connected. Content Posting API (video.upload): after the owner approves a finished video in Telegram, the server uploads it (FILE_UPLOAD) to the owner's TikTok inbox as a draft. The owner opens TikTok, adds the caption, turns on the AI-generated content label and publishes manually. No Direct Post, no other users.

## Chạy hằng ngày

```bash
python -m src.daily --dry-run     # xem sẽ chọn kịch bản nào, chạy bước nào (không chạy gì)
python -m src.daily --skip-ideas  # dùng kịch bản đã có trong DB
python -m src.daily               # cả dây chuyền: ý tưởng -> kịch bản -> video -> gửi duyệt
```

Cách chọn kịch bản: đã qua Kiểm chứng, chưa gửi duyệt, không quá `daily.max_script_age_days` ngày;
ưu tiên cái đã dựng xong video, rồi tới điểm Biên tập cao. Mỗi ngày `daily.videos_per_day` video;
chạy lại trong ngày không làm dư. Kịch bản dựng hỏng 2 lần thì bị bỏ qua. Log: `logs/daily_<ngày>.log`.

Mỗi ngày (tính theo giờ Hàn) đúng một lượt `daily` được phép chạy tại một thời điểm (`data/daily.lock`).

### Cổng chất lượng trước khi tốn công dựng

- **Kịch bản phải đủ dài và đủ số:** `daily.min_script_words` (165 từ ≈ 48 giây) và
  `daily.min_script_numbers` (4 con số). Ngay khâu viết, kịch bản hụt chuẩn bị giữ ở `draft`
  và dây chuyền viết ý tưởng kế tiếp (`daily.extra_script_tries`).
- **Độ dài kịch bản tính từ tốc độ đọc đo thật:** `pacing.words_per_second` = 3,4 →
  60–90 giây cần 204–306 từ. Đổi giọng (`TTS_VOICE`) thì đo lại con số này.
- **Mọi con số trong lời đọc phải có trong bài nguồn:** agent Kiểm chứng (LLM) chỉ soát các
  "claims" Biên kịch tự khai, nên `crew.unsourced_numbers()` đối chiếu bằng code từng con số
  với toàn văn bài nguồn. Thiếu căn cứ thì trả về viết lại một lần; vẫn còn thì kịch bản ở
  lại `draft`. (Đã bắt được câu mở đầu tự chế "Sai lầm 99% người ăn chay mắc phải...".)
- **Ý tưởng không đọc được bài nguồn bị loại trước khi chấm điểm** (ví dụ bài Reddit bị chặn).
- **Ý tưởng từ bảng số liệu phải được kể thành chuyện:** Biên kịch nhận thêm luật riêng
  (`crew.DATA_STORY`), và kịch bản nhắc quá 5 mốc năm bị trả lại — biểu đồ đã vẽ cả chuỗi năm,
  lời đọc không đọc lại bảng.
- **Đạo diễn đồ họa được dùng số của dữ liệu nguồn** để vẽ biểu đồ (lời đọc không cần đọc hết
  từng điểm), vẫn qua cổng chống bịa số; hai con số cùng đơn vị của hai đối tượng thì thành một
  cảnh so găng.
- **Lời đọc được gỡ hashtag, emoji, đuôi "| tên kênh"** trước khi tới giọng đọc.

### Giọng đọc và quota

- **Đọc gộp:** `src/audio/batch.py` gửi cả bài trong **một** lần gọi TTS, Whisper cho mốc từng từ,
  code dóng với kịch bản để tìm chỗ ngắt câu rồi cắt vào giữa khoảng lặng thật. Hai câu model
  đọc liền một hơi thì giữ chung một đoạn giọng (hai cảnh hình chia nhau thời lượng). Chỗ nào
  không chắc thì chỉ câu đó được đọc lẻ. Tắt: `TTS_BATCH_WORDS=0`.
- **Một câu trải nhiều cảnh hình:** spec ghi cùng một `voice` ở các cảnh liền nhau, `assemble`
  đọc một lần rồi chia thời lượng (`voice_groups`, `audio_runs`).
- **Giọng đã đọc được giữ lại** trong `data/render/audio_<id>/` kèm dấu vân tay lời đọc
  (`voice.sha1`): chạy lại không tốn quota; spec đổi thì giọng cũ tự bị xoá.
- **Hết quota không tính là kịch bản hỏng:** `tts.py` đọc lý do trong lỗi 429 (quota phút: chờ
  đúng số giây API báo; quota ngày: nhảy sang `TTS_MODEL_FALLBACKS`). Hết sạch thì `assemble`
  thoát mã 75, `daily` báo "tạm dừng" qua Telegram, lượt chạy bù 17:40 làm tiếp. Quota ngày của
  Gemini hồi lúc nửa đêm giờ Thái Bình Dương (16–17h giờ Hàn).

### Kiểm định (`python -m src.qc <id>`)

Sáu phép kiểm, đạt hết mới gửi Telegram: độ dài 45–95 giây, không khung đen, âm lượng quanh
-16 LUFS, chất liệu đủ giấy phép, **lời đọc khớp kịch bản** (số từ Whisper nghe được so với số từ
kịch bản — bắt video đọc lặp/đọc cụt), và **model nhìn ảnh** soát 6 khung rải đều. Model nhìn ảnh
chỉ được báo 3 loại lỗi (sai số, ngược nghĩa, tràn khung), lỗi sai số được code đối chiếu lại,
nghi lỗi thì hỏi lại lần hai; nó sập thì không chặn video nhưng ghi rõ số cảnh chưa soát.

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

Bốn unit: `video-agents-daily` (06:00 giờ Hàn, cả dây chuyền), `video-agents-daily-retry`
(17:40, chỉ làm khi sáng chưa gửi được video — thường do hết quota giọng đọc),
`video-agents-weekly` (Chủ nhật 21:00, agent Phân tích), `video-agents-review` (bot chờ nút
bấm, chạy suốt). Xem lịch: `systemctl --user list-timers`.

DB chính thức nằm trên VM (`~/video-agents/data/pipeline.db`); DB trên laptop chỉ để thử.

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
