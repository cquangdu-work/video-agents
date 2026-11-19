import React from "react";
import { Brand, Word } from "../types";
import { clamp01 } from "../lib/anim";

// Phụ đề lớn theo cụm (chữ lấy từ KỊCH BẢN, mốc thời gian từ Whisper — giữ đúng luật cũ).
// Từ đang đọc đổi màu nhấn và nảy nhẹ. Đặt ở 1/4 dưới khung nhưng trên vùng nút của YouTube/TikTok.
const RING = [[4, 0], [-4, 0], [0, 4], [0, -4], [3, 3], [-3, 3], [3, -3], [-3, -3]]
  .map(([x, y]) => `${x}px ${y}px 0 rgba(6,10,20,0.95)`).join(", ") + ", 0 6px 24px rgba(0,0,0,0.6)";

// size: cỡ chữ (px) — một "núm" đang thử nghiệm của src/style.py (72-96 px), mặc định 80 như trước 19/11.
export const Captions: React.FC<{ words: Word[]; t: number; brand: Brand; size?: number }> = ({ words, t, brand, size = 80 }) => {
  if (!words.length) return null;
  const chunks = new Map<number, Word[]>();
  for (const w of words) chunks.set(w.c, [...(chunks.get(w.c) ?? []), w]);
  const list = [...chunks.values()];
  let cur: Word[] | undefined;
  for (let i = 0; i < list.length; i++) {
    const ch = list[i];
    const nextStart = i + 1 < list.length ? list[i + 1][0].s : Infinity;
    const hold = Math.min(0.5, nextStart - ch[ch.length - 1].e);
    if (t >= ch[0].s - 0.04 && t < ch[ch.length - 1].e + Math.max(hold, 0)) cur = ch;
  }
  if (!cur) return null;
  const enter = clamp01((t - cur[0].s + 0.04) / 0.12);
  return (
    <div style={{
      position: "absolute", top: 1395, left: 60, right: 60, textAlign: "center",
      fontSize: size, fontWeight: 800, lineHeight: 1.15, letterSpacing: "-0.01em",
      opacity: enter, transform: `translateY(${(1 - enter) * 18}px)`,
    }}>
      {cur.map((w, i) => {
        const next = cur![i + 1];
        const active = t >= w.s && t < (next ? next.s : w.e + 0.5);
        // nảy: phóng lên trong 0,08 giây rồi lắng về 1,06 (từ đang đọc vẫn to hơn chút)
        const bump = clamp01((t - w.s) / 0.08) * (1 - clamp01((t - w.s - 0.08) / 0.15));
        const scale = active ? 1.06 + 0.1 * bump : 1;
        return (
          <span key={i} style={{
            display: "inline-block", margin: "0 12px",
            color: active ? brand.accent : brand.text,
            textShadow: RING, transform: `scale(${scale})`,
          }}>{w.w}</span>
        );
      })}
    </div>
  );
};
