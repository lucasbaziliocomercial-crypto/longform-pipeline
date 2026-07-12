import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { Captions } from "./components/Captions";
import type { OverlayProps } from "./types";

/**
 * Composição de overlay do modo HÍBRIDO.
 *
 * O vídeo-base (Ken Burns + crossfade-através-do-preto + áudio da narração) já foi
 * renderizado pelo FFmpeg em ffmpeg_montagem.py -> public/<slug>/<baseVideo>. Aqui o
 * Remotion só desenha o que agrega valor visual de verdade (legendas/títulos) POR CIMA,
 * via OffthreadVideo. Sem overlays, nem chamamos esta composição — o base.mp4 já é o final.
 */
export const Overlay: React.FC<OverlayProps> = ({ slug, baseVideo, mapping, showCaptions }) => {
  if (!mapping) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#111", color: "#bbb", justifyContent: "center", alignItems: "center", fontFamily: "system-ui", fontSize: 40 }}>
        Sem mapping para "{slug}". Faça o staging (Etapa 8) e renderize com --props.
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* base.mp4 carrega vídeo E áudio — não somar <Audio> aqui (duplicaria a trilha). */}
      <OffthreadVideo src={staticFile(`${slug}/${baseVideo}`)} />
      {showCaptions
        ? mapping.segments.map((seg) => (
            <Sequence key={seg.index} from={seg.fromFrame} durationInFrames={seg.durationInFrames}>
              <Captions text={seg.text} />
            </Sequence>
          ))
        : null}
    </AbsoluteFill>
  );
};
