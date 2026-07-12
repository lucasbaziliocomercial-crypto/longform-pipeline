export type Segment = {
  index: number;
  image: string; // ex.: "images/img_001.png" (relativo a public/<slug>/)
  start: number;
  end: number;
  fromFrame: number;
  durationInFrames: number;
  text: string;
  effect: "zoomIn" | "zoomOut";
  pan: [number, number];
};

export type Mapping = {
  fps: number;
  width: number;
  height: number;
  audio: string; // ex.: "narration.mp3"
  durationInFrames: number;
  totalSeconds: number;
  segments: Segment[];
};

export type LongFormProps = {
  slug: string;
  showCaptions?: boolean;
  mapping?: Mapping | null;
};

// Composição DINÂMICA (v2): galeria viva com ordem/movimento/transição aleatórios (sem dip-to-black).
// Renderiza só o vídeo MUDO; o áudio (tratado) + legenda são muxados depois pelo FFmpeg.
export type DynamicGalleryProps = {
  slug: string;
  mapping?: Mapping | null;
};

// Composição de overlay (modo híbrido): o Ken Burns + áudio já vêm prontos no base.mp4
// (gerado pelo FFmpeg em ffmpeg_montagem.py); o Remotion só compõe legendas/títulos por cima.
export type OverlayProps = {
  slug: string;
  baseVideo: string; // ex.: "base.mp4" (relativo a public/<slug>/)
  showCaptions?: boolean;
  mapping?: Mapping | null;
};
