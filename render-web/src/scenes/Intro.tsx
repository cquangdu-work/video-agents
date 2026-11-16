import React from "react";
import { AbsoluteFill, Easing } from "remotion";
import { Brand } from "../types";
import { ramp } from "../lib/anim";

// Intro ~1 giây giữ đúng ý bộ nhận diện cũ (số 0 nhảy thành 1 + tên kênh) nhưng có chuyển động:
// chữ số cuộn, tên kênh giãn chữ rồi thu lại, vạch vàng quét qua, cuối cảnh phóng to biến mất.
export const Intro: React.FC<{ brand: Brand; tl: number; dur: number }> = ({ brand, tl, dur }) => {
  const roll = ramp(tl, 0.15, 0.55, Easing.inOut(Easing.cubic));
  const name = ramp(tl, 0.2, 0.75, Easing.out(Easing.cubic));
  const out = ramp(tl, dur - 0.2, dur, Easing.in(Easing.cubic));
  return (
    <AbsoluteFill style={{
      alignItems: "center", justifyContent: "center",
      opacity: 1 - out, transform: `scale(${1 + out * 0.35})`,
    }}>
      <div style={{ height: 300, overflow: "hidden", marginTop: -160 }}>
        <div style={{ transform: `translateY(${-roll * 300}px)` }}>
          {["0", "1"].map((d) => (
            <div key={d} style={{ height: 300, fontSize: 290, fontWeight: 800, lineHeight: "300px",
              color: brand.accent, textAlign: "center", textShadow: `0 0 60px ${brand.accent}55` }}>{d}</div>
          ))}
        </div>
      </div>
      <div style={{ marginTop: 30, fontSize: 56, fontWeight: 800, color: brand.text,
        letterSpacing: `${0.5 - 0.36 * name}em`, opacity: name }}>
        {brand.channel}
      </div>
      <div style={{ marginTop: 22, height: 8, borderRadius: 4, background: brand.accent,
        width: 460 * ramp(tl, 0.35, 0.9, Easing.out(Easing.cubic)) }} />
    </AbsoluteFill>
  );
};
