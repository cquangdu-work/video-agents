# render-web — engine dựng hình bằng Remotion (đang thử nghiệm)

Python vẫn quyết định mọi thứ quan trọng (số liệu từ bảng gốc, mốc thời gian từ giọng đọc +
Whisper, chữ phụ đề từ kịch bản). Python ghi một file JSON "props" (khuôn ở `src/types.ts`),
Remotion chỉ vẽ theo. Cầu nối phía Python: `src/render/web.py`.

## Cài
```bash
cd render-web && npm ci          # máy mới (laptop Node 24, VM Node 20 đều chạy)
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

## Đã đo (16/11/2026)
- VM ARM64: cảnh 10 giây 1080x1920 render 34,5 giây (concurrency 3), RAM đỉnh ~850 MB.
- Hạt nhiễu nhảy mỗi khung làm file 31 giây nặng 113 MB -> để hạt nhiễu đứng yên (20 MB ở crf 18).
