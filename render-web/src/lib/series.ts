import { Series } from "../types";
import { lerp } from "./anim";

/** Giá trị nội suy của chuỗi tại năm x (null nếu trước điểm đầu) — CHỈ dùng để vẽ đường. */
export function valueAt(s: Series, x: number): number | null {
  if (!s.xs.length || x < s.xs[0]) return null;
  for (let i = 0; i + 1 < s.xs.length; i++) {
    if (x <= s.xs[i + 1]) {
      const k = (x - s.xs[i]) / (s.xs[i + 1] - s.xs[i]);
      return lerp(s.ys[i], s.ys[i + 1], k);
    }
  }
  return s.ys[s.ys.length - 1];
}

/** Điểm số liệu THẬT gần nhất <= năm x. Nhãn trên hình chỉ được hiện số này. */
export function lastKnown(s: Series, x: number): { x: number; y: number } | null {
  let out: { x: number; y: number } | null = null;
  s.xs.forEach((xx, i) => { if (xx <= x + 1e-6) out = { x: xx, y: s.ys[i] }; });
  return out;
}

/** Số liệu thật đúng năm x (null nếu năm đó không có số). */
export function exactAt(s: Series, x: number): number | null {
  const i = s.xs.indexOf(x);
  return i >= 0 ? s.ys[i] : null;
}

/** Bước lưới 1-2-5 sao cho các vạch cách nhau ít nhất minPx điểm ảnh. */
export function niceStep(range: number, px: number, minPx: number) {
  for (const s of [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000,
    20000, 50000, 100000, 200000, 500000, 1e6, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8, 1e9, 1e10, 1e11, 1e12])
    if ((s / range) * px >= minPx) return s;
  return 1e12;
}
