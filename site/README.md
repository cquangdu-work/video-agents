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

1. Thay `{{CONTACT_EMAIL}}` trong cả 3 trang bằng email liên hệ Du chọn công khai.
2. Tạo repo công khai trên GitHub (vd `thegioiquaconso`), đẩy nội dung thư mục này lên nhánh `main`.
3. Repo → Settings → Pages → Deploy from a branch → `main` / `(root)`.
   Địa chỉ: `https://<tên-github>.github.io/thegioiquaconso/`.
4. TikTok: Manage apps → URL properties → xác minh **URL prefix** bằng file chữ ký TikTok cấp
   (tải file đó vào thư mục này, đẩy lên lại).
