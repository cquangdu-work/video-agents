// Ngôn ngữ của video (kênh Việt / kênh Hàn, 20/11/2026) — Python ghi props.lang (src/render/web.py), không có
// thì là tiếng Việt. Đọc một lần ở cấp module bằng getInputProps() để mọi hàm viết số dùng chung.
import { getInputProps } from "remotion";

export type Lang = "vi" | "ko";

const raw = (() => {
  try {
    return (getInputProps() as { lang?: string }).lang;
  } catch {
    return undefined;
  }
})();

export const LANG: Lang = raw === "ko" ? "ko" : "vi";

/** Dấu ngăn nghìn / dấu thập phân: Việt 1.234,5 — Hàn 1,234.5 (giống src/lang.py). */
export const SEP = LANG === "ko" ? { thou: ",", dec: "." } : { thou: ".", dec: "," };
