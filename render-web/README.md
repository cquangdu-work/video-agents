# render-web — engine dựng hình bằng Remotion (mặc định từ 16/11/2026)

Python vẫn quyết định mọi thứ quan trọng (số liệu từ bảng gốc, mốc thời gian từ giọng đọc +
Whisper, chữ phụ đề từ kịch bản). Python ghi một file JSON "props" (khuôn ở `src/types.ts`),
Remotion chỉ vẽ theo. Cầu nối phía Python: `src/render/web.py` (`build_story` dịch spec của
`src/produce.py` sang props — KHÔNG đổi gì phía Biên kịch/Sản xuất).

`src/assemble.py` dùng engine này khi `config/channel.yaml` có `render.engine: web`; lỗi gì cũng
tự lùi về Manim. Chạy thử không đè video thật: `python -m src.assemble <id> --out data/tmp/x.mp4`.

## Các mẫu chung (mỗi template của spec một bản)
| template | cảnh Remotion |
|---|---|
| statement | chữ hiện từng từ, số/viết tắt tô vàng, icon theo từ khoá (`ICON_KEYWORDS`), 3 bố cục xoay vòng |
| big_number | số đếm lên + cờ; tỷ lệ dân số % -> lưới 100 hình người; "x / 100 dân" -> người + đồ vật |
| versus | hai cờ, hai số đếm lên, cột so độ cao |
| bar_chart | có cờ; xen kẽ thanh ngang / cột đứng trong cùng video (chống "nội dung theo mẫu") |
| percent | vòng tròn phát sáng |
| line_chart | **biểu đồ chính** (`ChartWorld`): sống xuyên các cảnh, toàn màn hình ở cảnh line_chart, thu xuống nửa dưới khi cảnh so găng/số lớn nói đúng một điểm số liệu (`_match_points`, chỉ khi chắc chắn duy nhất) |
| map | bản đồ châu Á / thế giới: hình học (phép chiếu, Hoàng Sa + Trường Sa, ô phóng to Biển Đông, thứ hạng) do `src/render/web_map.py` tính, Remotion chỉ tô dần từ thấp lên cao |
| bar_race | cuộc đua có cờ, thanh trượt đổi chỗ; số trên thanh luôn là số thật của năm đang hiện |
| line_chart thứ hai khác số liệu | biểu đồ riêng chỉ sống trong cảnh đó (`line_solo`); số liệu hỏng mới dựng Manim lồng vào (`clip`) |

## Cài
```bash
cd render-web && npm ci          # máy mới. Laptop: Node 24. VM: Node 24 RIÊNG ở ~/.local/node24 (khai
                                 # REMOTION_NODE_DIR trong .env; Node 20 hệ thống hết hạn hỗ trợ, để nguyên
                                 # vì dịch vụ khác dùng chung) — deploy/setup_vm.sh tự cài
npx remotion browser ensure      # tải Chrome Headless Shell (VM ARM64 có bản riêng)
```

## Chạy bản demo (31 giây đầu video #30)
```bash
python tools/demo_web30.py --spec data/specs/script_30_final.yaml --ass data/render/subs.ass \
    --video output/final_30.mp4 --out data/tmp/demo30 [--telegram]
```
Xem/chỉnh trực quan: `npm run studio` (mở trình duyệt, kéo thanh thời gian).

## Cấu trúc
- `src/Story.tsx` — ghép nền, các cảnh theo thời gian, phụ đề, âm thanh hiệu ứng.
- `src/scenes/` — các mẫu cảnh: `Intro`, `Isotype` (100 người → N thứ), `Network`, `Orbit`
  (icon bật ra đúng lúc lời đọc nhắc tới), `HeroLine` (biểu đồ chính có "camera").
- `src/components/` — `Background` (nền có chiều sâu), `Captions` (phụ đề lớn theo từ).
- `public/` — chất liệu tĩnh, tạo lại bằng `python tools/make_web_assets.py`.

## Luật giữ nguyên từ engine cũ
- Nhãn trên hình chỉ hiện **số thật trong bảng** (`lastKnown`), số nội suy chỉ dùng để vẽ đường.
- Bản đồ có Việt Nam phải có Hoàng Sa, Trường Sa (chưa có mẫu bản đồ ở engine này).

## Giấy phép chất liệu
- Remotion: miễn phí cho cá nhân / công ty ≤ 3 người (https://www.remotion.dev/docs/license).
- Font Be Vietnam Pro: SIL OFL (tải qua `@remotion/google-fonts` lúc render).
- Icon: lucide-react (ISC). Cờ: flag-icons (MIT, `public/flags/LICENSE-flag-icons.txt`).
- Âm thanh hiệu ứng (`public/sfx`) và hạt nhiễu (`public/grain.png`): tự tổng hợp bằng code.

## Kiểm định
`build_story` gắn vào mỗi cảnh của spec trường `shown` (số liệu bảng gốc, vạch chia trục) để
`src/qc.py` không coi số trên biểu đồ chính là "số lạ" khi model nhìn ảnh soát hình.

## Đã đo (16/11/2026)
- VM ARM64: cảnh 10 giây 1080x1920 render 34,5 giây (concurrency 3), RAM đỉnh ~850 MB.
- Hạt nhiễu nhảy mỗi khung làm file 31 giây nặng 113 MB -> để hạt nhiễu đứng yên (20 MB ở crf 18).
