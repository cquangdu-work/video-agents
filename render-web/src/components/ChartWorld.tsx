import React from "react";
import { AbsoluteFill, Easing, Img, staticFile } from "remotion";
import { Brand, ChartState, Scene, World } from "../types";
import { fmtDec, labelDec, lerp, pop, ramp } from "../lib/anim";
import { exactAt, lastKnown, niceStep, valueAt } from "../lib/series";

// BIỂU ĐỒ CHÍNH sống suốt video (không nằm trong một cảnh nào): mỗi cảnh chỉ khai "trạng thái"
// của nó (ChartState) — toàn màn hình (cảnh line_chart), thu xuống nửa dưới làm nền cho cảnh
// so găng / con số lớn đang nói về một điểm trên biểu đồ (panel), hoặc ẩn (cảnh chữ...).
// Giữa hai cảnh, khung nhìn (năm, giá trị) và khung hình trượt mượt sang trạng thái mới, phần
// đường đã vẽ thì giữ nguyên -> người xem thấy MỘT câu chuyện trên MỘT biểu đồ.

type Rect = { left: number; right: number; top: number; bottom: number };
type View = [number, number, number, number]; // x0, x1, y0, y1 (đơn vị dữ liệu)
const FULL: Rect = { left: 150, right: 990, top: 480, bottom: 1250 };
const PANEL: Rect = { left: 150, right: 990, top: 900, bottom: 1255 };
const MOVE = 0.6; // giây chuyển khung nhìn giữa hai cảnh

// Cảnh chữ (statement) cũng giữ biểu đồ ở nửa dưới khi Python gắn trạng thái cho nó (từ 19/11/2026)
const stateOf = (sc: Scene): ChartState | undefined =>
  sc.kind === "line_chart" || sc.kind === "versus" || sc.kind === "big_number" || sc.kind === "statement"
    ? sc.chart : undefined;

const lerpView = (a: View, b: View, k: number) => a.map((x, i) => lerp(x, b[i], k)) as View;
const lerpRect = (a: Rect, b: Rect, k: number): Rect => ({
  left: lerp(a.left, b.left, k), right: lerp(a.right, b.right, k), top: lerp(a.top, b.top, k), bottom: lerp(a.bottom, b.bottom, k),
});

function fullView(w: World): View {
  const R = w.maxX - w.minX || 1;
  return [w.minX - 0.04 * R, w.maxX + 0.1 * R, -w.yMax * 0.07, w.yMax * 1.15];
}

/** Khung nhìn bám theo đầu đường đang vẽ: trục y co giãn theo phần số liệu đã hiện. */
function followView(w: World, head: number): View {
  const R = w.maxX - w.minX || 1;
  let top = w.yMax * 0.08;
  for (const s of w.series) {
    s.xs.forEach((x, i) => { if (x <= head) top = Math.max(top, s.ys[i]); });
    const v = valueAt(s, head);
    if (v !== null) top = Math.max(top, v);
  }
  return [w.minX - 0.04 * R, Math.max(head + 0.1 * R, w.minX + 0.35 * R), -top * 0.08, top * 1.2];
}

function focusView(w: World, st: ChartState): View {
  const R = w.maxX - w.minX || 1;
  const xs = (st.focus ?? []).map((f) => f.x);
  const f0 = Math.min(...xs), f1 = Math.max(...xs);
  let x0 = Math.max(w.minX - 0.04 * R, f0 - 0.3 * R), x1 = Math.min(w.maxX + 0.1 * R, f1 + 0.3 * R);
  if (x1 - x0 < 0.45 * R) { const c = (x0 + x1) / 2; x0 = c - 0.225 * R; x1 = c + 0.225 * R; }
  return [x0, x1, -w.yMax * 0.07, w.yMax * 1.15];
}

function targetView(w: World, st: ChartState, drawn: number, tl: number, dur: number): View {
  if (st.mode === "panel" && st.focus?.length) return focusView(w, st);
  return lerpView(followView(w, drawn), fullView(w), ramp(tl, 0.55 * dur, 0.8 * dur));
}

type Plan = {
  start: number; end: number; st?: ChartState;
  drawFrom: number; drawEnd: number;
  prevView: View; prevBox: Rect; prevVisible: boolean; prevFull: boolean;
  endView: View; endBox: Rect;
};

