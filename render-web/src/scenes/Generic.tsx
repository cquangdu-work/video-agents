import React from "react";
import { AbsoluteFill, Easing, Img, OffthreadVideo, staticFile } from "remotion";
import { PersonStanding } from "lucide-react";
import {
  BarChartScene, BigNumberScene, Brand, ClipScene, LineChartScene, PercentScene, StatementScene, Valued, VersusScene,
} from "../types";
import { fmtDec, lerp, pop, ramp } from "../lib/anim";
import { ICONS } from "../components/Icons";

// Các mẫu cảnh CHUNG — mỗi template của spec (src/produce.py) có một bản ở đây.
// Luật thời gian giữ như engine Manim: hoạt hình đếm số xong trước 70% cảnh, vì Kiểm định
// chụp khung ở 85% cảnh để đối chiếu số trên hình với lời đọc.

type P<S> = { s: S; brand: Brand; tl: number; dur: number };

const exitOf = (tl: number, dur: number) => 1 - ramp(tl, dur - 0.15, dur);
const countK = (tl: number, dur: number) => ramp(tl, 0.05 * dur, 0.62 * dur, Easing.out(Easing.cubic));
/** Cỡ chữ để một chuỗi số vừa bề ngang `width` (ước lượng ~0,6 em mỗi ký tự với font đậm). */
const fitSize = (text: string, width: number, max: number) => Math.min(max, width / (0.62 * Math.max(text.length, 1)));

export const SceneTitle: React.FC<{ text: string; brand: Brand; tl: number }> = ({ text, brand, tl }) => {
  const k = ramp(tl, 0.0, 0.4, Easing.out(Easing.cubic));
  return (
    <div style={{ position: "absolute", top: 196, left: 70, right: 70, textAlign: "center", fontSize: 56,
      fontWeight: 800, lineHeight: 1.2, color: brand.text, opacity: k, transform: `translateY(${(1 - k) * 26}px)` }}>
      {text}
    </div>
  );
};

const Flag: React.FC<{ code?: string; w: number }> = ({ code, w }) =>
  code ? <Img src={staticFile(`flags/${code}.svg`)} style={{ width: w, height: w * 0.75, borderRadius: w / 10,
    boxShadow: "0 4px 18px rgba(0,0,0,0.45)" }} /> : null;

// ------------------------------------------------------------------ cảnh chữ
/** Tô màu nhấn cho số và chữ viết tắt (danh sách do Python tính bằng cùng hàm với Manim). */
function richWords(text: string, hl: string[], brand: Brand, tl: number) {
  const words = text.split(/\s+/).filter(Boolean);
  return words.map((w, i) => {
    const k = ramp(tl, 0.05 + i * 0.045, 0.3 + i * 0.045, Easing.out(Easing.cubic));
    const hot = hl.some((h) => w.includes(h));
    return (
      <span key={i} style={{ display: "inline-block", marginRight: "0.28em", opacity: k,
        transform: `translateY(${(1 - k) * 22}px)`, color: hot ? brand.accent : brand.text }}>{w}</span>
    );
  });
}

