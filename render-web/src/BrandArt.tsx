import React from "react";
import { AbsoluteFill } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { loadFont as loadKR } from "@remotion/google-fonts/NotoSansKR";
import { LANG } from "./lib/locale";
import { Brand } from "./types";

// ẢNH BÌA TRANG KÊNH (src/brand_kit.py, Du xin 21/11/2026 "hoàn thành các kênh một cách chuyên nghiệp"):
// ảnh bìa YouTube 2560x1440 và ảnh bìa Trang Facebook 1702x630. Cùng bộ nhận diện với video: nền xanh đen,
// lưới chấm, chữ Be Vietnam Pro, Việt Nam đỏ / Hàn Quốc xanh / số liệu vàng hổ phách.
// Bản đồ do Python tính hết (phép chiếu, Hoàng Sa + Trường Sa ở kênh Việt, 독도 + 동해 ở kênh Hàn) — ở đây chỉ vẽ.

const vi = loadFont("normal", { weights: ["500", "600", "700", "800"], subsets: ["vietnamese", "latin"] });
const kr = LANG === "ko" ? loadKR("normal", { weights: ["500", "700", "800"], subsets: ["korean", "latin"] }) : null;
const fontFamily = kr ? `${vi.fontFamily}, ${kr.fontFamily}` : vi.fontFamily;

type MapPath = { d: string; fill: string; o?: number; glow?: boolean };
type MapLabel = { text: string; x: number; y: number; size: number; color: string; anchor: "start" | "middle" };

export type BrandArtProps = {
  width: number;
  height: number;
  lang?: string;
  brand: Brand;
  title: string[]; // các dòng tên kênh
  accent?: string; // phần chữ tô màu nhấn (vàng = màu của SỐ LIỆU): "CON SỐ" | "숫자"
  tagline: string;
  chip: string; // nhịp đăng ("VIDEO MỚI MỖI NGÀY · 19:00")
  sources: string;
  box: { x: number; y: number; w: number; h: number; title: number }; // khối chữ: vị trí + cỡ chữ tên kênh
  map: { paths: MapPath[]; dots: [number, number, number, string][]; labels: MapLabel[]; glowAt: [number, number] };
  shade: number; // mép của lớp tối sau khối chữ (điểm ảnh)
  shadeDir?: "x" | "y"; // "x": tối từ trái sang (ảnh bìa ngang) · "y": tối từ trên xuống (ảnh dọc Instagram)
  guides?: [number, number, number, number][]; // vùng an toàn (chỉ để soát, bản thật không vẽ)
};

const Accented: React.FC<{ text: string; accent?: string; color: string }> = ({ text, accent, color }) => {
  const i = accent ? text.indexOf(accent) : -1;
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<span style={{ color }}>{accent}</span>{text.slice(i + accent!.length)}</>;
};

export const BrandArt: React.FC<BrandArtProps> = ({ width, height, brand, title, accent, tagline, chip, sources, box,
  map, shade, shadeDir, guides }) => {
  const k = box.title / 120; // mọi cỡ chữ khác theo cỡ tên kênh
  const [gx, gy] = map.glowAt;
  return (
    <AbsoluteFill style={{ fontFamily, color: brand.text, background: brand.background, overflow: "hidden" }}>
      {/* quầng sáng quanh vùng bản đồ được nhấn + lưới chấm (chữ ký kênh) */}
      <AbsoluteFill style={{ background: `radial-gradient(circle ${height * 0.75}px at ${gx}px ${gy}px, #131d31 0%, ${brand.background} 100%)` }} />
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${brand.muted} ${2.2 * k}px, transparent ${2.8 * k}px)`,
        backgroundSize: `${72 * k}px ${72 * k}px`, opacity: 0.14 }} />
      <svg width={width} height={height} style={{ position: "absolute" }}>
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation={10 * k} result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {map.paths.filter((p) => !p.glow).map((p, i) => (
          <path key={i} d={p.d} fill={p.fill} fillOpacity={p.o ?? 1} stroke={brand.background} strokeWidth={1.2 * k} />
        ))}
        <g filter="url(#glow)">
          {map.paths.filter((p) => p.glow).map((p, i) => (
            <path key={`g${i}`} d={p.d} fill={p.fill} stroke={p.fill} strokeWidth={1.5 * k} strokeLinejoin="round" />
          ))}
          {map.dots.map(([x, y, r, c], i) => <circle key={`d${i}`} cx={x} cy={y} r={r} fill={c} />)}
        </g>
        {map.labels.map((l) => (
          <text key={l.text} x={l.x} y={l.y + l.size * 0.35} fontSize={l.size} fontWeight={700} fill={l.color}
            textAnchor={l.anchor} stroke={brand.background} strokeWidth={4 * k} paintOrder="stroke"
            strokeLinejoin="round">{l.text}</text>
        ))}
      </svg>
      {/* lớp tối sau khối chữ: bản đồ phía sau không làm rối chữ */}
      {/* dốc mềm nhiều nấc: bản đầu hai nấc (95% -> 85% -> 0) để lại một vệt dọc thấy rõ trên đất liền */}
      <AbsoluteFill style={{ background: `linear-gradient(${shadeDir === "y" ? "180deg" : "90deg"}, ${[[0, "f2"], [0.45, "eb"], [0.62, "d4"], [0.75, "a8"],
        [0.86, "6b"], [0.94, "2e"], [1, "00"]].map(([f, a]) => `${brand.background}${a} ${Math.round(shade * (f as number))}px`).join(", ")})` }} />

      <div style={{ position: "absolute", left: box.x, top: box.y, width: box.w, height: box.h, display: "flex",
        flexDirection: "column", justifyContent: "center", alignItems: "flex-start" }}>
        <div style={{ fontSize: 30 * k, fontWeight: 800, letterSpacing: "0.14em", color: brand.accent,
          border: `${2.5 * k}px solid ${brand.accent}`, borderRadius: 999, padding: `${8 * k}px ${22 * k}px`,
          whiteSpace: "nowrap" }}>{chip}</div>
        <div style={{ marginTop: 22 * k, fontSize: box.title, fontWeight: 800, lineHeight: 1.02, letterSpacing: "0.01em" }}>
          {title.map((line, i) => (
            <div key={i} style={{ whiteSpace: "nowrap" }}><Accented text={line} accent={accent} color={brand.accent} /></div>
          ))}
        </div>
        <div style={{ marginTop: 22 * k, fontSize: 38 * k, fontWeight: 600, lineHeight: 1.3, color: brand.text,
          maxWidth: box.w }}>{tagline}</div>
        {sources && <div style={{ marginTop: 14 * k, fontSize: 28 * k, fontWeight: 500, color: brand.muted,
          whiteSpace: "nowrap" }}>{sources}</div>}
      </div>

      {guides?.map(([x0, y0, x1, y1], i) => (
        <div key={`s${i}`} style={{ position: "absolute", left: x0, top: y0, width: x1 - x0, height: y1 - y0,
          border: "3px dashed #ff00ff" }} />
      ))}
    </AbsoluteFill>
  );
};
