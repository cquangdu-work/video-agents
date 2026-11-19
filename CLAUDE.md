# Dự án: Đội AI agent tự động sản xuất video ngắn (YouTube + TikTok)

File này tổng hợp các quyết định thiết kế đã thống nhất. Đọc toàn bộ trước khi làm bất cứ việc gì.

## Bối cảnh người dùng
- Du, sinh viên ngành AI/Khoa học máy tính ở Hàn Quốc. Giao tiếp bằng tiếng Việt.
- Thời gian rảnh ít (vừa học vừa làm thêm). Muốn tự động hoá tối đa, chỉ làm những bước bắt buộc.
- Đây cũng là dự án portfolio để xin việc AI engineer remote: **giải thích ngắn gọn từng phần code bạn viết** để Du hiểu và tự sửa được.

## Mục tiêu
Một đội agent chạy theo lịch, mỗi ngày tạo video ngắn dọc (**45–60 giây**, Du chốt 19/11/2026; trước là 60–90) để đăng lên YouTube Shorts và TikTok, kiếm tiền từ nền tảng.

## Quyết định đã chốt
- Ngôn ngữ video: **tiếng Việt** (sau này có thể thêm phụ đề/lồng tiếng Hàn, Anh để tăng người xem ở thị trường giá quảng cáo cao).
- Kênh YouTube: tạo **kênh mới dạng Brand Account**, quốc gia đặt là **Hàn Quốc** (nơi cư trú thật).
- TikTok: tài khoản đăng ký tại Hàn.
- Video được dựng từ **"chất liệu" đặc trưng riêng** của kênh (không dùng kiểu video stock ghép giọng AI). Chất liệu được chọn sao cho sinh ra tự nhiên từ chủ đề.
- Có bước người duyệt: mỗi ngày Du duyệt video qua Telegram (~5 phút). Không bỏ bước này.

## Đã chốt thêm (11/2026)
- **Chủ đề kênh: "Thế giới qua con số"** (Du chốt 10/11/2026) — biểu đồ, bản đồ động, cuộc đua số liệu dựng bằng code; nguồn mở (OWID, World Bank, KOSIS...); lồng góc Việt–Hàn.
- **Giọng đọc: Gemini TTS** (Du chốt 11/11/2026; model đặt trong `.env` TTS_MODEL — đang dùng bản lite vì quota thoáng hơn, kèm TTS_MODEL_FALLBACKS; giọng đặt trong TTS_VOICE). Muốn đổi sang giọng nhân bản của Du sau này: chỉ thay `src/audio/tts.py`.
- Nhạc nền: **code xong 12/11/2026** (`src/audio/music.py`, nối trong `src/assemble.py`): tự chọn bài theo tâm trạng lời đọc (tiền tố tên file `calm`/`bright`/`serious`), xoay vòng theo nhật ký kho chất liệu, sidechaincompress hạ nhạc khi có giọng, có test đo bằng số. Du đã tải 12 bài YouTube Audio Library (12/11, 5 calm / 4 bright / 3 serious) vào `assets/music/` trên laptop + VM (không vào git). Mỗi bài được đo độ to và đưa về -27 LUFS (các bài chênh nhau 17 dB); mô tả video tự ghi công tên bài + tác giả. Kho trống = video không nhạc.

## Tiêu chí của "chất liệu" tốt
1. Sinh ra tự nhiên từ nội dung.
2. Agent tạo được hoàn toàn bằng code.
3. Mỗi tập tự khác nhau vì dữ liệu khác nhau.
4. Nhìn 1 giây là nhận ra kênh.
5. Kênh khác khó bắt chước.

Kho chất liệu gồm: bộ nhận diện (màu, font, khung phụ đề, logo nhỏ ở góc — thẻ intro 1 giây đã bỏ từ 19/11/2026), mẫu đồ hoạ chuyển động có tham số (Manim / Motion Canvas), minh hoạ cùng một phong cách, âm thanh có giấy phép thương mại rõ ràng. Mỗi chất liệu gắn thẻ và lưu trong database. Luật chống lặp: giới hạn số lần dùng một chất liệu mỗi tuần, mỗi video phải có tỷ lệ chất liệu mới tối thiểu.

