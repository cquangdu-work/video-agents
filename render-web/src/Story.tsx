import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
import { ChartWorld } from "./components/ChartWorld";
import { BarChart, BigNumber, Clip, LineChartTitle, PercentRing, Statement, Versus } from "./scenes/Generic";
import { HeroLine } from "./scenes/HeroLine";
import { Intro } from "./scenes/Intro";
import { Isotype } from "./scenes/Isotype";
import { Network } from "./scenes/Network";
import { Orbit } from "./scenes/Orbit";
import { Scene, StoryProps } from "./types";

// Font của bộ nhận diện (Be Vietnam Pro, giấy phép OFL) — tải lúc render, đủ dấu tiếng Việt.
const { fontFamily } = loadFont("normal", { weights: ["500", "600", "700", "800"], subsets: ["vietnamese", "latin"] });

const SceneView: React.FC<{ scene: Scene; brand: StoryProps["brand"] }> = ({ scene, brand }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tl = frame / fps, dur = scene.end - scene.start;
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
    // cảnh riêng của bản demo #30
    case "isotype": return <Isotype s={scene} {...common} />;
    case "network": return <Network s={scene} {...common} />;
    case "orbit": return <Orbit s={scene} {...common} />;
    case "heroline": return <HeroLine s={scene} {...common} />;
  }
};

export const Story: React.FC<StoryProps> = ({ brand, scenes, words, source, sfx, world }) => {
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
          <SceneView scene={sc} brand={brand} />
        </Sequence>
      ))}
      <Captions words={words} t={t} brand={brand} />
      {src && current?.kind !== "clip" && (
        <div style={{ position: "absolute", bottom: 46, left: 40, right: 40, textAlign: "center", fontSize: 24,
          fontWeight: 500, color: brand.muted }}>Nguồn: {src}</div>
      )}
      {sfx.map((s, i) => (
        <Sequence key={`a${i}`} from={Math.round(s.at * fps)} durationInFrames={2 * fps}>
          <Audio src={staticFile(`sfx/${s.name}.wav`)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