export const Statement: React.FC<P<StatementScene>> = ({ s, brand, tl, dur }) => {
  const Icon = s.icon ? ICONS[s.icon] : undefined;
  const ik = pop(tl, 0.0, 0.45);
  const glow = 0.5 + 0.5 * Math.sin(tl * 3);
  const text = (align: "center" | "left", size = 66) => (
    <div style={{ fontSize: size, fontWeight: 800, lineHeight: 1.22, textAlign: align }}>
      {richWords(s.text, s.highlights, brand, tl)}
    </div>
  );
  const iconBubble = (size: number) => Icon && (
    <div style={{ width: size, height: size, borderRadius: size / 2, background: brand.surface,
      display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${ik})`,
      boxShadow: `0 0 0 4px ${brand.accent}88, 0 0 ${40 + 30 * glow}px ${brand.accent}44` }}>
      <Icon size={size * 0.52} color={brand.accent} strokeWidth={2} />
    </div>
  );
  const exit = exitOf(tl, dur);
  if (s.style === 1) {
    return (
      <AbsoluteFill style={{ opacity: exit }}>
        <div style={{ position: "absolute", left: 90, right: 90, top: 470 }}>
          <div style={{ marginBottom: 40 }}>{iconBubble(150)}</div>
          <div style={{ display: "flex", gap: 34 }}>
            <div style={{ width: 12, borderRadius: 6, background: brand.accent,
              transform: `scaleY(${ramp(tl, 0, 0.5)})`, transformOrigin: "top" }} />
            {text("left")}
          </div>
        </div>
      </AbsoluteFill>
    );
  }
  if (s.style === 2 && s.n) {
    return (
      <AbsoluteFill style={{ opacity: exit }}>
        <div style={{ position: "absolute", top: 250, left: 0, right: 0, textAlign: "center", fontSize: 400,
          fontWeight: 800, color: brand.surface, lineHeight: 1, transform: `scale(${lerp(1.15, 1, ramp(tl, 0, 0.6))})` }}>
          {String(s.n).padStart(2, "0")}</div>
        <div style={{ position: "absolute", top: 660, left: 90, right: 90, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 36 }}>
          {iconBubble(120)}
          {text("center", 64)}
        </div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <div style={{ position: "absolute", top: Icon ? 420 : 560, left: 90, right: 90, display: "flex",
        flexDirection: "column", alignItems: "center", gap: 48 }}>
        {iconBubble(220)}
        {text("center")}
        <div style={{ height: 8, borderRadius: 4, background: brand.accent, width: 200 * ramp(tl, 0.2, 0.7) }} />
      </div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ con số lớn
const PeopleGrid: React.FC<{ s: BigNumberScene; brand: Brand; tl: number; dur: number; top: number }> = ({ s, brand, tl, dur, top }) => {
  const iso = s.isotype!;
  const COLS = 10, CELL = 64, LEFT = (1080 - COLS * CELL) / 2;
  const Item = iso.icon ? ICONS[iso.icon] : undefined;
  const at = 0.1 * dur, span = 0.5 * dur;
  const cells: React.ReactNode[] = [];
  for (let i = 0; i < 100; i++) {
    const r = Math.floor(i / COLS), c = i % COLS;
    const p = pop(tl, (r + c) * 0.02, 0.25);
    const lit = iso.mode === "share" ? i < iso.count && tl >= at + (i / Math.max(iso.count, 1)) * span : false;
    const item = iso.mode === "per100" && i < iso.count ? pop(tl, at + (i / Math.max(iso.count, 1)) * span, 0.25) : 0;
    cells.push(
      <div key={i} style={{ position: "absolute", left: LEFT + c * CELL, top: top + r * CELL, width: CELL, height: CELL,
        transform: `scale(${p})` }}>
        <PersonStanding size={44} color={lit ? brand.accent : iso.mode === "per100" ? brand.text : brand.muted}
          strokeWidth={2.3} style={{ position: "absolute", left: 4, top: 8, opacity: lit || iso.mode === "per100" ? 0.95 : 0.45 }} />
        {item > 0 && Item && <Item size={28} color={brand.accent} strokeWidth={2.8}
          style={{ position: "absolute", left: 36, top: 28, transform: `scale(${item})` }} />}
      </div>,
    );
  }
  const extra = iso.mode === "per100" ? Math.max(iso.count - 100, 0) : 0;
  for (let j = 0; j < extra; j++) {
    const r = Math.floor(j / COLS), c = j % COLS;
    const d = ramp(tl, at + span + j * 0.02, at + span + 0.35 + j * 0.02, Easing.out(Easing.bounce));
    cells.push(Item && (
      <div key={`x${j}`} style={{ position: "absolute", left: LEFT + c * CELL + 12, top: top + (10 + r) * CELL + 14 - (1 - d) * 200,
        opacity: d > 0 ? 1 : 0 }}><Item size={40} color={brand.accent} strokeWidth={2.6} /></div>
    ));
  }
  return <>{cells}</>;
};

export const BigNumber: React.FC<P<BigNumberScene>> = ({ s, brand, tl, dur }) => {
  const k = countK(tl, dur);
  const txt = fmtDec(s.value * k, s.dec);
  const final = fmtDec(s.value, s.dec);
  const panel = !!s.chart;
  const iso = !panel && !!s.isotype;
  const size = fitSize(final, 900, iso ? 150 : panel ? 190 : 240);
  const top = iso ? 300 : panel ? 380 : 560;
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      <div style={{ position: "absolute", top, left: 40, right: 40, display: "flex", flexDirection: "column", alignItems: "center",
        gap: iso ? 4 : 18 }}>
        {!iso && s.flag && <div style={{ transform: `scale(${pop(tl, 0.05, 0.4)})` }}><Flag code={s.flag} w={110} /></div>}
        <div style={{ display: "flex", alignItems: "baseline", gap: 20 }}>
          {iso && s.flag && <Flag code={s.flag} w={70} />}
          <span style={{ fontSize: size, fontWeight: 800, lineHeight: 1, color: s.color,
            textShadow: `0 0 70px ${s.color}55` }}>{txt}</span>
          {iso && <span style={{ fontSize: 50, fontWeight: 700, color: brand.text }}>{s.suffix}</span>}
        </div>
        {!iso && s.suffix && <div style={{ fontSize: 48, fontWeight: 700, color: brand.text, textAlign: "center" }}>{s.suffix}</div>}
      </div>
      {iso && <PeopleGrid s={s} brand={brand} tl={tl} dur={dur} top={490} />}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ so găng
export const Versus: React.FC<P<VersusScene>> = ({ s, brand, tl, dur }) => {
  const k = countK(tl, dur);
  const panel = !!s.chart;
  const sides: [Valued, number][] = [[s.left, 280], [s.right, 800]];
  const longest = Math.max(fmtDec(s.left.value, s.left.dec).length, fmtDec(s.right.value, s.right.dec).length);
  const size = fitSize("0".repeat(longest), 430, panel ? 120 : 140);
  const vmax = Math.max(Math.abs(s.left.value), Math.abs(s.right.value), 1e-9);
  const top = panel ? 360 : 420;
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      <div style={{ position: "absolute", left: 539, width: 3, top: top + 10, height: panel ? 380 : 420,
        background: brand.muted, opacity: 0.35 * ramp(tl, 0, 0.4) }} />
      {sides.map(([v, cx], i) => (
        <div key={i} style={{ position: "absolute", top, left: cx - 250, width: 500, display: "flex", flexDirection: "column",
          alignItems: "center", gap: 14, transform: `translateY(${(1 - pop(tl, 0.05 + i * 0.1, 0.45)) * 40}px)`,
          opacity: ramp(tl, 0.05 + i * 0.1, 0.3 + i * 0.1) }}>
          <Flag code={v.flag} w={panel ? 84 : 100} />
          <div style={{ fontSize: 44, fontWeight: 800, color: v.color, textAlign: "center", lineHeight: 1.15 }}>{v.label}</div>
          <div style={{ fontSize: size, fontWeight: 800, color: v.color, lineHeight: 1.05,
            textShadow: `0 0 60px ${v.color}55` }}>{fmtDec(v.value * k, v.dec)}</div>
        </div>
      ))}
      {s.suffix && (
        <div style={{ position: "absolute", top: top + (panel ? 360 : 400), left: 60, right: 60, textAlign: "center",
          fontSize: 40, fontWeight: 700, color: brand.text, opacity: ramp(tl, 0.2, 0.5) }}>{s.suffix}</div>
      )}
      {!panel && sides.map(([v, cx], i) => {
        const h = 330 * Math.max(v.value, 0) / vmax * k;
        return <div key={`b${i}`} style={{ position: "absolute", left: cx - 90, width: 180, top: 1270 - h, height: Math.max(h, 4),
          borderRadius: "14px 14px 4px 4px", background: `linear-gradient(180deg, ${v.color}, ${v.color}55)`,
          boxShadow: `0 0 40px ${v.color}44` }} />;
      })}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ xếp hạng
export const BarChart: React.FC<P<BarChartScene>> = ({ s, brand, tl, dur }) => {
  const items = s.items.slice(0, 6);
  const vmax = Math.max(...items.map((i) => Math.abs(i.value)), 1e-9);
  const k = countK(tl, dur);
  // ít hàng thì hàng to hơn và cả khối căn giữa vùng 380-1300 (không dồn lên trên, trống phía dưới)
  const pitch = Math.min(200, 860 / Math.max(items.length, 1));
  const barH = Math.round(Math.min(70, pitch * 0.36));
  const top0 = 380 + (920 - items.length * pitch) / 2;
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      {items.map((it, i) => {
        const top = top0 + i * pitch;
        const appear = ramp(tl, 0.05 + i * 0.08, 0.3 + i * 0.08);
        const w = 640 * Math.max(it.value, 0) / vmax * ramp(tl, 0.1 + i * 0.08, 0.62 * dur, Easing.out(Easing.cubic));
        return (
          <div key={i} style={{ position: "absolute", top, left: 90, right: 60, opacity: appear }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 38, fontWeight: 800, color: it.color }}>
              <Flag code={it.flag} w={52} />{it.label}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 10 }}>
              <div style={{ width: Math.max(w, 6), height: barH, borderRadius: 10,
                background: `linear-gradient(90deg, ${it.color}88, ${it.color})`, boxShadow: `0 0 30px ${it.color}33` }} />
              <span style={{ fontSize: 44, fontWeight: 800, color: brand.text }}>{fmtDec(it.value * k, it.dec)}</span>
            </div>
          </div>
        );
      })}
      {s.unit && <div style={{ position: "absolute", top: top0 + items.length * pitch + 10, left: 60, right: 60,
        textAlign: "center", fontSize: 34, fontWeight: 600, color: brand.muted }}>{s.unit}</div>}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ phần trăm
export const PercentRing: React.FC<P<PercentScene>> = ({ s, brand, tl, dur }) => {
  const k = countK(tl, dur);
  const v = Math.max(0, Math.min(s.value, 100));
  const R = 270, C = 2 * Math.PI * R;
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      <svg width={1080} height={1920} style={{ position: "absolute" }}>
        <circle cx={540} cy={820} r={R} fill="none" stroke={brand.surface} strokeWidth={50} />
        <circle cx={540} cy={820} r={R} fill="none" stroke={brand.accent} strokeWidth={50} strokeLinecap="round"
          strokeDasharray={`${(C * v * k) / 100} ${C}`} transform="rotate(-90 540 820)"
          style={{ filter: `drop-shadow(0 0 24px ${brand.accent}88)` }} />
      </svg>
      <div style={{ position: "absolute", top: 820 - 80, left: 0, right: 0, textAlign: "center", fontSize: fitSize(fmtDec(s.value, s.dec) + "%", 420, 150),
        fontWeight: 800, color: brand.accent, lineHeight: "160px" }}>{fmtDec(s.value * k, s.dec)}%</div>
      {s.label && <div style={{ position: "absolute", top: 1150, left: 70, right: 70, textAlign: "center", fontSize: 42,
        fontWeight: 700, color: brand.text, opacity: ramp(tl, 0.2, 0.5) }}>{s.label}</div>}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ biểu đồ đường: chỉ tiêu đề,
// phần biểu đồ do ChartWorld vẽ (sống xuyên các cảnh)
export const LineChartTitle: React.FC<P<LineChartScene>> = ({ s, brand, tl }) => (
  <AbsoluteFill><SceneTitle text={s.title} brand={brand} tl={tl} /></AbsoluteFill>
);

// ------------------------------------------------------------------ cảnh Manim dựng sẵn
export const Clip: React.FC<P<ClipScene>> = ({ s, tl, dur }) => (
  <AbsoluteFill style={{ opacity: ramp(tl, 0, 0.15) * exitOf(tl, dur) }}>
    <OffthreadVideo src={staticFile(s.src)} muted />
  </AbsoluteFill>
);
