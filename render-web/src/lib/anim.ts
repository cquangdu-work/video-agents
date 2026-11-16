import { Easing, interpolate } from "remotion";

export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
export const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

/** 0 -> 1 trong khoảng [a, b] giây, có làm mượt. Ngoài khoảng thì giữ 0 hoặc 1. */
export const ramp = (t: number, a: number, b: number, ease = Easing.inOut(Easing.cubic)) =>
  b <= a ? (t >= b ? 1 : 0)
    : interpolate(t, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });

/** Bật ra có nảy nhẹ (vượt quá rồi về 1) — dùng cho icon, nhãn. */
export const pop = (t: number, at: number, dur = 0.35) => ramp(t, at, at + dur, Easing.out(Easing.back(1.8)));

/** Nhịp "đập" ngắn sau một thời điểm: 1 ngay lúc đó rồi tắt dần về 0. */
export const pulse = (t: number, at: number, dur = 0.25) =>
  t < at || t > at + dur ? 0 : 1 - (t - at) / dur;

/** Số kiểu Việt Nam: 1.234 và 0,03. Số nhỏ giữ đủ chữ số để không làm tròn mất giá trị. */
export const fmtVi = (v: number) => {
  const a = Math.abs(v);
  const dec = Number.isInteger(v) || a >= 10 ? 0 : a >= 0.1 ? 1 : 2;
  const [i, f] = v.toFixed(dec).split(".");
  const int = i.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return f ? `${int},${f}` : int;
};
