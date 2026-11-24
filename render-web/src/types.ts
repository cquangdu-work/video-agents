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

// source: dòng "Nguồn" riêng của cảnh. hook: cảnh MỞ ĐẦU (từ 19/11/2026 không còn thẻ intro) — chữ của
// nó hiện đủ ngay khung hình đầu tiên, không chờ hiệu ứng, vì người xem quyết định lướt đi trong 1-2 giây.
type Span = { start: number; end: number; source?: string; hook?: boolean };

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
  // khoảng cách năm cuối giữa đường được nhấn (a) và đường kia (b) — ngoặc đo khi vẽ xong (src/render/web.gap_of)
  gap?: { a: number; b: number; x: number; value: string; label: string };
};

/** Phát hiện đáng nhớ (src/render/web.finding_of): câu mở đầu đã kiểm + con số chính, thẻ lớn cuối video. */
export type Finding = { value: string; text: string; start: number; end: number; label: string };

// ---- cảnh chung (map 1-1 với template của spec)
export type IntroScene = Span & { kind: "intro" };
export type StatementScene = Span & {
  kind: "statement"; text: string; style: number; n?: number; icon?: string; highlights: string[];
  // Có biểu đồ chính đã vẽ: câu chữ hiện ở nửa trên, BIỂU ĐỒ GIỮ LẠI ở nửa dưới (trước 19/11 cảnh
  // chữ là nền trống — 1/3 thời lượng video, và là chỗ người xem bỏ đi nhiều nhất)
  chart?: ChartState; compact?: boolean;
};
export type BigNumberScene = Span & {
  kind: "big_number"; title: string; value: number; dec: number; suffix: string; color: string; flag?: string;
  isotype?: { mode: "share" | "per100"; count: number; icon?: string; noun: string };
  chart?: ChartState;
};
export type VersusScene = Span & {
  kind: "versus"; title: string; left: Valued; right: Valued; suffix: string; chart?: ChartState;
};
export type BarChartScene = Span & { kind: "bar_chart"; title: string; items: Valued[]; unit: string; style?: number };
export type PercentScene = Span & { kind: "percent"; title: string; value: number; dec: number; label: string };
export type LineChartScene = Span & { kind: "line_chart"; title: string; chart: ChartState };
export type ClipScene = Span & { kind: "clip"; src: string }; // cảnh Manim dựng sẵn (khi chưa có bản Remotion)
/** Biểu đồ đường mang số liệu KHÁC biểu đồ chính: một ChartWorld riêng chỉ sống trong cảnh này. */
export type LineSoloScene = Span & { kind: "line_solo"; title: string; world: World; chart: ChartState };

// Bản đồ: mọi toạ độ là ĐIỂM ẢNH khung 1080x1920, do src/render/web_map.py tính (phép chiếu,
// Hoàng Sa + Trường Sa, ô phóng to Biển Đông...). Remotion chỉ tô và cho chuyển động.
type Pt = [number, number];
export type MapLabel = { text: string; x: number; y: number; anchor: "start" | "middle"; size: number; color: string };
export type MapScene = Span & {
  kind: "map"; region: "asia" | "world"; title: string;
  outline: string;
  fills: { code: string; d: string; color: string; k: number; dot?: [number, number, number] }[];
  islands: Pt[]; islandColor: string; islandLabels: MapLabel[];
  marks: { d: string; color: string }[];
  legend?: { stops: string[]; lo: string; hi: string; caption: string; y: number };
  callouts?: { label: string; value: string; color: string; x: number; y: number; to: Pt }[];
  inset?: {
    frame: [Pt, Pt]; shapes: { d: string; fill?: string | null; stroke: string; vn: boolean }[];
    islands: Pt[]; labels: MapLabel[]; mark: [Pt, Pt]; background: string;
  };
  panel?: { label: string; value: string; color: string; pos: string }[];
};
export type BarRaceScene = Span & {
  kind: "bar_race"; title: string; years: number[]; unit: string;
  items: { label: string; values: number[]; shown: string[]; fill: string; ink: string; strong: boolean; flag?: string }[];
  overtakes?: { leg: number; item: number; passed: string[] }[]; // chặng nước "ta" vượt nước khác (web_map.overtakes)
};

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
  | LineChartScene | LineSoloScene | ClipScene | MapScene | BarRaceScene
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
  hideCaptions?: boolean; // video dài (Wide): phụ đề vẽ to ở cột phải thay vì trong khung dọc
  hideLogo?: boolean; // video dài (Wide) đã có nhận diện riêng ở cột phải
  captionSize?: number; // cỡ chữ phụ đề (px) của phong cách đang thử nghiệm (src/style.py); thiếu = 80
  finding?: Finding | null;
};
