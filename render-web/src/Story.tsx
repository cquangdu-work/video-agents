import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { loadFont as loadKR } from "@remotion/google-fonts/NotoSansKR";
import { LANG } from "./lib/locale";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
import { ChartWorld } from "./components/ChartWorld";
import { FindingCard } from "./components/FindingCard";
import { BarChart, BigNumber, Clip, HookContext, LineChartTitle, LineSolo, PercentRing, Statement, Versus } from "./scenes/Generic";
import { BarRace, MapView } from "./scenes/MapRace";
import { HeroLine } from "./scenes/HeroLine";
import { Intro } from "./scenes/Intro";
import { Isotype } from "./scenes/Isotype";
import { Network } from "./scenes/Network";
import { Orbit } from "./scenes/Orbit";
import { Scene, StoryProps } from "./types";

// Font của bộ nhận diện (Be Vietnam Pro, giấy phép OFL) — tải lúc render, đủ dấu tiếng Việt.
const vi = loadFont("normal", { weights: ["500", "600", "700", "800"], subsets: ["vietnamese", "latin"] });
// Kênh tiếng Hàn: Be Vietnam Pro không có chữ Hàn -> Noto Sans KR (OFL) đứng sau cho chữ Hàn, chữ số/Latin vẫn
// dùng Be Vietnam Pro để giữ nhận diện kênh. Chỉ nạp khi video là tiếng Hàn (bộ chữ Hàn nặng).
const kr = LANG === "ko" ? loadKR("normal", { weights: ["500", "700", "800"], subsets: ["korean", "latin"] }) : null;
const fontFamily = kr ? `${vi.fontFamily}, ${kr.fontFamily}` : vi.fontFamily;

// Cảnh MỞ ĐẦU chạy hiệu ứng "đi trước" chừng này giây: khung hình đầu tiên đã có hình (cột, số) thay vì
// đang mọc từ 0 — người xem quyết định lướt đi trong 1-2 giây đầu (bản thử 19/11: khung 0 chỉ có tiêu đề).
// Cộng cả vào dur để hiệu ứng thoát cuối cảnh vẫn đúng lúc.
const HOOK_HEAD = 0.6;

const SceneView: React.FC<{ scene: Scene; brand: StoryProps["brand"] }> = ({ scene, brand }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const head = scene.hook ? HOOK_HEAD : 0;
  const tl = frame / fps + head, dur = scene.end - scene.start + head;
  const common = { brand, tl, dur };
  switch (scene.kind) {
    case "intro": return <Intro {...common} />;
    case "statement": return <Statement s={scene} {...common} />;
    case "big_number": return <BigNumber s={scene} {...common} />;
    case "versus": return <Versus s={scene} {...common} />;
    case "bar_chart": return <BarChart s={scene} {...common} />;
    case "percent": return <PercentRing s={scene} {...common} />;
    case "line_chart": return <LineChartTitle s={scene} {...common} />;
    case "clip": return <Clip s={scene} {...common} />;
    case "line_solo": return <LineSolo s={scene} {...common} />;
    case "map": return <MapView s={scene} {...common} />;
    case "bar_race": return <BarRace s={scene} {...common} />;
    // cảnh riêng của bản demo #30
    case "isotype": return <Isotype s={scene} {...common} />;
    case "network": return <Network s={scene} {...common} />;
    case "orbit": return <Orbit s={scene} {...common} />;
    case "heroline": return <HeroLine s={scene} {...common} />;
  }
};

// Dấu nhận diện nhỏ ở góc trên trái, suốt video — thay cho thẻ intro 1,2 giây (bỏ từ 19/11/2026: giây
// đầu tiên là câu mở đầu). Cùng ý bộ nhận diện cũ: số "1" màu nhấn + tên kênh.
const CornerLogo: React.FC<{ brand: StoryProps["brand"] }> = ({ brand }) => (
  <div style={{ position: "absolute", top: 70, left: 56, display: "flex", alignItems: "center", gap: 14,
    opacity: 0.88 }}>
    <div style={{ width: 52, height: 52, borderRadius: 14, background: brand.accent, color: brand.background,
      fontSize: 38, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>1</div>
    <div style={{ fontSize: 25, fontWeight: 800, letterSpacing: "0.08em", color: brand.text }}>{brand.channel}</div>
  </div>
);

export const Story: React.FC<StoryProps> = ({ brand, scenes, words, source, sfx, world, hideCaptions, hideLogo,
  captionSize, finding }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  // dòng "Nguồn" theo cảnh đang chiếu (spec ghi nguồn từng cảnh), không có thì dùng nguồn chung
  const current = [...scenes].reverse().find((sc) => sc.start <= t + 1e-6);
  const src = current?.source || source;
  return (
    <AbsoluteFill style={{ fontFamily, color: brand.text }}>
      <Background brand={brand} t={t} frame={frame} />
      {world && <ChartWorld world={world} scenes={scenes} t={t} brand={brand} />}
      {scenes.map((sc, i) => (
        <Sequence key={i} from={Math.round(sc.start * fps)} durationInFrames={Math.max(1, Math.round((sc.end - sc.start) * fps))}>
          <HookContext.Provider value={!!sc.hook}>
            <SceneView scene={sc} brand={brand} />
          </HookContext.Provider>
        </Sequence>
      ))}
      {finding && <FindingCard f={finding} brand={brand} t={t} />}
      {!hideLogo && !scenes.some((sc) => sc.kind === "intro") && <CornerLogo brand={brand} />}
      {!hideCaptions && <Captions words={words} t={t} brand={brand} size={captionSize} />}
      {src && current?.kind !== "clip" && (
        <div style={{ position: "absolute", bottom: 46, left: 40, right: 40, textAlign: "center", fontSize: 24,
          fontWeight: 500, color: brand.muted }}>{LANG === "ko" ? "출처" : "Nguồn"}: {src}</div>
      )}
      {sfx.map((s, i) => (
        <Sequence key={`a${i}`} from={Math.round(s.at * fps)} durationInFrames={2 * fps}>
          <Audio src={staticFile(`sfx/${s.name}.wav`)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
