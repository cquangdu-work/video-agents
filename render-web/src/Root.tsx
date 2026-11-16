import React from "react";
import { Composition } from "remotion";
import { Story } from "./Story";
import { Wide, WideProps } from "./Wide";
import { StoryProps } from "./types";

// Props thật do Python truyền vào bằng --props=<file.json>; bản mặc định chỉ để mở Studio.
const empty: StoryProps = {
  brand: {
    background: "#0D1321", surface: "#1D2D44", text: "#F0EBD8", muted: "#748CAB", accent: "#FFB703",
    vietnam: "#E63946", korea: "#457B9D", good: "#2A9D8F", bad: "#E76F51", channel: "THẾ GIỚI QUA CON SỐ",
  },
  duration: 1.2,
  scenes: [{ kind: "intro", start: 0, end: 1.2 }],
  words: [], source: "", sfx: [],
};
const wideEmpty: WideProps = { story: empty, chapter: 1, chapters: ["Chương mẫu"], series: "TUẦN QUA CON SỐ" };

export const RemotionRoot: React.FC = () => (
  <>
    {/* Shorts dọc 9:16 — một video mỗi ngày */}
    <Composition
      id="Story"
      component={Story}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={36}
      defaultProps={empty}
      calculateMetadata={({ props }) => ({ durationInFrames: Math.max(1, Math.round(props.duration * 30)) })}
    />
    {/* Video dài 16:9 — mỗi lần render là một chương (src/longform.py) */}
    <Composition
      id="Wide"
      component={Wide}
      width={1920}
      height={1080}
      fps={30}
      durationInFrames={36}
      defaultProps={wideEmpty}
      calculateMetadata={({ props }) => ({ durationInFrames: Math.max(1, Math.round(props.story.duration * 30)) })}
    />
  </>
);