## Các agent
1. **Săn ý tưởng** — chống nội dung đại trà theo 4 lớp:
   - Lấy từ nguồn gốc: thông cáo khoa học (EurekAlert, ScienceDaily), PubMed, arXiv, câu hỏi thật (r/askscience, r/explainlikeimfive, Stack Exchange, gợi ý tìm kiếm), nguồn tiếng Hàn ít kênh Việt khai thác, kho dữ liệu mở. Google Trends chỉ để đo mức quan tâm, không làm nguồn ý tưởng.
   - Kiểm tra trùng: tìm trên YouTube bằng tiếng Việt qua API; đã có nhiều video lượt xem cao thì loại hoặc chỉ giữ khi có góc mới. So với kho ý tưởng đã làm để không lặp.
   - Bắt buộc có "góc": phát hiện mới 1–2 năm gần đây, hoặc điều ngược suy nghĩ thông thường có nguồn, hoặc kết nối hai lĩnh vực. Thiếu thì loại.
   - Mỗi sáng: ~30 ý tưởng thô → 2–3 ý tưởng, kèm góc, link nguồn gốc, lý do chọn.
2. **Biên tập** — chấm điểm 1–5: độ tò mò, độ mới, kiểm chứng được, ai cũng hiểu, dễ minh hoạ. Giữ cân bằng giữa các mảng.
3. **Biên kịch** — kịch bản 45–60 giây, viết 3 phiên bản câu mở đầu để chọn cái mạnh nhất.
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

**Bản đồ** (Claude đặt 12/11/2026, Du có thể đổi): bản đồ nào có Việt Nam cũng phải thể hiện quần đảo Hoàng Sa và Trường Sa thuộc Việt Nam (cùng màu Việt Nam, có tên) — luật Đo đạc và Bản đồ của Việt Nam yêu cầu, và khán giả Việt sẽ phản ứng ngay nếu thiếu. Natural Earth 1:50m không vẽ hai quần đảo nên `src/render/geo.py` (`VN_ISLANDS`) tự vẽ; có test chốt chặn. Bản đồ thế giới quá nhỏ để ghi tên nên có ô phóng to (`geo.INSET_BBOX`). Ranh giới thế giới theo góc nhìn Việt Nam (Kosovo trong Serbia, Bắc Síp trong Síp...); Hồng Kông, Ma Cao, Đài Loan ghi kèm "(Trung Quốc)".

