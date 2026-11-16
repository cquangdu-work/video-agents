import React from "react";
import { AbsoluteFill, Easing, Img, staticFile } from "remotion";
import { BarRaceScene, Brand, MapLabel, MapScene } from "../types";
import { lerp, pop, ramp } from "../lib/anim";
import { SceneTitle } from "./Generic";

// BẢN ĐỒ và CUỘC ĐUA SỐ LIỆU. Mọi hình học do Python tính (src/render/web_map.py) — kể cả
// Hoàng Sa, Trường Sa luôn có mặt, cùng màu Việt Nam, có tên. Ở đây chỉ tô màu và chuyển động.
// Hoạt hình xong trước ~70% cảnh (Kiểm định chụp khung ở 85%).

type P<S> = { s: S; brand: Brand; tl: number; dur: number };
const exitOf = (tl: number, dur: number) => 1 - ramp(tl, dur - 0.15, dur);

/** Mép trái nhãn số (bản đồ châu Á): đặt quanh điểm Python chọn ở vùng biển trống, không tràn mép phải. */
const tagLeft = (c: { label: string; value: string; x: number }) => {
  const w = Math.max(c.label.length * 0.56 * 32, c.value.length * 0.62 * 46);
  return Math.min(c.x - 60, 1050 - w);
};

const Label: React.FC<{ l: MapLabel; brand: Brand }> = ({ l, brand }) => (
  <text x={l.x} y={l.y + l.size * 0.35} fontSize={l.size} fontWeight={800} fill={l.color} textAnchor={l.anchor}
    stroke={brand.background} strokeWidth={5} paintOrder="stroke" strokeLinejoin="round">{l.text}</text>
);

