# Trang web của kênh (GitHub Pages)

Ba trang tĩnh mà Google (YouTube API: chuyển app sang Production, đơn audit) và TikTok (xác minh
Terms of Service URL, Privacy Policy URL, Website URL) đòi phải có:

| File | Vai trò |
|---|---|
| `index.html` | Trang chủ: kênh là gì, video làm thế nào (khai báo giọng AI, Du duyệt từng video) |
| `privacy.html` | Chính sách quyền riêng tư: dùng YouTube API Services (link Điều khoản YouTube + Chính sách Google), quyền nào, lưu gì ở đâu, cách thu hồi quyền |
| `terms.html` | Điều khoản: công cụ riêng của chủ kênh, đồng ý Điều khoản YouTube + TikTok |

Song ngữ Anh–Việt (người duyệt ở Google/TikTok đọc tiếng Anh). Màu theo `config/brand.yaml`.
Không cookie, không theo dõi.

## Đăng (một lần)

1. Liên hệ: tạm dùng trang Issues của repo (không lộ email cá nhân); có Gmail riêng của kênh thì thay vào.
2. Tạo repo công khai trên GitHub (`cquangdu-work/thegioiquaconso` (đã tạo 12/11/2026)), đẩy nội dung thư mục này lên nhánh `main`.
3. Repo → Settings → Pages → Deploy from a branch → `main` / `(root)`.
   Địa chỉ: `https://cquangdu-work.github.io/thegioiquaconso/`.
4. TikTok: Manage apps → URL properties → xác minh **URL prefix** bằng file chữ ký TikTok cấp
   (tải file đó vào thư mục này, đẩy lên lại).

## Gốc tên miền (repo `cquangdu-work/cquangdu-work.github.io`, tạo 12/11/2026)

Chỉ chứa file xác minh TikTok (cùng tên, cùng nội dung với file ở thư mục này) và một trang
chuyển hướng về `/thegioiquaconso/` — để xác minh qua được dù nhập URL prefix là gốc tên miền
hay `/thegioiquaconso/`. DNS của `github.io` do GitHub quản lý nên không dùng được kiểu xác minh
bằng bản ghi TXT.
