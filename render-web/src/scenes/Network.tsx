import React from "react";
import { AbsoluteFill, Easing, random } from "remotion";
import { RadioTower, Smartphone } from "lucide-react";
import { Brand, NetworkScene } from "../types";
import { pop, ramp } from "../lib/anim";

// "Điện thoại của bạn là một phần của hạ tầng khổng lồ": bắt đầu từ MỘT chiếc điện thoại to
// (nối từ cú lao camera của cảnh trước), thu nhỏ thành một nút, rồi mạng lưới trạm phát + máy
// lan ra khắp màn hình. Vị trí do random(seed) quyết định -> render lại vẫn y hệt.
const CX = 540, CY = 820;
const TOWERS = Array.from({ length: 6 }, (_, i) => {
  const a = (-90 + i * 60 + 18) * Math.PI / 180;
  const r = 300 + 60 * random(`tw${i}`);
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) * 1.15 };
});
const NODES = Array.from({ length: 90 }, (_, i) => {
  const a = random(`na${i}`) * Math.PI * 2;
  const r = 90 + random(`nr${i}`) * 560;
  const x = Math.max(70, Math.min(1010, CX + r * Math.cos(a)));
  const y = Math.max(400, Math.min(1310, CY + r * Math.sin(a) * 1.2));
  let best = 0, bd = Infinity;
  TOWERS.forEach((t, k) => { const d = Math.hypot(t.x - x, t.y - y); if (d < bd) { bd = d; best = k; } });
  return { x, y, tower: best, born: 0.9 + (Math.hypot(x - CX, y - CY) / 650) * 2.0 };
});

export const Network: React.FC<{ s: NetworkScene; brand: Brand; tl: number; dur: number }> = ({ s, brand, tl, dur }) => {
  const shrink = ramp(tl, 0.0, 0.7, Easing.inOut(Easing.cubic));
  const cam = 1.12 - 0.14 * ramp(tl, 0, dur, Easing.linear);
  const out = ramp(tl, dur - 0.15, dur);
  const phoneSize = 360 - 290 * shrink;
  return (
    <AbsoluteFill style={{ opacity: 1 - out }}>
      <Title text={s.title} brand={brand} tl={tl} />
      <AbsoluteFill style={{ transform: `scale(${cam})`, transformOrigin: `${CX}px ${CY}px` }}>
        <svg width={1080} height={1920} style={{ position: "absolute" }}>
          {NODES.map((n, i) => {
            const k = ramp(tl, n.born, n.born + 0.35, Easing.out(Easing.cubic));
            if (k <= 0) return null;
            const t = TOWERS[n.tower];
            return <line key={i} x1={t.x} y1={t.y} x2={t.x + (n.x - t.x) * k} y2={t.y + (n.y - t.y) * k}
              stroke={brand.muted} strokeOpacity={0.35} strokeWidth={2} />;
          })}
          {TOWERS.map((t, i) => {
            const k = ramp(tl, 0.35 + i * 0.08, 0.85 + i * 0.08);
            return <line key={`c${i}`} x1={CX} y1={CY} x2={CX + (t.x - CX) * k} y2={CY + (t.y - CY) * k}
              stroke={brand.accent} strokeOpacity={0.7} strokeWidth={4} />;
          })}
          {TOWERS.map((t, i) => [0, 1, 2].map((j) => {
            if (tl < 0.5 + i * 0.08) return null;
            const r = ((tl * 150 + j * 75 + i * 23) % 225);
            return <circle key={`r${i}${j}`} cx={t.x} cy={t.y} r={r} fill="none"
              stroke={brand.korea} strokeOpacity={0.55 * (1 - r / 225)} strokeWidth={3} />;
          }))}
          {NODES.map((n, i) => {
            const k = pop(tl, n.born + 0.25, 0.3);
            if (k <= 0) return null;
            const fresh = 1 - ramp(tl, n.born + 0.3, n.born + 1.2);
            return (
              <g key={`n${i}`}>
                <circle cx={n.x} cy={n.y} r={16 * k} fill={brand.accent} fillOpacity={0.25 * fresh} />
                <circle cx={n.x} cy={n.y} r={7 * k} fill={fresh > 0.05 ? brand.accent : brand.text} fillOpacity={0.9} />
              </g>
            );
          })}
        </svg>
        {TOWERS.map((t, i) => {
          const k = pop(tl, 0.35 + i * 0.08, 0.35);
          return (
            <div key={`t${i}`} style={{ position: "absolute", left: t.x - 40, top: t.y - 40, width: 80, height: 80,
              borderRadius: 40, background: brand.surface, display: "flex", alignItems: "center", justifyContent: "center",
              transform: `scale(${k})`, boxShadow: `0 0 0 3px ${brand.korea}` }}>
              <RadioTower size={46} color={brand.text} strokeWidth={2.2} />
            </div>
          );
        })}
        <div style={{ position: "absolute", left: CX - phoneSize / 2, top: CY - phoneSize / 2,
          width: phoneSize, height: phoneSize, display: "flex", alignItems: "center", justifyContent: "center",
          borderRadius: phoneSize / 2, background: shrink > 0.6 ? brand.accent : "transparent" }}>
          <Smartphone size={phoneSize * (shrink > 0.6 ? 0.6 : 1)} color={shrink > 0.6 ? brand.background : brand.accent}
            strokeWidth={shrink > 0.6 ? 2.6 : 1.6} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const Title: React.FC<{ text: string; brand: Brand; tl: number }> = ({ text, brand, tl }) => {
  const k = ramp(tl, 0.05, 0.45, Easing.out(Easing.cubic));
  return (
    <div style={{ position: "absolute", top: 200, left: 80, right: 80, textAlign: "center", fontSize: 58,
      fontWeight: 800, lineHeight: 1.18, color: brand.text, opacity: k, transform: `translateY(${(1 - k) * 30}px)` }}>
      {text}
    </div>
  );
};
