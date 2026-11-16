// Hợp đồng dữ liệu giữa Python và Remotion: Python (src/render/web.py) ghi một file JSON
// đúng khuôn này, Remotion chỉ việc vẽ. Mọi thời điểm là GIÂY TUYỆT ĐỐI tính từ đầu video,
// mọi con số đến từ bảng dữ liệu gốc do code điền — phía Remotion không tự bịa số nào.

export type Word = { w: string; s: number; e: number; c: number }; // c = số thứ tự cụm phụ đề

export type Brand = {
  background: string; surface: string; text: string; muted: string; accent: string;
  vietnam: string; korea: string; good: string; bad: string;
  channel: string;
};

export type Series = {
  label: string; color: string; flag?: string; xs: number[]; ys: number[]; emphasis?: boolean;
};

type Span = { start: number; end: number };

export type IntroScene = Span & { kind: "intro" };

export type IsotypeScene = Span & {
  kind: "isotype";
  flag?: string; caption: string; // dòng nhỏ phía trên: cờ + "Việt Nam · 2024"
  people: number; peopleLabel: string; // 100 "người"
  items: number; itemsLabel: string; // 128 "thuê bao"
  itemsAt: number; // lúc lời đọc nói tới con số -> điện thoại bật ra
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
  flatUntil: number; // năm cuối của đoạn "gần như bằng 0"
  beats: { startLine: number; flat: number; rise: number; callout: number };
  startLabel: string; zeroLabel: string; gapLabel: string;
  reference?: { y: number; label: string };
  callout: { series: number; value: string; label: string };
};

export type Scene = IntroScene | IsotypeScene | NetworkScene | OrbitScene | HeroLineScene;

export type Sfx = { name: string; at: number; volume: number };

export type StoryProps = {
  brand: Brand;
  duration: number;
  scenes: Scene[];
  words: Word[];
  source: string;
  sfx: Sfx[];
};
