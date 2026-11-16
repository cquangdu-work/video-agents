import React from "react";
import { AbsoluteFill } from "remotion";
import { Briefcase, MapPin, MessageCircle, ShoppingCart, Smartphone, Video, Wallet, LucideIcon } from "lucide-react";
import { Brand, OrbitScene } from "../types";
import { pop, pulse, ramp } from "../lib/anim";
import { Title } from "./Network";

// Điện thoại ở giữa, các việc hằng ngày bật ra quanh nó — mỗi icon xuất hiện ĐÚNG lúc lời đọc
// nhắc tới (Python dò mốc thời gian của từ trong phụ đề), các icon còn lại rải đều.
const ICONS: Record<string, LucideIcon> = {
  briefcase: Briefcase, message: MessageCircle, video: Video, cart: ShoppingCart, wallet: Wallet, pin: MapPin,
};
const CX = 540, CY = 840, R = 330;

export const Orbit: React.FC<{ s: OrbitScene; brand: Brand; tl: number; dur: number }> = ({ s, brand, tl, dur }) => {
  const spin = tl * 7;
  const out = ramp(tl, dur - 0.15, dur);
  const center = pop(tl, 0.0, 0.4);
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Title text={s.title} brand={brand} tl={tl} />
      <svg width={1080} height={1920} style={{ position: "absolute" }}>
        <circle cx={CX} cy={CY} r={R} fill="none" stroke={brand.muted} strokeOpacity={0.25} strokeWidth={2} strokeDasharray="6 14" />
        {[0, 1].map((j) => {
          const r = 130 + ((tl * 90 + j * 60) % 120);
          return <circle key={j} cx={CX} cy={CY} r={r} fill="none" stroke={brand.accent} strokeOpacity={0.35 * (1 - (r - 130) / 120)} strokeWidth={3} />;
        })}
        {s.items.map((it, i) => {
          const k = ramp(tl, it.at - s.start, it.at - s.start + 0.3);
          const a = (-90 + i * (360 / s.items.length) + spin) * Math.PI / 180;
          return <line key={i} x1={CX} y1={CY} x2={CX + Math.cos(a) * R * k} y2={CY + Math.sin(a) * R * k}
            stroke={brand.accent} strokeOpacity={0.5} strokeWidth={3} />;
        })}
      </svg>
      <div style={{ position: "absolute", left: CX - 120, top: CY - 120, width: 240, height: 240, borderRadius: 120,
        background: brand.accent, display: "flex", alignItems: "center", justifyContent: "center",
        transform: `scale(${center})`, boxShadow: `0 0 80px ${brand.accent}66` }}>
        <Smartphone size={130} color={brand.background} strokeWidth={2.4} />
      </div>
      {s.items.map((it, i) => {
        const Icon = ICONS[it.icon] ?? Briefcase;
        const at = it.at - s.start;
        const k = pop(tl, at, 0.4);
        const hit = pulse(tl, at, 0.5);
        const a = (-90 + i * (360 / s.items.length) + spin) * Math.PI / 180;
        const x = CX + Math.cos(a) * R, y = CY + Math.sin(a) * R;
        return (
          <div key={i} style={{ position: "absolute", left: x - 120, top: y - 66, width: 240, textAlign: "center",
            transform: `scale(${k})`, opacity: Math.min(k, 1) }}>
            <div style={{ margin: "0 auto", width: 112, height: 112, borderRadius: 56, background: brand.surface,
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: `0 0 0 ${3 + hit * 8}px ${brand.accent}${hit > 0 ? "cc" : "66"}` }}>
              <Icon size={58} color={brand.text} strokeWidth={2.2} />
            </div>
            <div style={{ marginTop: 10, fontSize: 34, fontWeight: 700, color: brand.text }}>{it.label}</div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
