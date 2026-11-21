import React from "react";
import { AbsoluteFill, Freeze } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { loadFont as loadKR } from "@remotion/google-fonts/NotoSansKR";
import { LANG } from "./lib/locale";
import { Story } from "./Story";
import { Brand, StoryProps } from "./types";

// HÌNH THU NHỎ của video dài hằng tuần (src/longform.py, 21/11/2026): video dài sống nhờ hình thu nhỏ ở trang chủ /
// cột đề xuất (nhánh giờ xem của YPP). Trái: số câu chuyện rất to (đọc được cả khi hình chỉ còn ~170 điểm ảnh) +
// khoảng ngày; phải: 3 khung hình THẬT của các Shorts trong tuần (chính Story, dừng ở khung đẹp nhất) xếp hình quạt.
// Không có câu chữ nào ngoài số chương + ngày — không câu view.

const vi = loadFont("normal", { weights: ["600", "700", "800"], subsets: ["vietnamese", "latin"] });
const kr = LANG === "ko" ? loadKR("normal", { weights: ["700", "800"], subsets: ["korean", "latin"] }) : null;
const fontFamily = kr ? `${vi.fontFamily}, ${kr.fontFamily}` : vi.fontFamily;

export type ThumbProps = {
  lang?: string;
  brand: Brand;
  series: string; // "TUẦN QUA CON SỐ" | "숫자로 본 한 주"
  count: number; // số câu chuyện (chương)
  label: string[]; // dòng chữ cạnh con số: ["CÂU CHUYỆN", "QUA CON SỐ"]
  span: string; // "15/11–21/11"
  cards: { story: StoryProps; frame: number }[]; // tối đa 3
};

const SCALE = 0.3; // khung dọc 1080x1920 -> 324x576

export const Thumb: React.FC<ThumbProps> = ({ brand, series, count, label, span, cards }) => {
  const n = cards.length;
  return (
    <AbsoluteFill style={{ fontFamily, color: brand.text,
      background: `radial-gradient(ellipse 900px 700px at 75% 50%, #1b2a45 0%, ${brand.background} 75%)` }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${brand.muted} 2px, transparent 2.6px)`,
        backgroundSize: "48px 48px", opacity: 0.14 }} />
      {cards.map((c, i) => {
        const mid = (n - 1) / 2;
        const rot = (i - mid) * 7;
        const x = 905 + (i - mid) * 190 - (1080 * SCALE) / 2;
        const y = 80 + Math.abs(i - mid) * 26;
        return (
          <div key={i} style={{ position: "absolute", left: x, top: y, width: 1080 * SCALE, height: 1920 * SCALE,
            transform: `rotate(${rot}deg)`, borderRadius: 22, overflow: "hidden", zIndex: i === Math.round(mid) ? 2 : 1,
            border: `4px solid ${brand.surface}`, boxShadow: "0 24px 60px rgba(0,0,0,0.65)" }}>
            <div style={{ width: 1080, height: 1920, transform: `scale(${SCALE})`, transformOrigin: "top left" }}>
              <Freeze frame={c.frame}><Story {...c.story} sfx={[]} words={[]} hideCaptions hideLogo /></Freeze>
            </div>
          </div>
        );
      })}
      {/* lớp tối bên trái cho chữ */}
      <AbsoluteFill style={{ background: `linear-gradient(90deg, ${brand.background}f5 0px, ${brand.background}e0 470px, ${brand.background}00 640px)` }} />
      <div style={{ position: "absolute", left: 64, top: 70, width: 600 }}>
        <div style={{ display: "inline-block", fontSize: 30, fontWeight: 800, letterSpacing: "0.12em", color: brand.accent,
          border: `3px solid ${brand.accent}`, borderRadius: 999, padding: "6px 20px", whiteSpace: "nowrap" }}>{series}</div>
        <div style={{ marginTop: 6, fontSize: 300, fontWeight: 800, lineHeight: 1, color: brand.accent,
          textShadow: `0 0 60px ${brand.accent}55` }}>{count}</div>
        {label.map((l, i) => (
          <div key={i} style={{ fontSize: 64, fontWeight: 800, lineHeight: 1.08, whiteSpace: "nowrap" }}>{l}</div>
        ))}
        <div style={{ marginTop: 18, fontSize: 44, fontWeight: 700, color: brand.muted }}>{span}</div>
      </div>
    </AbsoluteFill>
  );
};
