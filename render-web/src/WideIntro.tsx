import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { loadFont as loadKR } from "@remotion/google-fonts/NotoSansKR";
import { LANG } from "./lib/locale";
import { Brand } from "./types";
import { pop, ramp } from "./lib/anim";

// MỞ ĐẦU VIDEO DÀI (src/longform.py, 24/11/2026): ~10 giây lời dẫn đọc bằng giọng kênh, hình là danh sách các chương
// hiện dần, chương được xem nhiều nhất tuần tô vàng ("nổi bật"). Chữ lấy từ tiêu đề các Shorts đã đăng — không số mới.

const vi = loadFont("normal", { weights: ["600", "700", "800"], subsets: ["vietnamese", "latin"] });
const kr = LANG === "ko" ? loadKR("normal", { weights: ["700", "800"], subsets: ["korean", "latin"] }) : null;
const fontFamily = kr ? `${vi.fontFamily}, ${kr.fontFamily}` : vi.fontFamily;

export type WideIntroProps = {
  lang?: string; brand: Brand; duration: number;
  series: string; headline: string; chapters: string[]; lead: number; leadLabel: string;
};

export const WideIntro: React.FC<WideIntroProps> = ({ brand, duration, series, headline, chapters, lead, leadLabel }) => {
  const t = useCurrentFrame() / useVideoConfig().fps;
  const head = ramp(t, 0, 0.5);
  const step = Math.min(0.55, (0.6 * duration) / Math.max(chapters.length, 1));
  const out = 1 - ramp(t, duration - 0.35, duration);
  return (
    <AbsoluteFill style={{ fontFamily, color: brand.text, opacity: out,
      background: `radial-gradient(ellipse 1400px 900px at 70% 40%, #17233b 0%, ${brand.background} 70%)` }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${brand.muted} 2px, transparent 2.6px)`,
        backgroundSize: "60px 60px", opacity: 0.12 }} />
      <div style={{ position: "absolute", left: 120, top: 110, opacity: head }}>
        <div style={{ display: "inline-block", fontSize: 30, fontWeight: 800, letterSpacing: "0.16em", color: brand.accent,
          border: `3px solid ${brand.accent}`, borderRadius: 999, padding: "6px 22px" }}>{series}</div>
        <div style={{ marginTop: 24, fontSize: 84, fontWeight: 800, lineHeight: 1.1 }}>{headline}</div>
      </div>
      <div style={{ position: "absolute", left: 120, right: 120, top: 360 }}>
        {chapters.map((c, i) => {
          const k = pop(t, 0.6 + i * step, 0.35);
          const isLead = i === lead;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 22, marginTop: chapters.length > 6 ? 22 : 30, opacity: Math.min(k, 1),
              transform: `translateX(${(1 - Math.min(k, 1)) * -30}px)` }}>
              <div style={{ width: 60, height: 60, borderRadius: 30, display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: 26, fontWeight: 800, flexShrink: 0,
                background: isLead ? brand.accent : brand.surface, color: isLead ? brand.background : brand.muted }}>{i + 1}</div>
              <div style={{ fontSize: chapters.length > 6 ? 44 : 52, fontWeight: isLead ? 800 : 600,
                color: isLead ? brand.accent : brand.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                wordBreak: "keep-all" }}>{c}</div>
              {isLead && <div style={{ flexShrink: 0, fontSize: 24, fontWeight: 800, color: brand.background,
                background: brand.accent, borderRadius: 10, padding: "4px 12px" }}>★ {leadLabel}</div>}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
