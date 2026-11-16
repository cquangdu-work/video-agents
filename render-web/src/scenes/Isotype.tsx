import React from "react";
import { AbsoluteFill, Easing, Img, staticFile } from "remotion";
import { PersonStanding, Smartphone } from "lucide-react";
import { Brand, IsotypeScene } from "../types";
import { fmtVi, pop, ramp } from "../lib/anim";

// "Cứ 100 người thì có N thứ": lưới 10x10 hình người, tới đúng lúc lời đọc nói con số thì
// mỗi người nhận một chiếc điện thoại, phần dư (N - 100) rơi xuống thành hàng riêng.
// Cuối cảnh camera lao vào một chiếc điện thoại -> nối sang cảnh mạng lưới.
const COLS = 10, CELL = 66, LEFT = (1080 - COLS * CELL) / 2, TOP = 400;
const ZOOM_CELL = 46; // ô camera lao vào (hàng 4, cột 6)

export const Isotype: React.FC<{ s: IsotypeScene; brand: Brand; tl: number; dur: number }> = ({ s, brand, tl, dur }) => {
  const at = s.itemsAt - s.start;
  const extra = Math.max(s.items - s.people, 0);
  const rows = Math.ceil(s.people / COLS);
  const counting = ramp(tl, at, at + 1.0, Easing.out(Easing.cubic));
  const showItems = tl >= at;
  const shown = showItems ? Math.round(counting * s.items) : s.people;
  const zoom = ramp(tl, dur - 0.45, dur, Easing.in(Easing.cubic));
  const zx = LEFT + (ZOOM_CELL % COLS) * CELL + CELL / 2, zy = TOP + Math.floor(ZOOM_CELL / COLS) * CELL + CELL / 2;
  const head = ramp(tl, 0, 0.35, Easing.out(Easing.cubic));

  const cells = [];
  for (let i = 0; i < s.people; i++) {
    const r = Math.floor(i / COLS), c = i % COLS;
    const p = pop(tl, 0.05 + (r + c) * 0.03, 0.3);
    const ph = pop(tl, at + i * 0.006, 0.25);
    cells.push(
      <div key={`p${i}`} style={{ position: "absolute", left: LEFT + c * CELL, top: TOP + r * CELL,
        width: CELL, height: CELL, transform: `scale(${p})`, opacity: Math.min(p, 1) }}>
        <PersonStanding size={46} color={showItems ? brand.text : brand.muted} strokeWidth={2.2}
          style={{ position: "absolute", left: 2, top: 8, opacity: showItems ? 0.5 : 1 }} />
        {ph > 0 && (
          <Smartphone size={28} color={brand.accent} strokeWidth={2.8}
            style={{ position: "absolute", left: 38, top: 28, transform: `scale(${ph})` }} />
        )}
      </div>,
    );
  }
  for (let j = 0; j < extra; j++) {
    const r = Math.floor(j / COLS), c = j % COLS;
    const d = ramp(tl, at + 0.55 + j * 0.022, at + 0.95 + j * 0.022, Easing.out(Easing.bounce));
    cells.push(
      <div key={`x${j}`} style={{ position: "absolute", left: LEFT + c * CELL + 12,
        top: TOP + (rows + r) * CELL + 18 - (1 - d) * 260, opacity: d > 0 ? 1 : 0 }}>
        <Smartphone size={42} color={brand.accent} strokeWidth={2.6} />
      </div>,
    );
  }

  return (
    <AbsoluteFill style={{ opacity: 1 - ramp(tl, dur - 0.12, dur), transformOrigin: `${zx}px ${zy}px`,
      transform: `scale(${1 + zoom * 7})` }}>
      <div style={{ position: "absolute", top: 205, left: 0, right: 0, display: "flex", justifyContent: "center",
        alignItems: "center", gap: 18, opacity: head, fontSize: 40, fontWeight: 700, color: brand.muted }}>
        {s.flag && <Img src={staticFile(`flags/${s.flag}.svg`)} style={{ width: 56, height: 42, borderRadius: 6 }} />}
        {s.caption}
      </div>
      <div style={{ position: "absolute", top: 262, left: 0, right: 0, textAlign: "center", opacity: head,
        fontWeight: 800, color: showItems ? brand.accent : brand.text, fontSize: 120, lineHeight: "130px",
        transform: `scale(${1 + 0.08 * (showItems ? 1 - counting : 0)})` }}>
        {fmtVi(shown)}
        <span style={{ fontSize: 52, marginLeft: 22, color: brand.text, fontWeight: 700 }}>
          {showItems ? s.itemsLabel : s.peopleLabel}
        </span>
      </div>
      {cells}
    </AbsoluteFill>
  );
};
