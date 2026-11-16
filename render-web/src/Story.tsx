import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/BeVietnamPro";
import { Background } from "./components/Background";
import { Captions } from "./components/Captions";
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
  switch (scene.kind) {
    case "intro": return <Intro brand={brand} tl={tl} dur={dur} />;
    case "isotype": return <Isotype s={scene} brand={brand} tl={tl} dur={dur} />;
    case "network": return <Network s={scene} brand={brand} tl={tl} dur={dur} />;
    case "orbit": return <Orbit s={scene} brand={brand} tl={tl} dur={dur} />;
    case "heroline": return <HeroLine s={scene} brand={brand} tl={tl} dur={dur} />;
  }
};

export const Story: React.FC<StoryProps> = ({ brand, scenes, words, source, sfx }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  return (
    <AbsoluteFill style={{ fontFamily, color: brand.text }}>
      <Background brand={brand} t={t} frame={frame} />
      {scenes.map((sc, i) => (
        <Sequence key={i} from={Math.round(sc.start * fps)} durationInFrames={Math.max(1, Math.round((sc.end - sc.start) * fps))}>
          <SceneView scene={sc} brand={brand} />
        </Sequence>
      ))}
      <Captions words={words} t={t} brand={brand} />
      {source && (
        <div style={{ position: "absolute", bottom: 46, left: 0, right: 0, textAlign: "center", fontSize: 24,
          fontWeight: 500, color: brand.muted }}>Nguồn: {source}</div>
      )}
      {sfx.map((s, i) => (
        <Sequence key={`a${i}`} from={Math.round(s.at * fps)} durationInFrames={2 * fps}>
          <Audio src={staticFile(`sfx/${s.name}.wav`)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