function makePlan(scenes: Scene[], w: World): Plan[] {
  let drawn = w.minX, view = fullView(w), box = FULL, visible = false, full = false;
  return scenes.map((sc) => {
    const st = stateOf(sc), dur = sc.end - sc.start;
    const p: Plan = {
      start: sc.start, end: sc.end, st, drawFrom: drawn, drawEnd: drawn,
      prevView: view, prevBox: box, prevVisible: visible, prevFull: full, endView: view, endBox: box,
    };
    if (st) {
      p.drawEnd = Math.max(drawn, Math.min(st.drawTo, w.maxX));
      drawn = p.drawEnd;
      view = targetView(w, st, p.drawEnd, dur, dur);
      box = st.mode === "full" ? FULL : PANEL;
    }
    visible = !!st;
    full = !!st && st.mode === "full";
    p.endView = view; p.endBox = box;
    return p;
  });
}

export const ChartWorld: React.FC<{ world: World; scenes: Scene[]; t: number; brand: Brand }> = ({ world: w, scenes, t, brand }) => {
  const plans = React.useMemo(() => makePlan(scenes, w), [scenes, w]);
  let k = 0;
  for (let i = 0; i < plans.length; i++) if (plans[i].start <= t + 1e-6) k = i;
  const p = plans[k], st = p.st, tl = t - p.start, dur = p.end - p.start;

  const opacity = st ? (p.prevVisible ? 1 : ramp(tl, 0, 0.4)) : (p.prevVisible ? 1 - ramp(tl, 0, 0.35) : 0);
  if (opacity <= 0.001) return null;

  const drawn = !st ? p.drawFrom
    : st.mode === "full" ? lerp(p.drawFrom, p.drawEnd, ramp(tl, 0.08 * dur, 0.7 * dur, Easing.inOut(Easing.cubic)))
      : lerp(p.drawFrom, p.drawEnd, ramp(tl, 0.1, 0.9));
  const move = ramp(tl, 0, MOVE);
  const [x0, x1, y0, y1] = st ? lerpView(p.prevView, targetView(w, st, drawn, tl, dur), move) : p.prevView;
  const box = st ? lerpRect(p.prevBox, st.mode === "full" ? FULL : PANEL, move) : p.prevBox;
  const isFull = st ? st.mode === "full" : false;
  const fullness = st ? (isFull ? (p.prevFull ? 1 : move) : (p.prevFull ? 1 - move : 0)) : (p.prevFull ? 1 - ramp(tl, 0, 0.35) : 0);
  const W = box.right - box.left, H = box.bottom - box.top;
  const X = (x: number) => box.left + ((x - x0) / (x1 - x0)) * W;
  const Y = (y: number) => box.bottom - ((y - y0) / (y1 - y0)) * H;

  // ---- lưới
  const ys = niceStep(y1 - y0, H, H > 500 ? 110 : 85), xs = Math.max(1, niceStep(x1 - x0, W, 150));
  const yTicks: number[] = [], xTicks: number[] = [];
  for (let i = Math.ceil(y0 / ys); i * ys <= y1; i++) { const v = +(i * ys).toFixed(6); if (v >= 0) yTicks.push(v); }
  for (let i = Math.ceil(x0 / xs); i * xs <= x1; i++) { const v = i * xs; if (v >= w.minX && v <= w.maxX) xTicks.push(v); }

  const order = w.series.map((_, i) => i).sort((a, b) => Number(!!w.series[a].emphasis) - Number(!!w.series[b].emphasis));
  const pathOf = (i: number) => {
    const se = w.series[i];
    const pts: [number, number][] = [];
    se.xs.forEach((x, j) => { if (x <= drawn) pts.push([x, se.ys[j]]); });
    const v = valueAt(se, drawn);
    if (v !== null && (!pts.length || pts[pts.length - 1][0] < drawn)) pts.push([drawn, v]);
    return pts.map(([x, y], j) => `${j ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  };
  const fmtS = (i: number, v: number) => fmtDec(v, labelDec(v, w.series[i].dec ?? 2));

  // ---- đầu đường (chỉ ở chế độ toàn màn hình): nhãn hiện SỐ THẬT gần nhất
  const heads = isFull ? w.series.map((se, i) => {
    const v = valueAt(se, drawn), kn = lastKnown(se, drawn);
    return v === null || !kn ? null : { i, v: kn.y, x: X(drawn), y: Y(v) };
  }).filter(Boolean) as { i: number; v: number; x: number; y: number }[] : [];
  const headsSorted = [...heads].sort((a, b) => a.y - b.y);
  const emph = w.series.find((s) => s.emphasis) ?? w.series[0];
  const year = lastKnown(emph, drawn)?.x ?? w.minX;

  // ---- điểm được nhắc tới (chế độ panel)
  const focus = st && st.mode === "panel" ? (st.focus ?? []).map((f) => {
    const v = exactAt(w.series[f.s], f.x);
    return v === null ? null : { ...f, v, px: X(f.x), py: Y(v) };
  }).filter(Boolean) as { s: number; x: number; v: number; px: number; py: number }[] : [];
  const focusSorted = [...focus].sort((a, b) => a.py - b.py);
  const fk = pop(tl, 0.45, 0.4);

  // ---- chú thích con số chốt: đặt vào góc trống nhất của biểu đồ
  const co = st?.callout;
  const call = co && isFull ? pop(t, co.at, 0.45) : 0;
  let cpos = { left: box.left + 30, top: box.top + 20 };
  if (call > 0) {
    const cands = [
      { left: box.left + 30, top: box.top + 20 }, { left: box.right - 480, top: box.top + 20 },
      { left: box.left + 30, top: box.bottom - 300 }, { left: box.right - 480, top: box.bottom - 300 },
    ];
    let best = Infinity;
    for (const c of cands) {
      let hits = 0;
      for (const se of w.series) for (let j = 0; j <= 60; j++) {
        const x = w.minX + ((w.maxX - w.minX) * j) / 60, v = valueAt(se, x);
        if (v === null) continue;
        const sx = X(x), sy = Y(v);
        if (sx > c.left - 20 && sx < c.left + 480 && sy > c.top - 20 && sy < c.top + 280) hits++;
      }
      if (hits < best) { best = hits; cpos = c; }
    }
  }
  const coHead = co ? heads.find((h) => h.i === co.s) : undefined;

  // ---- NGOẶC ĐO KHOẢNG CÁCH năm cuối (24/11/2026: chuyển động phải giúp hiểu số liệu) — chỉ khi đường đã vẽ tới
  // năm cuối ở chế độ toàn màn hình: ngoặc mọc từ giữa ra hai đầu, rồi hiện "×5,06" / "24 điểm %" do Python tính
  const gp = w.gap;
  const gva = gp ? exactAt(w.series[gp.a], gp.x) : null, gvb = gp ? exactAt(w.series[gp.b], gp.x) : null;
  // cảnh vẽ tới năm cuối: ngoặc mọc khi đường vẽ xong; các cảnh SAU còn giữ biểu đồ (thu xuống nửa dưới): ngoặc ở
  // sẵn — cảnh line_chart có khi chỉ 3 giây, chưa kịp đọc (bản thử 24/11, video #10)
  const firstDraw = isFull && p.drawFrom < w.maxX - 1e-6;
  const gxRaw = gp ? X(gp.x) + 44 : 0;
  const gk = gp && st && p.drawEnd >= w.maxX - 1e-6 && gva !== null && gvb !== null && gxRaw <= box.right + 60
    ? (firstDraw ? ramp(tl, 0.72 * dur, 0.72 * dur + 0.5, Easing.out(Easing.cubic)) : opacity) : 0;
  const gx = gxRaw, gya = gva !== null ? Y(gva) : 0, gyb = gvb !== null ? Y(gvb) : 0;
  const gmid = (gya + gyb) / 2, ghalf = Math.abs(gya - gyb) / 2 * gk;
  const ref = w.reference && y1 > w.reference.y * 1.08 ? ramp(y1, w.reference.y * 1.08, w.reference.y * 1.3) : 0;

  return (
    <AbsoluteFill style={{ opacity }}>
      <svg width={1080} height={1920} style={{ position: "absolute" }}>
        <defs>
          <clipPath id="cw"><rect x={box.left - 4} y={box.top - 40} width={W + 40} height={H + 44} /></clipPath>
        </defs>
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={box.left} x2={box.right} y1={Y(v)} y2={Y(v)} stroke={brand.surface} strokeWidth={v === 0 ? 4 : 2} />
            <text x={box.left - 18} y={Y(v) + 10} fill={brand.muted} fontSize={28} fontWeight={600} textAnchor="end">
              {fmtDec(v, labelDec(v, 2))}</text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text key={`x${v}`} x={X(v)} y={box.bottom + 48} fill={brand.muted} fontSize={28} fontWeight={600} textAnchor="middle">{v}</text>
        ))}
        {w.reference && ref > 0 && (
          <g opacity={ref}>
            <line x1={box.left} x2={box.right} y1={Y(w.reference.y)} y2={Y(w.reference.y)} stroke={brand.text}
              strokeOpacity={0.5} strokeWidth={3} strokeDasharray="14 12" />
            <text x={box.left + 10} y={Y(w.reference.y) - 14} fill={brand.text} fillOpacity={0.75} fontSize={28} fontWeight={600}>
              {w.reference.label}</text>
          </g>
        )}
        {focus.map((f, j) => (
          <line key={`fl${j}`} x1={f.px} x2={f.px} y1={box.bottom} y2={box.top - 6} stroke={brand.accent}
            strokeOpacity={0.8 * Math.min(fk, 1)} strokeWidth={3} strokeDasharray="12 10" />
        ))}
        <g clipPath="url(#cw)">
          {order.map((i) => {
            const se = w.series[i], d = pathOf(i), em = !!se.emphasis;
            return (
              <g key={i} opacity={em ? 1 : 0.85}>
                <path d={d} fill="none" stroke={se.color} strokeOpacity={0.18} strokeWidth={22} strokeLinejoin="round" strokeLinecap="round" />
                <path d={d} fill="none" stroke={se.color} strokeWidth={em ? 8 : 7} strokeLinejoin="round" strokeLinecap="round" />
              </g>
            );
          })}
          {heads.map((h) => (
            <g key={`h${h.i}`} opacity={fullness}>
              <circle cx={h.x} cy={h.y} r={22 + 9 * Math.sin(t * 6)} fill={w.series[h.i].color} fillOpacity={0.2} />
              <circle cx={h.x} cy={h.y} r={13} fill={w.series[h.i].color} stroke={brand.background} strokeWidth={4} />
            </g>
          ))}
          {focus.map((f, j) => [0, 1].map((r) => {
            const rr = 18 + ((t * 60 + r * 30) % 60);
            return <circle key={`fr${j}${r}`} cx={f.px} cy={f.py} r={rr} fill="none" stroke={w.series[f.s].color}
              strokeWidth={4} strokeOpacity={Math.min(fk, 1) * (1 - (rr - 18) / 60)} />;
          }))}
          {focus.map((f, j) => (
            <circle key={`fd${j}`} cx={f.px} cy={f.py} r={14 * Math.min(fk, 1.2)} fill={w.series[f.s].color} stroke={brand.background} strokeWidth={4} />
          ))}
        </g>
        {gk > 0 && (
          <g opacity={Math.min(1, gk * 1.5)}>
            <line x1={gx} x2={gx} y1={gmid - ghalf} y2={gmid + ghalf} stroke={brand.accent} strokeWidth={5} />
            <line x1={gx - 16} x2={gx} y1={gmid - ghalf} y2={gmid - ghalf} stroke={brand.accent} strokeWidth={5} />
            <line x1={gx - 16} x2={gx} y1={gmid + ghalf} y2={gmid + ghalf} stroke={brand.accent} strokeWidth={5} />
          </g>
        )}
        {call > 0 && coHead && [0, 1].map((j) => {
          const r = 20 + ((t * 70 + j * 35) % 70);
          return <circle key={`c${j}`} cx={coHead.x} cy={coHead.y} r={r} fill="none" stroke={brand.accent}
            strokeWidth={4} strokeOpacity={Math.min(call, 1) * (1 - (r - 20) / 70)} />;
        })}
      </svg>

      {headsSorted.map((h, j) => {
        const se = w.series[h.i];
        const leftSide = h.x > box.right - 330;
        const fadeForCall = co && h.i === co.s ? 1 - ramp(t, co.at, co.at + 0.25) : 1;
        return (
          <div key={`l${h.i}`} style={{
            position: "absolute", top: j === 0 ? h.y - 90 : h.y + 26,
            left: leftSide ? undefined : h.x + 4, right: leftSide ? 1080 - h.x + 4 : undefined,
            display: "flex", alignItems: "center", gap: 12, fontSize: 38, fontWeight: 800, color: se.color,
            opacity: fullness * fadeForCall, textShadow: "0 2px 12px rgba(0,0,0,0.8)", whiteSpace: "nowrap",
          }}>
            {se.flag && <Img src={staticFile(`flags/${se.flag}.svg`)} style={{ width: 50, height: 37, borderRadius: 5 }} />}
            <span>{se.label}</span>
            <span style={{ color: brand.text }}>{fmtS(h.i, h.v)}</span>
          </div>
        );
      })}

      {focusSorted.map((f, j) => {
        const se = w.series[f.s];
        const leftSide = f.px > box.right - 300;
        return (
          <div key={`fv${j}`} style={{
            // điểm cao hơn ghi nhãn phía trên, điểm thấp hơn ghi phía dưới -> hai nhãn không chồng nhau
            position: "absolute", top: j === 0 ? f.py - 84 : f.py + 24,
            left: leftSide ? undefined : f.px + 18, right: leftSide ? 1080 - f.px + 18 : undefined,
            display: "flex", alignItems: "center", gap: 10, fontSize: 36, fontWeight: 800, color: se.color,
            transform: `scale(${fk})`, transformOrigin: leftSide ? "right center" : "left center",
            textShadow: "0 2px 12px rgba(0,0,0,0.85)", whiteSpace: "nowrap",
          }}>
            {se.flag && <Img src={staticFile(`flags/${se.flag}.svg`)} style={{ width: 44, height: 33, borderRadius: 5 }} />}
            <span style={{ color: brand.text }}>{fmtS(f.s, f.v)}</span>
          </div>
        );
      })}
      {[...new Set(focus.map((f) => f.x))].map((x) => (
        <div key={`fy${x}`} style={{ position: "absolute", top: box.top - 62, left: X(x) - 100, width: 200, textAlign: "center",
          fontSize: 36, fontWeight: 800, color: brand.accent, opacity: Math.min(fk, 1) }}>{x}</div>
      ))}

      {gk > 0 && gp && (() => {
        const roomy = Math.abs(gya - gyb) >= 200;
        const top = roomy ? gmid - 60 : Math.max(gya, gyb) + 70;
        const k = firstDraw ? ramp(tl, 0.72 * dur + 0.35, 0.72 * dur + 0.8) : gk;
        const small = !isFull;
        return (
          <div style={{ position: "absolute", right: 1080 - gx + 24, top, textAlign: "right", opacity: k,
            transform: `translateX(${(1 - k) * 20}px)` }}>
            <div style={{ display: "inline-block", fontSize: small ? 46 : 64, fontWeight: 800, color: brand.background, lineHeight: 1.1,
              background: brand.accent, borderRadius: 16, padding: "4px 18px" }}>{gp.value}</div>
            {roomy && <div style={{ marginTop: 8, fontSize: small ? 24 : 30, fontWeight: 700, color: brand.text,
              whiteSpace: "nowrap", textShadow: "0 2px 12px rgba(0,0,0,0.9)" }}>{gp.label}</div>}
          </div>
        );
      })()}

      {fullness > 0 && (
        <div style={{ position: "absolute", top: 362, right: 90, fontSize: 92, fontWeight: 800, color: brand.accent,
          lineHeight: 1, opacity: 0.9 * fullness, textShadow: `0 0 50px ${brand.accent}44` }}>{year}</div>
      )}

      {call > 0 && co && (
        <div style={{ position: "absolute", left: cpos.left, top: cpos.top, transform: `scale(${call})`, transformOrigin: "left top" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 36, fontWeight: 800, color: w.series[co.s].color }}>
            {w.series[co.s].flag && <Img src={staticFile(`flags/${w.series[co.s].flag}.svg`)} style={{ width: 46, height: 34, borderRadius: 5 }} />}
            {w.series[co.s].label}
          </div>
          <div style={{ fontSize: 140, fontWeight: 800, color: brand.accent, lineHeight: 1.05, textShadow: `0 0 50px ${brand.accent}55` }}>{co.value}</div>
          <div style={{ fontSize: 34, fontWeight: 700, color: brand.text, maxWidth: 460 }}>{co.label}</div>
        </div>
      )}
    </AbsoluteFill>
  );
};
