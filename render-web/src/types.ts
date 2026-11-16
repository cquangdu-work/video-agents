// Hợp đồng dữ liệu giữa Python và Remotion: Python (src/render/web.py) ghi một file JSON
// đúng khuôn này, Remotion chỉ việc vẽ. Mọi thời điểm là GIÂY TUYỆT ĐỐI tính từ đầu video,
// mọi con số đến từ spec (đã đối chiếu nguồn) hoặc bảng dữ liệu gốc — Remotion không bịa số.

export type Word = { w: string; s: number; e: number; c: number }; // c = số thứ tự cụm phụ đề

export type Brand = {
  background: string; surface: string; text: string; muted: string; accent: string;
  vietnam: string; korea: string; good: string; bad: string;
  channel: string;
};

export type Series = {
  label: string; color: string; flag?: string; xs: number[]; ys: number[]; emphasis?: boolean;
  dec?: number; // số chữ số thập phân tối đa khi hiện nhãn (theo spec)
};

/** Một con số có nhãn: dec = số chữ số lẻ Python đã chọn (label_decimals) -> hiện y hệt bản Manim. */
export type Valued = { label: string; value: number; dec: number; color: string; flag?: string };

type Span = { start: number; end: number; source?: string }; // source: dòng "Nguồn" riêng của cảnh

/** Trạng thái của BIỂU ĐỒ CHÍNH trong một cảnh (xem components/ChartWorld.tsx). */
export type ChartState = {
  mode: "full" | "panel";
  drawTo: number; // năm cuối cần vẽ tới ở cảnh này
  focus?: { s: number; x: number }[]; // điểm số liệu thật cảnh này nói tới
  callout?: { s: number; value: string; label: string; at: number };
};

export type World = {
  series: Series[]; minX: number; maxX: number; yMax: number; unit: string;
  reference?: { y: number; label: string };
};

// ---- cảnh chung (map 1-1 với template của spec)
export type IntroScene = Span & { kind: "intro" };
export type StatementScene = Span & {
  kind: "statement"; text: string; style: number; n?: number; icon?: string; highlights: string[];
};
export type BigNumberScene = Span & {
  kind: "big_number"; title: string; value: number; dec: number; suffix: string; color: string; flag?: string;
  isotype?: { mode: "share" | "per100"; count: number; icon?: string; noun: string };
  chart?: ChartState;
};
export type VersusScene = Span & {
  kind: "versus"; title: string; left: Valued; right: Valued; suffix: string; chart?: ChartState;
};
export type BarChartScene = Span & { kind: "bar_chart"; title: string; items: Valued[]; unit: string };
export type PercentScene = Span & { kind: "percent"; title: string; value: number; dec: number; label: string };
export type LineChartScene = Span & { kind: "line_chart"; title: string; chart: ChartState };
export type ClipScene = Span & { kind: "clip"; src: string }; // cảnh Manim dựng sẵn (bản đồ, cuộc đua...)

// ---- cảnh riêng của bản demo #30 (tools/demo_web30.py)
export type IsotypeScene = Span & {
  kind: "isotype";
  flag?: string; caption: string;
  people: number; peopleLabel: string;
  items: number; itemsLabel: string;
  itemsAt: number;
};
export type NetworkScene = Span & { kind: "network"; title: string };
export type OrbitScene = Span & {
  kind: "orbit"; title: string;
  items: { icon: string; label: string; at: number }[];
};
export type HeroLineScene = Span & {
  kind: "heroline";
  title: string;
  series: Series[];
  minX: number; maxX: number; yMax: number;
  flatUntil: number;
  beats: { startLine: number; flat: number; rise: number; callout: number };
  startLabel: string; zeroLabel: string; gapLabel: string;
  reference?: { y: number; label: string };
  callout: { series: number; value: string; label: string };
};

export type Scene =
  | IntroScene | StatementScene | BigNumberScene | VersusScene | BarChartScene | PercentScene
  | LineChartScene | ClipScene
  | IsotypeScene | NetworkScene | OrbitScene | HeroLineScene;

export type Sfx = { name: string; at: number; volume: number };

export type StoryProps = {
  brand: Brand;
  duration: number;
  scenes: Scene[];
  words: Word[];
  source: string;
  sfx: Sfx[];
  world?: World | null;
};
