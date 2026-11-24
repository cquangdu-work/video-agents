import React from "react";
import { AbsoluteFill } from "remotion";
import { Brand, Finding } from "../types";
import { pop, ramp } from "../lib/anim";

// THẺ PHÁT HIỆN cuối video (24/11/2026, Du: "mỗi video phải có một phát hiện đáng nhớ", "hình ảnh phải đẹp ngay cả
// khi tắt âm thanh"). Chữ = câu mở đầu đã qua mọi cổng kiểm số (src/render/web.finding_of), con số lớn = số chính của
// câu đó. Người tắt tiếng / xem lặp lại vẫn mang về đúng một điều.
export const FindingCard: React.FC<{ f: Finding; brand: Brand; t: number }> = ({ f, brand, t }) => {
  if (t < f.start || t > f.end + 0.05) return null;
  const tl = t - f.start;
  const bg = ramp(tl, 0, 0.35);
  const num = pop(tl, 0.15, 0.5);
  const txt = ramp(tl, 0.45, 0.9);
  const long = f.text.length > 70;
  return (
    <AbsoluteFill style={{ background: `${brand.background}${Math.round(bg * 235).toString(16).padStart(2, "0")}`,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 80px" }}>
      <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: "0.22em", color: brand.accent, opacity: bg,
        border: `3px solid ${brand.accent}`, borderRadius: 999, padding: "8px 26px", marginTop: -140 }}>{f.label}</div>
      {f.value && (
        <div style={{ marginTop: 40, fontSize: f.value.length > 9 ? 150 : 190, fontWeight: 800, lineHeight: 1,
          color: brand.accent, transform: `scale(${num})`, textShadow: `0 0 70px ${brand.accent}66`,
          whiteSpace: "nowrap" }}>{f.value}</div>
      )}
      <div style={{ marginTop: 44, fontSize: long ? 50 : 58, fontWeight: 800, lineHeight: 1.3, color: brand.text,
        textAlign: "center", opacity: txt, transform: `translateY(${(1 - txt) * 24}px)` }}>{f.text}</div>
    </AbsoluteFill>
  );
};
