import React from "react";
import { AbsoluteFill, Easing, Img, staticFile } from "remotion";
import { PhoneOff } from "lucide-react";
import { Brand, HeroLineScene, Series } from "../types";
import { fmtVi, lerp, pop, ramp } from "../lib/anim";

// BIỂU ĐỒ CHÍNH xuyên suốt nửa sau video: không cắt sang thẻ số trên nền đen nữa mà giữ một
// biểu đồ và cho "camera" (khung nhìn trên trục dữ liệu) di chuyển theo lời kể:
//   tua ngược năm -> vạch xuất phát -> đoạn nằm sát 0 -> vọt lên -> lùi ra thấy toàn cảnh -> chú thích.
// Đường vẽ lại theo khung nhìn ở MỖI khung hình nên nét luôn sắc, không bị phóng to vỡ.
const BOX = { left: 150, right: 990, top: 470, bottom: 1250 };
const W = BOX.right - BOX.left, H = BOX.bottom - BOX.top;
const REW = 1.3; // giây tua ngược năm ở đầu cảnh

type View = [number, number, number, number]; // x0, x1, y0, y1 trong đơn vị dữ liệu

function viewAt(t: number, kf: { t: number; v: View }[]): View {
  if (t <= kf[0].t) return kf[0].v;
  for (let i = 0; i + 1 < kf.length; i++) {
    const a = kf[i], b = kf[i + 1];
    if (t <= b.t) {
      const k = ramp(t, a.t, b.t, Easing.inOut(Easing.cubic));
      return a.v.map((x, j) => lerp(x, b.v[j], k)) as View;
    }
  }
  return kf[kf.length - 1].v;
}

/** Bước lưới đẹp (1-2-5) sao cho các vạch cách nhau ít nhất `minPx` điểm ảnh. */
function niceStep(range: number, px: number, minPx: number) {
  for (const s of [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000]) if ((s / range) * px >= minPx) return s;
  return 1000;
}

/** Giá trị nội suy của chuỗi tại năm x (trả null nếu chưa có số liệu ở đó). */
function valueAt(s: Series, x: number): number | null {
  if (x < s.xs[0]) return null;
  for (let i = 0; i + 1 < s.xs.length; i++) {
    if (x <= s.xs[i + 1]) {
      const k = (x - s.xs[i]) / (s.xs[i + 1] - s.xs[i]);
      return lerp(s.ys[i], s.ys[i + 1], k);
    }
  }
  return s.ys[s.ys.length - 1];
}

/** Điểm số liệu THẬT gần nhất <= năm x. Nhãn trên hình chỉ được hiện số này, không hiện số
 *  nội suy giữa hai năm (nội suy chỉ dùng để vẽ đường cho mượt — số đó không có trong bảng gốc). */
function lastKnown(s: Series, x: number): { x: number; y: number } | null {
  let out: { x: number; y: number } | null = null;
  s.xs.forEach((xx, i) => { if (xx <= x + 1e-6) out = { x: xx, y: s.ys[i] }; });
  return out;
}