export const MapView: React.FC<P<MapScene>> = ({ s, brand, tl, dur }) => {
  const fillStart = 0.35, fillSpan = Math.max(0.6, 0.4 * dur);
  const fillEnd = fillStart + fillSpan;
  const late = ramp(tl, fillEnd - 0.1, fillEnd + 0.4);
  const cam = lerp(1.0, 1.035, ramp(tl, 0, dur, Easing.linear));
  const glow = 0.5 + 0.5 * Math.sin(tl * 4);
  const inset = s.inset;
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      <svg width={1080} height={1920} style={{ position: "absolute" }}>
        <g style={{ transform: `scale(${cam})`, transformOrigin: s.region === "world" ? "540px 720px" : "540px 790px" }}>
          <path d={s.outline} fill="none" stroke={brand.muted} strokeOpacity={0.45 * ramp(tl, 0, 0.35)} strokeWidth={1} />
          {s.fills.map((f) => {
            // tô từ thấp lên cao: mắt theo được thứ hạng
            const a = fillStart + f.k * (fillSpan - 0.3);
            const o = ramp(tl, a, a + 0.3);
            return (
              <g key={f.code} opacity={o}>
                <path d={f.d} fill={f.color} stroke={brand.background} strokeWidth={0.8} />
                {f.dot && <circle cx={f.dot[0]} cy={f.dot[1]} r={f.dot[2]} fill={f.color} />}
              </g>
            );
          })}
          {/* Hoàng Sa, Trường Sa: hiện ngay từ đầu cùng nền bản đồ, cùng màu Việt Nam */}
          {s.islands.map(([x, y], i) => <circle key={`i${i}`} cx={x} cy={y} r={s.region === "world" ? 1.8 : 3.4} fill={s.islandColor} />)}
          {s.islandLabels.map((l) => <Label key={l.text} l={l} brand={brand} />)}
          {s.marks.map((m, i) => (
            <g key={`m${i}`} opacity={late}>
              <path d={m.d} fill="none" stroke={m.color} strokeOpacity={0.35 * glow} strokeWidth={12} strokeLinejoin="round" />
              <path d={m.d} fill="none" stroke={m.color} strokeWidth={s.region === "world" ? 3 : 4} strokeLinejoin="round" />
            </g>
          ))}
          {s.callouts?.map((c, i) => {
            const k = pop(tl, fillEnd + 0.1 + i * 0.15, 0.4);
            return k > 0 ? <line key={`cl${i}`} x1={tagLeft(c) - 8} y1={c.y} x2={c.to[0]} y2={c.to[1]} stroke={c.color}
              strokeWidth={3} opacity={Math.min(k, 1)} /> : null;
          })}
          {inset && (() => {
            const [[x0, y0], [x1, y1]] = inset.frame;
            const [[m0x, m0y], [m1x, m1y]] = inset.mark;
            const k = ramp(tl, fillEnd - 0.2, fillEnd + 0.3, Easing.out(Easing.cubic));
            return (
              <g opacity={k}>
                <rect x={m0x} y={m0y} width={m1x - m0x} height={m1y - m0y} fill="none" stroke={brand.text} strokeWidth={2} />
                <line x1={m0x} y1={m1y} x2={x0} y2={y0} stroke={brand.muted} strokeWidth={1.5} />
                <line x1={m1x} y1={m1y} x2={x1} y2={y0} stroke={brand.muted} strokeWidth={1.5} />
                <g style={{ transform: `translateY(${(1 - k) * 40}px)` }}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill={inset.background} stroke={brand.muted} strokeWidth={2} rx={8} />
                  {inset.shapes.map((sh, i) => (
                    <path key={`s${i}`} d={sh.d} fill={sh.fill ?? "none"} stroke={sh.stroke}
                      strokeWidth={sh.vn ? 2.5 : 1} strokeOpacity={sh.fill ? 1 : 0.5} />
                  ))}
                  {inset.islands.map(([x, y], i) => <circle key={`ii${i}`} cx={x} cy={y} r={3.6} fill={s.islandColor} />)}
                  {inset.labels.map((l) => <Label key={l.text} l={l} brand={brand} />)}
                </g>
              </g>
            );
          })()}
        </g>
      </svg>

      {s.callouts?.map((c, i) => {
        const k = pop(tl, fillEnd + 0.1 + i * 0.15, 0.4);
        const left = tagLeft(c);
        return (
          <div key={`c${i}`} style={{ position: "absolute", left, top: c.y - 52, transform: `scale(${k})`,
            transformOrigin: "left center", textShadow: "0 2px 10px rgba(0,0,0,0.9)" }}>
            <div style={{ fontSize: 32, fontWeight: 800, color: c.color }}>{c.label}</div>
            <div style={{ fontSize: 46, fontWeight: 800, color: c.color, lineHeight: 1 }}>{c.value}</div>
          </div>
        );
      })}

      {s.panel?.map((r, i) => {
        const k = pop(tl, fillEnd + 0.15 + i * 0.15, 0.4);
        return (
          <div key={`p${i}`} style={{ position: "absolute", left: 60, top: 1066 + i * 92, width: 620,
            transform: `translateX(${(1 - Math.min(k, 1)) * -40}px)`, opacity: Math.min(k, 1) }}>
            <div style={{ fontSize: 30, fontWeight: 800, color: r.color, whiteSpace: "nowrap", overflow: "hidden",
              textOverflow: "ellipsis" }}>{r.label}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
              <span style={{ fontSize: 46, fontWeight: 800, color: r.color, lineHeight: 1.05 }}>{r.value}</span>
              <span style={{ fontSize: 26, fontWeight: 600, color: brand.text }}>{r.pos}</span>
            </div>
          </div>
        );
      })}

      {s.legend && (() => {
        const lg = s.legend!;
        const world = s.region === "world";
        const k = ramp(tl, fillEnd - 0.1, fillEnd + 0.4);
        return (
          <div style={{ position: "absolute", top: lg.y, left: world ? 60 : 0, right: world ? undefined : 0, width: world ? 620 : undefined,
            display: "flex", flexDirection: "column", alignItems: world ? "flex-start" : "center", gap: 6, opacity: k }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 26, fontWeight: 700, color: brand.text }}>
              <span>{lg.lo}</span>
              <div style={{ display: "flex" }}>{lg.stops.map((c, i) => <div key={i} style={{ width: 34, height: 18, background: c }} />)}</div>
              <span>{lg.hi}</span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 600, color: brand.muted }}>{lg.caption}</div>
          </div>
        );
      })()}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------------- cuộc đua
