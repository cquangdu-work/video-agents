import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { Story } from "./Story";
import { StoryProps, Word } from "./types";
import { clamp01, ramp } from "./lib/anim";

// VIDEO DÀI 16:9 (src/longform.py): mỗi lần render là MỘT CHƯƠNG = một video Shorts trong tuần.
// Bố cục "phòng thu": trái là câu chuyện dọc (chính Story, thu nhỏ, giữ nguyên mọi cảnh),
// phải là số chương, tiêu đề, phụ đề lớn theo từ đang đọc và danh sách các chương.
// Tiếng do Python ghép từ bản phát hành của Shorts (đã có giọng + nhạc + hiệu ứng).

const { fontFamily } = loadFont("normal", { weights: ["500", "600", "700", "800"], subsets: ["vietnamese", "latin"] });

export type WideProps = {
  story: StoryProps;
  chapter: number; // 1-based
  chapters: string[]; // tiêu đề các chương
  series: string; // "TUẦN QUA CON SỐ · 10–16/11"
};

const SCALE = 1080 / 1920; // khung dọc 1080x1920 thu vào cao 1080
const LEFT_W = 1080 * SCALE; // ~608

function currentChunk(words: Word[], t: number): { words: Word[]; active: number } | null {
  let chunk: Word[] = [];
  for (const w of words) if (w.s <= t + 0.05) chunk = words.filter((x) => x.c === w.c);
  if (!chunk.length) return null;
  const last = chunk[chunk.length - 1];
  const next = words.find((x) => x.c === last.c + 1);
  if (t > last.e + Math.min(0.6, next ? next.s - last.e : 0.6)) return null;
  let active = -1;
  chunk.forEach((w, i) => { if (t >= w.s) active = i; });
  return { words: chunk, active };
}

export const Wide: React.FC<WideProps> = ({ story, chapter, chapters, series }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const b = story.brand;
  const enter = ramp(t, 0, 0.6);
  const cap = currentChunk(story.words, t);
  const title = chapters[chapter - 1] ?? "";
  return (
    <AbsoluteFill style={{ fontFamily, color: b.text,
      background: `radial-gradient(ellipse 1400px 900px at 70% 40%, #17233b 0%, ${b.background} 70%)` }}>
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${b.muted} 2px, transparent 2.6px)`,
        backgroundSize: "60px 60px", opacity: 0.12 }} />
      {/* khung dọc: chính video Shorts, thu nhỏ */}
      <div style={{ position: "absolute", left: 90, top: 0, width: LEFT_W, height: 1080, overflow: "hidden",
        borderRadius: 0, boxShadow: "0 0 80px rgba(0,0,0,0.6)", borderLeft: `2px solid ${b.surface}`,
        borderRight: `2px solid ${b.surface}` }}>
        <div style={{ width: 1080, height: 1920, transform: `scale(${SCALE})`, transformOrigin: "top left" }}>
          <Story {...story} sfx={[]} hideCaptions hideLogo />
        </div>
      </div>

      {/* cột phải */}
      <div style={{ position: "absolute", left: 790, right: 90, top: 80, opacity: enter,
        transform: `translateY(${(1 - enter) * 20}px)` }}>
        <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "0.18em", color: b.accent }}>{series}</div>
        <div style={{ marginTop: 14, fontSize: 30, fontWeight: 700, color: b.muted }}>
          Chương {chapter}/{chapters.length}
        </div>
        <div style={{ marginTop: 10, fontSize: 52, fontWeight: 800, lineHeight: 1.18, maxHeight: 190, overflow: "hidden" }}>
          {title}
        </div>
      </div>

      <div style={{ position: "absolute", left: 790, right: 90, top: 430, minHeight: 200, fontSize: 64, fontWeight: 800,
        lineHeight: 1.2 }}>
        {cap && cap.words.map((w, i) => (
          <span key={i} style={{ display: "inline-block", marginRight: 18,
            color: i === cap.active ? b.accent : b.text, opacity: i <= cap.active ? 1 : 0.55,
            transform: `scale(${i === cap.active ? 1 + 0.06 * (1 - clamp01((t - w.s) / 0.2)) : 1})` }}>{w.w}</span>
        ))}
      </div>

      <div style={{ position: "absolute", left: 790, right: 90, bottom: 70 }}>
        {chapters.map((c, i) => {
          const cur = i + 1 === chapter, done = i + 1 < chapter;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 10, fontSize: 24,
              fontWeight: cur ? 800 : 600, color: cur ? b.text : b.muted, opacity: done ? 0.55 : 1 }}>
              <div style={{ width: 34, height: 34, borderRadius: 17, display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: 18, fontWeight: 800,
                background: cur ? b.accent : b.surface, color: cur ? b.background : b.muted }}>{i + 1}</div>
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c}</span>
            </div>
          );
        })}
        <div style={{ marginTop: 18, height: 6, borderRadius: 3, background: b.surface }}>
          <div style={{ height: 6, borderRadius: 3, background: b.accent,
            width: `${100 * clamp01(t / Math.max(story.duration, 0.1))}%` }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
