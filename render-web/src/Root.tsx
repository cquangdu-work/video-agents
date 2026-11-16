import React from "react";
import { Composition } from "remotion";
import { Story } from "./Story";
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

export const RemotionRoot: React.FC = () => (
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
);
