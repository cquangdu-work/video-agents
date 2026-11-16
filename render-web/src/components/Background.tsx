import React from "react";
import { AbsoluteFill, staticFile } from "remotion";
import { Brand } from "../types";

// Nền có chiều sâu thay cho màu phẳng: quầng sáng giữa, lưới chấm (chữ ký kênh, trôi chậm),
// hai đốm màu mờ di chuyển, hạt nhiễu kiểu phim và viền tối. Không dùng CSS blur (chậm khi render).
// Hạt nhiễu ĐỨNG YÊN: cho nó nhảy mỗi khung thì bộ nén phải mã hoá nhiễu -> 31 giây nặng 113 MB (đo 16/11).
export const Background: React.FC<{ brand: Brand; t: number; frame: number }> = ({ brand, t }) => {
  const blob = (cx: number, cy: number, r: number, color: string, alpha: string) => (
    <AbsoluteFill style={{
      background: `radial-gradient(circle ${r}px at ${cx}px ${cy}px, ${color}${alpha} 0%, transparent 100%)`,
    }} />
  );
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse 900px 1300px at 50% 40%, #17233b 0%, ${brand.background} 75%)` }}>
      {blob(260 + 120 * Math.sin(t * 0.35), 520 + 80 * Math.cos(t * 0.27), 520, brand.korea, "33")}
      {blob(820 + 100 * Math.cos(t * 0.3), 1250 + 90 * Math.sin(t * 0.22), 480, brand.accent, "14")}
      <AbsoluteFill style={{
        backgroundImage: `radial-gradient(${brand.muted} 2.2px, transparent 2.8px)`,
        backgroundSize: "90px 90px",
        backgroundPosition: `${(t * 5) % 90}px ${(t * 9) % 90}px`,
        opacity: 0.16,
      }} />
      <AbsoluteFill style={{
        backgroundImage: `url(${staticFile("grain.png")})`,
        opacity: 0.05,
      }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 760px 1150px at 50% 45%, transparent 55%, rgba(0,0,0,0.55) 100%)" }} />
    </AbsoluteFill>
  );
};