export const BarRace: React.FC<P<BarRaceScene>> = ({ s, brand, tl, dur }) => {
  const n = s.items.length, legs = Math.max(s.years.length - 1, 1);
  const top = 400, rowH = Math.min(84, 800 / Math.max(n, 1)), barH = rowH * 0.62;
  const BAR_X = 400, BAR_W = 500;
  // chạy hết các mốc trong [0,5 giây .. 75% cảnh] rồi dừng ở năm cuối
  const prog = ramp(tl, 0.5, Math.max(0.75 * dur, 1.0), Easing.linear) * legs;
  const k = Math.min(Math.floor(prog), legs - 1);
  const f = Easing.inOut(Easing.cubic)(Math.min(prog - k, 1));
  const started = tl >= 0.5;
  const shownIdx = started ? Math.min(k + 1, s.years.length - 1) : 0; // số + năm đổi NGAY đầu chặng
  const layout = (j: number) => {
    const vals = s.items.map((it) => it.values[j]);
    const vmax = Math.max(...vals, 1e-9);
    const order = vals.map((_, i) => i).sort((a, b) => vals[b] - vals[a]);
    const rank: number[] = [];
    order.forEach((i, r) => { rank[i] = r; });
    return s.items.map((_, i) => ({ y: top + rank[i] * rowH, w: Math.max((vals[i] / vmax) * BAR_W, 4) }));
  };
  const a = layout(started ? k : 0), b = layout(started ? Math.min(k + 1, s.years.length - 1) : 0);
  const appear = ramp(tl, 0, 0.4);
  return (
    <AbsoluteFill style={{ opacity: exitOf(tl, dur) }}>
      <SceneTitle text={s.title} brand={brand} tl={tl} />
      {s.items.map((it, i) => {
        const y = lerp(a[i].y, b[i].y, f), w = lerp(a[i].w, b[i].w, f);
        return (
          <div key={i} style={{ position: "absolute", top: y, left: 0, width: 1080, height: rowH, opacity: appear }}>
            <div style={{ position: "absolute", right: 1080 - BAR_X + 14, top: (rowH - 40) / 2, display: "flex",
              alignItems: "center", gap: 10, fontSize: it.strong ? 32 : 28, fontWeight: it.strong ? 800 : 600,
              color: it.ink, whiteSpace: "nowrap" }}>
              {it.flag && <Img src={staticFile(`flags/${it.flag}.svg`)} style={{ width: 40, height: 30, borderRadius: 4 }} />}
              {it.label}
            </div>
            <div style={{ position: "absolute", left: BAR_X, top: (rowH - barH) / 2, width: w, height: barH, borderRadius: 8,
              background: it.strong ? `linear-gradient(90deg, ${it.fill}aa, ${it.fill})` : it.fill,
              opacity: it.strong ? 1 : 0.5, boxShadow: it.strong ? `0 0 30px ${it.fill}55` : undefined }} />
            <div style={{ position: "absolute", left: BAR_X + w + 12, top: (rowH - 38) / 2, fontSize: 30, fontWeight: 800,
              color: it.ink }}>{it.shown[shownIdx]}</div>
          </div>
        );
      })}
      <div style={{ position: "absolute", right: 70, top: top + n * rowH + 6, fontSize: 104, fontWeight: 800,
        color: brand.muted, opacity: appear, lineHeight: 1 }}>{s.years[shownIdx]}</div>
      {s.unit && <div style={{ position: "absolute", left: 70, top: top + n * rowH + 40, fontSize: 28, fontWeight: 600,
        color: brand.muted, opacity: appear }}>{s.unit}</div>}
    </AbsoluteFill>
  );
};