## Hạ tầng
- Phát triển trên máy Windows này; triển khai chạy thật trên **VM Oracle Cloud Free Tier (ARM64, Linux, tối đa 4 OCPU / 24GB RAM, không GPU)**. VM đang chạy sẵn một số dịch vụ khác: kiểm tra RAM trước khi cài thêm.
- Không chạy LLM local để suy luận cho agent (CPU ARM quá chậm). Dùng API giá rẻ / có free tier. Model ảnh trên CPU chỉ chạy hàng loạt ban đêm.
- Code phải chạy được trên cả x64 (máy này) và ARM64 (VM). Ưu tiên Docker hoặc venv + requirements rõ ràng.
- Từ 19/11/2026 cả hai máy chạy **Python 3.13**; phiên bản thư viện chốt trong `requirements.lock` (tạo lại: lệnh ở đầu file, cần uv). Trên VM: venv tạo bằng uv (Python của uv nằm trong thư mục người dùng), Remotion chạy bằng Node 24 riêng (`REMOTION_NODE_DIR`).

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
- **Xong (4.1):** duyệt hai chiều (`src/review.py`), tiêu đề/mô tả (`src/publish/metadata.py`), upload YouTube (`src/publish/youtube.py`, **chưa chạy thật**). **Du chốt 12/11: đăng tự động qua API** (`mode: api`, công khai, hẹn 19:00 giờ VN) — vẫn chỉ sau khi Du bấm ✅. Chưa cấp quyền YouTube thì bot tự lùi về gửi gói tự đăng. **Đã cấp quyền thật 12/11** (token ở `.secrets/youtube_token.json` trên laptop + VM, kênh <channel-id>), upload thử riêng tư chạy được (video thử `SrfwS90-_Ec`, Du xoá được). App OAuth đã **In production** (12/11, chưa xác minh — không cần vì chỉ Du dùng; trang chủ/chính sách/điều khoản ở https://cquangdu-work.github.io/thegioiquaconso/, nguồn trong `site/`) → hết giới hạn token 7 ngày. Token hỏng thì Du gửi `/capquyen` trên Telegram (đã dùng thật 12/11). Project chưa audit thì video bị khoá riêng tư; bot soát sau giờ hẹn và báo.
- **Xong (4.2):** chuỗi hằng ngày `src/daily.py` + bộ triển khai `deploy/`.
- **Xong (4.3):** agent Phân tích `src/analysis/weekly.py`, ghi `data/learned.yaml`. Chưa có số liệu thật vì kênh chưa đăng video nào.
- **Xong (12/11):** nguồn World Bank (25 chỉ số Việt–Hàn, xoay vòng 2 chỉ số/ngày) + biểu đồ đường hai nước trên cùng trục, số liệu do code chép từ bảng gốc. Video đầu tiên dạng này (kịch bản #17, điện tiêu thụ) đã dựng xong trên VM, đạt Kiểm định, chờ lượt 06:00 ngày 13/11 gửi duyệt.
- **Xong (12/11, chiều):** "cuộc đua số liệu" (`bar_race`) 10 nền kinh tế châu Á từ World Bank, số do code điền từ bảng. Hai video đã dựng sẵn trên VM, đạt Kiểm định, xếp hàng gửi duyệt: #18 (cuộc đua GDP đầu người) sáng 13/11, #17 (điện tiêu thụ Việt–Hàn) sáng 14/11. Cả hai đi tắt (bỏ qua Săn ý tưởng/Biên tập nên điểm = 0).
- **Xong (12/11):** mẫu bản đồ châu Á (`map`, choropleth từ Natural Earth), tự dùng cho ý tưởng có bảng từ 3 nước.
- **Xong (12/11):** nguồn KOSIS (`src/sources/kosis.py`, key đã có trong `.env` laptop + VM): người nước ngoài ở Hàn theo quốc tịch (cuộc đua) và người Việt ở Hàn theo loại visa. Cảnh hỏng có lời đọc giờ thành cảnh chữ giữ lời thay vì bị bỏ.
- **Xong (12/11, tối):** bản đồ thế giới (`assets/geo/world.json`, ranh giới theo góc nhìn Việt Nam qua cột `ADM0_A3_VN` của Natural Earth, ô phóng to Biển Đông ghi tên Hoàng Sa/Trường Sa) + dạng ý tưởng World Bank "Việt Nam đứng thứ mấy thế giới" (`sources.worldbank.world`, 1 chỉ số/ngày). Bảng mọi nước nằm cuối tóm tắt, code đọc lại để tô bản đồ; thứ hạng trên hình và trong lời cùng một hàm `datatable.ranks_desc`.
- **TikTok (12/11):** chạy thật trên **Sandbox** — app Web, Login Kit redirect về `site/tiktok-callback.html`, token của tài khoản kênh trên VM (`.secrets/tiktok_token.json`, refresh token xoay vòng: KHÔNG chép sang laptop, hai máy cùng làm mới sẽ làm hỏng nhau); đẩy thử video #7 vào hộp thư thành công (20 giây). **Chốt 17/11/2026: GIỮ Sandbox, KHÔNG nộp duyệt Production** — Sandbox đã đủ cho quy trình hộp thư (tài khoản kênh là Target user; bài Du tự đăng từ bản nháp hiện công khai bình thường, đã kiểm với video #7), còn quy định duyệt app của TikTok cấm app dùng riêng/cá nhân nên gần như chắc bị từ chối. Production chỉ cần nếu muốn Direct Post (đăng thẳng) — trái nguyên tắc Du duyệt bước cuối.
- **Engine dựng hình Remotion `render-web/` — Du chốt dùng 16/11/2026** (Du chê hình cũ "hơi chán so với kênh khác", xem demo #30 rồi duyệt). `config/channel.yaml` `render.engine: web`; `src/assemble.py` làm tiếng + mốc từng từ trước, `src/render/web.py` dịch spec (KHÔNG đổi Biên kịch/Sản xuất) thành props, Remotion vẽ cả video; lỗi thì tự lùi về Manim. Biểu đồ chính sống xuyên cảnh (`ChartWorld`), cảnh so găng/số lớn chỉ gắn vào điểm số liệu khi khớp DUY NHẤT; nhãn chỉ hiện số thật trong bảng. Bản đồ và cuộc đua cũng đã chuyển (16/11, `src/render/web_map.py` giữ phần địa lý + test Hoàng Sa/Trường Sa); line_chart thứ hai khác số liệu thành biểu đồ riêng của cảnh; chỉ cảnh số liệu hỏng mới dựng Manim lồng vào. Tiêu đề video bị trả lại nếu bỏ mất đơn vị tỷ lệ/bình quân (`metadata.title_drops_unit`, ca thật video #6 "Vốn FDI… gấp 5,06 lần" khi số là % GDP). Chạy thử không đè video thật: `python -m src.assemble <id> --out data/tmp/x.mp4`. Du dùng gói Claude **Pro** (không có tín dụng API): Claude Code viết mẫu lúc phát triển, VM chỉ render; không chạy agent Claude tự động trên VM. Không dùng nguyên bộ OpenMontage (chạy tương tác, dựa ảnh AI/stock, AGPL).
- **Hướng kiếm tiền (Du chốt 17/11/2026: "làm tất cả, từng bước", giữ mọi thứ miễn phí):** ngưỡng YPP từ 1/2/2027 là 1.000 sub + 8.000 giờ xem/năm hoặc 20 triệu lượt Shorts/90 ngày -> ưu tiên nhánh giờ xem. (1) **Xong 17/11:** video dài hằng tuần `src/longform.py` (thứ Bảy 09:30 giờ Hàn, `video-agents-longform.timer`): ghép Shorts đã đăng trong 7 ngày thành video 16:9 nhiều chương (`render-web/src/Wide.tsx`), tiếng lấy từ bản phát hành (không tốn TTS), Shorts đời Manim tự dựng lại bằng `assemble --out`; duyệt/đăng chung luồng Shorts (bảng videos, script_id rỗng), không đẩy TikTok; Telegram nhận bản xem trước nén nhẹ. Video dài đầu tiên #9 (6,2 phút, 5 chương) gửi duyệt 17/11. (2) kênh tiếng Hàn, (3) Facebook Reels + TikTok bản chính thức — cần Du tạo tài khoản/quyết. (4) `docs/PORTFOLIO.md` (tiếng Anh, cho nhà tuyển dụng); đưa repo lên GitHub công khai phải hỏi Du + rà dữ liệu cá nhân trong lịch sử commit.
- **Mở rộng chủ đề (18/11, Du xin "thêm chủ đề, đừng chỉ Việt–Hàn"):** nguồn Our World in Data `src/sources/owid.py` (17 bảng trong `sources.owid.charts`: khí hậu, năng lượng, thực phẩm, xe điện, cà phê, lúa gạo, giờ làm việc..., 2 bảng/ngày, dạng bản đồ thế giới hoặc cuộc đua, chỉ neo Việt Nam). Cân bằng mảng bằng code (`datatable.topic_family`: viet-han / the-gioi / bai-bao): Biên tập xếp xen kẽ mảng (`main.balance_families`), daily không làm cùng mảng hai ngày liền nếu còn lựa chọn (`daily.streak`). World Bank Việt–Hàn còn 1 chỉ số/ngày. Thêm bảng mới: thêm dòng vào config, kiểm slug tại ourworldindata.org/grapher/<slug>. Chạy thử 18/11 trên VM: 3 ý tưởng OWID qua Săn ý tưởng/Biên tập/chống trùng YouTube; kịch bản xe điện #45 (Việt Nam hạng 10 -> hạng 2 trong 10 nền kinh tế lớn) dựng xong 84,5 giây, Kiểm định đạt, xếp hàng gửi duyệt sáng 19/11. Cuộc đua OWID chọn nhóm nước nên tóm tắt phải nói rõ "hạng trong nhóm" + hạng thế giới thật (bản đầu Biên kịch viết "hạng 2 toàn cầu", thật là 10/59).
- **Kiểm tra + nâng cấp (19/11/2026, Du xin "kiểm tra dự án trên VM, nâng cấp tất cả"):** VM khoẻ (timer đúng giờ, token YouTube/TikTok còn hạn, YouTube Analytics đã có số). Sửa: cổng code soát câu so sánh `src/claims.py` (nối vào chọn hook, Biên kịch, main, daily); agent Kiểm chứng soát TỪNG câu lời đọc + lượt hỏi thứ hai xác nhận; chỉ số tỷ lệ % nói thay đổi bằng điểm phần trăm (`worldbank.change_phrase`); `assemble.fit_tempo` đọc nhanh tối đa 1,12 lần cho video vừa 90 giây; Reddit tắt; bot duyệt ghi nhật ký. Nâng: venv VM lên **Python 3.13** (uv, thư viện theo `requirements.lock`; venv Python 3.10 cũ giữ ở `venv-py310` để lùi), **Node 24 riêng** cho Remotion ở `~/.local/node24` (khai trong `.env` `REMOTION_NODE_DIR`; Node 20 hệ thống giữ nguyên vì dịch vụ khác dùng chung), Remotion 4.0.545, crewai 1.15.42, manim 0.22 (so ảnh 10 mẫu với bản cũ: giống hệt).
- **Nâng chất lượng kịch bản + video (19/11/2026, Du duyệt đề xuất dựa trên số liệu giữ chân người xem của video #6, #7):** Du chốt **45–60 giây** (`channel.video_seconds_*`) và **bỏ thẻ intro** (`render.intro: false`, logo nhỏ ở góc — `Story.tsx` `CornerLogo`). Dàn bài mới: hook → chứng minh ngay → 2–3 điểm nhấn → ngã rẽ → câu kết quay lại hook; code kiểm 15 giây đầu và câu kết (`story.opening_problems`, `ending_problem`; lỗi "chặn" vs "nhắc", cổng cuối của main chỉ xét lỗi chặn). Bảng số có mục **"Điểm nhấn"** và **"Cách nói dễ hình dung"** do code tính (`datatable.story_beats`, `relatable_line`; cấu hình `per`/`period` ở từng chỉ số). Câu nêu nguyên nhân mà bảng số không nói bị chặn (`claims.cause_claims`). Hình: tiêu đề cảnh mở đầu hiện đủ ngay khung đầu (`HookContext`), cảnh chữ giữ biểu đồ chính ở nửa dưới (`compact`). Kiểm định 35–95 giây (`qc`; trần 95 cho kịch bản khổ cũ trong mấy ngày chuyển đổi, daily xếp chúng sau cùng). Báo cáo tuần thêm "qua vài giây đầu X%" (engaged views, cột mới `video_stats.engaged_views`) và mức mất người xem theo loại cảnh.
- **Chưa làm:** Kiểm chứng 2 nguồn cho bài báo (tìm kiếm web qua Gemini cần bật tính phí — chờ Du quyết; số liệu World Bank đã có nguồn 2 là Our World in Data, `src/second_source.py`); bản đồ một nước theo tỉnh.

## Những điều đã đo/đã học khi chạy thật (đừng làm lại từ đầu)
- **Quota TTS free tier ~15 lần gọi/ngày mỗi model**, hồi lúc nửa đêm giờ Thái Bình Dương (16–17h giờ Hàn). Vì vậy giọng được đọc **cả bài trong một lần gọi** rồi tự cắt theo câu (`src/audio/batch.py`); đừng quay về đọc từng câu.
- **Tốc độ đọc thật ≈ 3,4 từ/giây** (giọng Kore, tiếng Việt) → 45–60 giây cần 153–204 từ (trước 19/11: 60–90 giây, 204–306 từ) (`pacing.words_per_second`). Đổi giọng thì đo lại.
- **Model nhỏ (flash-lite) làm giám khảo rất hay báo nhầm**: mọi phán quyết của nó phải được ép khuôn (phân loại lỗi, JSON) và code đối chiếu lại; đừng cho nó quyền chặn video bằng một nhận xét tự do.
- **Model dự phòng trả lời sai khuôn** (mảng thay vì object) khi Gemini quá tải 503 — ban đêm giờ Hàn hay gặp. Mọi chỗ đọc JSON từ LLM phải chịu được điều này.
- **Phụ đề phải lấy chữ từ kịch bản**, Whisper chỉ cho mốc thời gian (Whisper nghe nhầm "phàn nàn" thành "phan an").
- **Reddit chặn IP của VM** ở đường JSON và trang HTML; chỉ RSS vào được và bị giới hạn tần suất. Bài Reddit vì thế không đọc được nguồn và bị loại trước khi chấm điểm.
- **Kịch bản phải qua cổng chuẩn** trước khi được dựng: đủ từ, ít nhất 4 con số viết bằng chữ số, Kiểm chứng đạt. Biên kịch được đưa toàn văn bài nguồn chứ không chỉ đoạn tóm tắt RSS.
- **Nguồn World Bank (12/11)** cho ý tưởng giàu số nhất; ý tưởng từ bảng số phải được kể thành chuyện (luật `DATA_STORY`, chặn kịch bản nhắc quá 5 mốc năm) — bản đầu tiên đọc 9 mốc năm x 2 nước như đọc bảng.
- **Render chậm thường do tạo chữ mỗi khung hình**: `pick_font()` từng liệt kê font cả máy ở mỗi khung của cảnh đếm số (cảnh số lớn 10 giây mất 327 giây). Đã lưu kết quả; mẫu mới đừng gọi hàm nặng bên trong `always_redraw`.
- **Model chép chuỗi số rất hay sai**: biểu đồ đường và cuộc đua phải lấy số bằng code từ bảng gốc (`crew.fill_series_from_data`), model chỉ chọn vẽ gì.
- **Lớp chống trùng YouTube phải xét cùng đề tài**: đếm mọi video view cao trong kết quả tìm kiếm thì "…Việt Nam và Hàn Quốc…" ra toàn video bóng đá, ý tưởng bị loại oan.
- **API World Bank với truy vấn "mọi nước"** (12/11): chưa có trong bộ đệm thì máy chủ tính mất vài phút (treo, rồi 502), xong thì trả trong 0,2 giây — `WORLD_TIMEOUTS` chờ tới ~9 phút. Hôm đó API số liệu còn sập 502 cả buổi chiều; code tự bỏ qua, đừng coi là lỗi code.
- **Cảnh nhiều chi tiết cần đủ thời gian** (chạy thử #7 trên laptop): bản đồ thế giới chia câu mở đầu với cảnh chữ chỉ còn 2,3 giây. `crew.short_rich_scenes` (≥ 5 giây cho map/bar_race) + `make_room_for_rich`; trần lời bản đồ ×1,5.
- **Kịch bản theo mẫu** (đo 18 kịch bản trên VM, 12/11): 11/18 câu mở đầu chép khuôn "Đừng… nữa!"/"Sai lầm…" của `config/formula.yaml` — vừa "nội dung theo mẫu" vừa câu view (2 loại không được kiếm tiền). Dàn bài cũ "mỗi con số một cảnh" làm kịch bản đọc số như đọc bảng. Từ 12/11: `src/story.py` cấm khuôn đó, máy chọn câu mở đầu mạnh nhất trong 3 phương án, cấm lặp cách mở của 8 video gần đây; khuôn câu view bị lọc khỏi công thức đối thủ trước khi đưa model. Đừng đưa lại khuôn tiêu đề vào prompt Biên kịch.
- **Bảo model "viết văn nói" thì nó viết số bằng chữ** ("bảy mươi ba phần trăm") — lọt qua mọi cổng đối chiếu số. Prompt phải nói rõ số vẫn viết chữ số; `story.spelled_numbers` bắt và trả về viết lại.
- **Tìm kiếm Google qua Gemini (grounding) không có ở gói miễn phí** (đo 12/11/2026: gemini-3.5-flash-lite báo 429 hạn mức 0; gemini-2.5-flash-lite "không mở cho người dùng mới"). Nguồn thứ hai miễn phí cho số liệu: Our World in Data — nhưng nhiều chuỗi OWID chép lại World Bank, chỉ dùng chuỗi có gốc khác.
- **Bảng `videos` có dòng `script_id` rỗng** (video dài hằng tuần, từ 17/11). Truy vấn `… NOT IN (SELECT script_id FROM videos …)` gặp NULL thì ra rỗng: sáng 18/11 có 3 kịch bản đạt mà daily báo "0 video" (sửa trong `src/daily.py`, có test). Truy vấn mới trên bảng này phải tính tới NULL; đếm "video hôm nay" chỉ tính Shorts.
- **Chống trùng bằng độ giống tiêu đề không hợp với ý tưởng bảng số** (18/11): tiêu đề cùng khuôn ("Bản đồ thế giới: … — Việt Nam thứ …") nên "lượng thịt" và "lượng cá" giống nhau 0,8; 19 cặp bản đồ World Bank từng bị loại oan. Ý tưởng bảng số chỉ chống trùng bằng URL (`db.insert_raw_ideas`).
- **`world.json` từng ghi Úc là "Quần đảo Ashmore và Cartier"** (vùng phụ thuộc cùng mã ISO ghi đè tên; hình Úc vẫn đúng). Sửa `tools/build_world_map.py`, có test. Dựng lại bản đồ thì so tên/hình với bản cũ trước khi thay.
- **Số liệu giữ chân người xem (đo 19/11 trên video #6 FDI, #7 thuê bao):** chỉ 43% lượt xem qua được vài giây đầu; còn xem ở giây ~18: 60% / 38%; tới cuối: 34% / 17%; xem trung bình 40 / 28 giây trên video 77 / 73 giây. Chỗ rớt mạnh nhất nằm trong 15 giây đầu, đúng ở câu định nghĩa, câu đệm chung chung và câu "Nhìn lại năm 1960/1970"; 1/3 số cảnh (trung bình 22 giây mỗi video) là cảnh chữ nền trống. Đây là căn cứ của đợt nâng chất lượng 19/11 — đo lại sau khi có video khổ mới rồi mới chỉnh tiếp.
- **Giọng đọc trong bộ đệm gắn SỐ THỨ TỰ cảnh** (`v_01.wav`...): bỏ/thêm một cảnh ở spec đã có giọng là câu sau dùng nhầm giọng câu trước (dấu vân tay `voice.sha1` chỉ so lời, không so vị trí). Vì vậy bỏ intro chỉ áp cho spec MỚI sinh; spec cũ giữ intro.
- **Hook "A hôm nay mới bằng B năm X" hay bị bịa** (đo 19/11 trên 29 kịch bản bảng số: 4 câu sai/không căn cứ — #27, #36, #37, #46; #46 và #37 đã "Kiểm chứng ĐẠT", #37 đã dựng xong video). Gốc: prompt lấy chính câu đó làm ví dụ hook. Mọi con số trong câu đều có trong nguồn nên cổng chống bịa số không bắt được, và **agent Kiểm chứng flash-lite đọc cả bài, được dặn riêng, vẫn cho qua cả hai câu** — chỉ cổng code `claims.py` bắt được. Đừng gỡ cổng này; hook kiểu này chỉ dùng khi tóm tắt có dòng "tương đương".
- **Thay đổi của một tỷ lệ % phải nói bằng điểm phần trăm** (19/11): 74,7% -> 68,6% từng được ghi "giảm 8,28%" (đúng toán, người xem hiểu sai).
- **Tốc độ giọng TTS mỗi hôm một khác** (3,20 từ/giây ở #37, #38; 3,79 ở #45): kịch bản đúng ngân sách từ vẫn ra video 95,3 giây, rớt Kiểm định sau khi đã tốn quota. `assemble.fit_tempo` xử lý; đừng siết ngân sách từ thay cho nó.
- **Reddit chặn hẳn** (19/11): RSS cũng 404/429 từ cả laptop lẫn VM (old.reddit 403) -> tắt trong config.
- **npm 11 (đi kèm Node 24) không chạy script cài đặt của esbuild** (cảnh báo allowScripts): Remotion vẫn đóng gói và dựng bình thường (đo 19/11) — không cần duyệt script đó.
- **Chạy nền qua ssh phải cắt stdin** (`… > log 2>&1 < /dev/null &`), không thì lệnh ssh treo tới khi tiến trình nền xong.
- **Agent Kiểm chứng bằng LLM không đủ để chặn số bịa**: nó chỉ soát danh sách "claims" Biên kịch tự khai. Đã lọt câu mở đầu "Sai lầm 99% người ăn chay..." (kịch bản #10) và ba con số không có trong nguồn ở kịch bản #6 (video #2, Du đã duyệt trước khi có cổng này). Từ 12/11 code đối chiếu TỪNG con số trong lời đọc với bài nguồn (`crew.unsourced_numbers`); đừng gỡ cổng này.

## Cách làm việc
- **Repo CÔNG KHAI trên GitHub** (https://github.com/cquangdu-work/video-agents, đưa lên 17/11/2026 làm portfolio, lịch sử đã gỡ thông tin riêng bằng git-filter-repo). Đẩy: `git push vm master` (chạy thật) và `git push github master:main` (deploy key `~/.ssh/github_video_agents`, alias SSH `github-video-agents`). KHÔNG commit: khoá/token, ID kênh, IP/alias SSH của VM, tên dịch vụ khác của Du trên VM, thông tin cá nhân của Du.
- Làm từng giai đoạn nhỏ, chạy thử được rồi mới sang bước tiếp. Commit git sau mỗi bước.
- Hỏi Du trước khi: cài dịch vụ trả phí, tạo tài khoản, đăng bất cứ thứ gì công khai, xoá dữ liệu.
- Trả lời Du bằng tiếng Việt.