export const HeroLine: React.FC<{ s: HeroLineScene; brand: Brand; tl: number; dur: number }> = ({ s, brand, tl, dur }) => {
  const b = {
    startLine: s.beats.startLine - s.start, flat: s.beats.flat - s.start,
    rise: s.beats.rise - s.start, callout: s.beats.callout - s.start,
  };
  // đường chạm năm cuối đúng lúc lời đọc nói con số chốt (nhưng không vọt nhanh hơn 1,5 giây)
  const riseEnd = Math.min(Math.max(b.callout, b.rise + 1.5), dur - 0.3);
  // năm đã vẽ tới
  const drawnX = tl < b.flat ? s.minX
    : tl < b.rise ? lerp(s.minX, s.flatUntil, ramp(tl, b.flat, b.rise - 0.1, Easing.inOut(Easing.quad)))
      : lerp(s.flatUntil, s.maxX, ramp(tl, b.rise, riseEnd, Easing.inOut(Easing.cubic)));
  const low = s.yMax * 0.2;
  const [x0, x1, y0, y1] = viewAt(tl, [
    { t: REW, v: [s.minX - 2.5, s.minX + 15, -low * 0.17, low] },
    { t: b.flat, v: [s.minX - 2.5, s.minX + 12, -low * 0.14, low * 0.85] },
    { t: b.rise, v: [s.minX - 2.5, s.flatUntil + 6, -low * 0.17, low] },
    { t: b.rise + 2.4, v: [s.minX - 4, s.maxX + 7, -s.yMax * 0.07, s.yMax * 1.12] },
  ]);
  const X = (x: number) => BOX.left + ((x - x0) / (x1 - x0)) * W;
  const Y = (y: number) => BOX.bottom - ((y - y0) / (y1 - y0)) * H;

  const axes = ramp(tl, REW - 0.3, REW + 0.4);
  const rising = ramp(tl, b.rise, b.rise + 0.8);

  // ---- lưới: bước 1-2-5 theo khung nhìn hiện tại
  const ys = niceStep(y1 - y0, H, 110), xs = niceStep(x1 - x0, W, 150);
  const yTicks: number[] = [], xTicks: number[] = [];
  for (let v = Math.ceil(y0 / ys) * ys; v <= y1; v += ys) if (v >= 0) yTicks.push(v);
  for (let v = Math.ceil(x0 / xs) * xs; v <= x1; v += xs) if (v >= s.minX && v <= s.maxX) xTicks.push(v);

  // ---- đường: chuỗi nhấn mạnh (VN) vẽ sau cùng để nằm trên
  const order = s.series.map((_, i) => i).sort((a, c) => Number(!!s.series[a].emphasis) - Number(!!s.series[c].emphasis));
  const pathOf = (se: Series) => {
    const pts: [number, number][] = [];
    se.xs.forEach((x, i) => { if (x <= drawnX) pts.push([x, se.ys[i]]); });
    const v = valueAt(se, drawnX);
    if (v !== null && (!pts.length || pts[pts.length - 1][0] < drawnX)) pts.push([drawnX, v]);
    return pts.map(([x, y], i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  };

  // ---- nhãn đầu đường: chuỗi ở trên đặt nhãn phía trên, chuỗi ở dưới đặt phía dưới
  const heads = s.series.map((se, i) => {
    const v = valueAt(se, drawnX), known = lastKnown(se, drawnX);
    return v === null || !known ? null : { i, se, v: known.y, x: X(drawnX), y: Y(v) };
  }).filter(Boolean) as { i: number; se: Series; v: number; x: number; y: number }[];
  const emph = s.series.find((se) => se.emphasis) ?? s.series[0];
  const sortedY = [...heads].sort((a, c) => a.y - c.y || Number(!!c.se.emphasis) - Number(!!a.se.emphasis));

  // ---- năm: tua ngược ở giữa màn hình rồi thu về góc phải làm "đồng hồ năm"
  const rewYear = Math.round(lerp(s.maxX, s.minX, ramp(tl, 0.05, REW - 0.1, Easing.inOut(Easing.cubic))));
  // đồng hồ năm nhảy theo NĂM CÓ SỐ LIỆU của chuỗi chính, khớp với số trên nhãn
  const year = tl < b.flat ? rewYear : (lastKnown(emph, drawnX)?.x ?? s.minX);
  const dock = ramp(tl, REW - 0.05, REW + 0.45, Easing.inOut(Easing.cubic));
  const yearStyle: React.CSSProperties = {
    position: "absolute", fontWeight: 800, color: brand.accent, lineHeight: 1,
    left: lerp(0, 590, dock), width: lerp(1080, 400, dock), textAlign: dock > 0.5 ? "right" : "center",
    top: lerp(720, 318, dock), fontSize: lerp(260, 92, dock),
    opacity: lerp(1, 0.9, dock), textShadow: `0 0 50px ${brand.accent}44`,
  };

  const start = ramp(tl, b.startLine, b.startLine + 0.6);
  const startFade = 1 - ramp(tl, b.rise, b.rise + 0.6);
  // nhãn "N năm gần như bằng 0" chỉ hiện khi đường đã đi gần hết đoạn đó (không nói trước)
  const gapAt = lerp(b.flat, b.rise, 0.55);
  const gap = ramp(tl, gapAt, gapAt + 0.4) * (1 - ramp(tl, b.rise + 0.6, b.rise + 1.2));
  const ref = s.reference ? ramp(tl, b.rise + 1.6, b.rise + 2.4) : 0;
  const call = pop(tl, b.callout, 0.45);
  const callHead = heads.find((h) => h.i === s.callout.series);

  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", top: 200, left: 80, right: 80, textAlign: "center", fontSize: 56,
        fontWeight: 800, color: brand.text, opacity: axes, lineHeight: 1.18 }}>{s.title}</div>
      <svg width={1080} height={1920} style={{ position: "absolute", opacity: axes }}>
        <defs>
          <clipPath id="box"><rect x={BOX.left - 4} y={BOX.top - 40} width={W + 30} height={H + 44} /></clipPath>
        </defs>
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={BOX.left} x2={BOX.right} y1={Y(v)} y2={Y(v)} stroke={brand.surface} strokeWidth={v === 0 ? 4 : 2} />
            <text x={BOX.left - 18} y={Y(v) + 11} fill={brand.muted} fontSize={30} fontWeight={600} textAnchor="end">{fmtVi(v)}</text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text key={`x${v}`} x={X(v)} y={BOX.bottom + 52} fill={brand.muted} fontSize={30} fontWeight={600} textAnchor="middle">{v}</text>
        ))}
        {s.reference && ref > 0 && (
          <g opacity={ref}>
            <line x1={BOX.left} x2={BOX.right} y1={Y(s.reference.y)} y2={Y(s.reference.y)} stroke={brand.text}
              strokeOpacity={0.5} strokeWidth={3} strokeDasharray="14 12" />
            <text x={BOX.left + 10} y={Y(s.reference.y) - 16} fill={brand.text} fillOpacity={0.75} fontSize={30} fontWeight={600}>
              {s.reference.label}</text>
          </g>
        )}
        {start > 0 && startFade > 0 && (
          <g opacity={startFade}>
            <line x1={X(s.minX)} x2={X(s.minX)} y1={Y(0)} y2={Y(0) - (Y(0) - BOX.top + 10) * start}
              stroke={brand.accent} strokeWidth={4} strokeDasharray="16 12" />
          </g>
        )}
        {gap > 0 && (() => {
          const xa = X(s.minX), xb = X(Math.min(drawnX, s.flatUntil)), yb = Y(0) - 150;
          return (
            <g opacity={gap}>
              <path d={`M${xa},${yb + 18} L${xa},${yb} L${xb},${yb} L${xb},${yb + 18}`} fill="none" stroke={brand.text} strokeWidth={3} />
            </g>
          );
        })()}
        <g clipPath="url(#box)">
          {tl > REW && order.map((i) => {
            const se = s.series[i];
            const em = !!se.emphasis;
            const w = em ? 8 : lerp(15, 6, rising);
            const op = em ? 1 : lerp(0.95, 0.5, rising);
            const d = pathOf(se);
            return (
              <g key={i}>
                <path d={d} fill="none" stroke={se.color} strokeOpacity={0.18 * op} strokeWidth={w + 14} strokeLinejoin="round" strokeLinecap="round" />
                <path d={d} fill="none" stroke={se.color} strokeOpacity={op} strokeWidth={w} strokeLinejoin="round" strokeLinecap="round" />
              </g>
            );
          })}
          {tl > REW && heads.map((h) => (
            <g key={`h${h.i}`} opacity={h.se.emphasis ? 1 : lerp(1, 0.6, rising)}>
              <circle cx={h.x} cy={h.y} r={22 + 10 * Math.sin(tl * 6)} fill={h.se.color} fillOpacity={0.2} />
              <circle cx={h.x} cy={h.y} r={13} fill={h.se.color} stroke={brand.background} strokeWidth={4} />
            </g>
          ))}
        </g>
        {call > 0 && callHead && [0, 1].map((j) => {
          const r = 20 + ((tl * 70 + j * 35) % 70);
          return <circle key={`c${j}`} cx={callHead.x} cy={callHead.y} r={r} fill="none" stroke={brand.accent}
            strokeWidth={4} strokeOpacity={Math.min(call, 1) * (1 - (r - 20) / 70)} />;
        })}
      </svg>

      {/* nhãn đầu đường: cờ + tên + giá trị hiện tại */}
      {tl > REW + 0.1 && sortedY.map((h, k) => {
        const above = k === 0;
        const leftSide = h.x > BOX.right - 330;
        return (
          <div key={`l${h.i}`} style={{
            position: "absolute", top: above ? h.y - 92 : h.y + 26,
            left: leftSide ? undefined : h.x + 4, right: leftSide ? 1080 - h.x + 4 : undefined,
            display: "flex", alignItems: "center", gap: 12, fontSize: 38, fontWeight: 800, color: h.se.color,
            // khi chú thích lớn hiện ra thì nhãn nhỏ của chính chuỗi đó lui đi (khỏi nói một số hai lần)
            opacity: (h.se.emphasis ? 1 : lerp(1, 0.65, rising)) * ramp(tl, REW + 0.1, REW + 0.5)
              * (h.i === s.callout.series ? 1 - ramp(tl, b.callout, b.callout + 0.25) : 1),
            textShadow: "0 2px 12px rgba(0,0,0,0.8)",
          }}>
            {h.se.flag && <Img src={staticFile(`flags/${h.se.flag}.svg`)} style={{ width: 50, height: 37, borderRadius: 5 }} />}
            <span>{h.se.label}</span>
            <span style={{ color: brand.text }}>{fmtVi(h.v)}</span>
          </div>
        );
      })}

      {/* vạch xuất phát + "không có điện thoại" */}
      {start > 0 && startFade > 0 && (
        <>
          <div style={{ position: "absolute", top: BOX.top + 6, left: X(s.minX) + 16, fontSize: 34, fontWeight: 800,
            letterSpacing: "0.08em", color: brand.accent, opacity: start * startFade }}>{s.startLabel}</div>
          <div style={{ position: "absolute", left: X(s.minX) + 70, top: Y(0) - 420, display: "flex", alignItems: "center",
            gap: 20, opacity: startFade, transform: `scale(${pop(tl, b.startLine + 0.5, 0.4)})`, transformOrigin: "left center" }}>
            <PhoneOff size={96} color={brand.muted} strokeWidth={2} />
            <span style={{ fontSize: 46, fontWeight: 800, color: brand.text }}>{s.zeroLabel}</span>
          </div>
        </>
      )}
      {gap > 0 && (
        <div style={{ position: "absolute", left: X(s.minX), width: X(Math.min(drawnX, s.flatUntil)) - X(s.minX),
          top: Y(0) - 208, textAlign: "center", fontSize: 38, fontWeight: 800, color: brand.text, opacity: gap,
          whiteSpace: "nowrap" }}>{s.gapLabel}</div>
      )}

      {/* chú thích con số chốt */}
      {/* đặt ở góc trên-trái, phía trên đường tham chiếu: vùng này luôn trống vì đường còn nằm sát 0 */}
      {call > 0 && callHead && (
        <div style={{ position: "absolute", left: BOX.left + 30,
          top: (s.reference ? Y(s.reference.y) : Y(s.yMax * 0.5)) - 330,
          transform: `scale(${call})`, transformOrigin: "left bottom" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 36, fontWeight: 800, color: callHead.se.color }}>
            {callHead.se.flag && <Img src={staticFile(`flags/${callHead.se.flag}.svg`)} style={{ width: 46, height: 34, borderRadius: 5 }} />}
            {callHead.se.label}
          </div>
          <div style={{ fontSize: 150, fontWeight: 800, color: brand.accent, lineHeight: 1.05, textShadow: `0 0 50px ${brand.accent}55` }}>
            {s.callout.value}</div>
          <div style={{ fontSize: 36, fontWeight: 700, color: brand.text }}>{s.callout.label}</div>
        </div>
      )}

      <div style={yearStyle}>{year}</div>
    </AbsoluteFill>
  );
};
