import React from "react";
import { AbsoluteFill } from "remotion";
import { Brand, Finding } from "../types";
import { pop, ramp } from "../lib/anim";

// THẺ PHÁT HIỆN cuối video (24/11/2026, Du: "mỗi video phải có một phát hiện đáng nhớ", "hình ảnh phải đẹp ngay cả
// khi tắt âm thanh"). Chữ = câu mở đầu đã qua mọi cổng kiểm số (src/render/web.finding_of), con số lớn = số chính của
// câu đó. Người tắt tiếng / xem lặp lại vẫn mang về đúng một điều.
// opening: THẺ MỞ ĐẦU (24/11/2026) — cùng nội dung, hiện ĐỦ ngay khung đầu (người xem quyết định lướt trong 1-2 giây)
// rồi mờ đi trong 0,3 giây cuối, mở ra cảnh đầu đã chạy sẵn. Thẻ cuối = thẻ đầu -> video phát lặp liền mạch.
export const FindingCard: React.FC<{ f: Finding; brand: Brand; t: number; opening?: number }> = ({ f, brand, t, opening }) => {
  const start = opening ? 0 : f.start, end = opening ? opening : f.end;
  if (t < start || t > end + 0.05) return null;
  const tl = t - start;
  const out = opening ? 1 - ramp(t, end - 0.3, end) : 1;
  const bg = (opening ? 1 : ramp(tl, 0, 0.35)) * out;
  const num = opening ? out : pop(tl, 0.15, 0.5);
  const txt = (opening ? 1 : ramp(tl, 0.45, 0.9)) * out;
  const cta = !opening && f.cta ? ramp(tl, 1.0, 1.4) : 0;
  const long = f.text.length > 70;
  return (
    <AbsoluteFill style={{ background: `${brand.background}${Math.round(bg * 250).toString(16).padStart(2, "0")}`,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 80px" }}>
      <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: "0.22em", color: brand.accent, opacity: bg,
        border: `3px solid ${brand.accent}`, borderRadius: 999, padding: "8px 26px", marginTop: -140 }}>{f.label}</div>
      {f.value && (
        <div style={{ marginTop: 40, fontSize: f.value.length > 9 ? 150 : 190, fontWeight: 800, lineHeight: 1,
          color: brand.accent, transform: `scale(${num})`, textShadow: `0 0 70px ${brand.accent}66`,
          whiteSpace: "nowrap" }}>{f.value}</div>
      )}
      <div style={{ marginTop: 44, fontSize: long ? 50 : 58, fontWeight: 800, lineHeight: 1.3, color: brand.text,
        textAlign: "center", wordBreak: "keep-all", opacity: txt, transform: `translateY(${(1 - txt) * 24}px)` }}>{f.text}</div>
      {cta > 0 && (
        <div style={{ marginTop: 50, fontSize: 36, fontWeight: 700, color: brand.muted, opacity: cta, textAlign: "center",
          wordBreak: "keep-all" }}>▶ {f.cta}</div>
      )}
    </AbsoluteFill>
  );
};
