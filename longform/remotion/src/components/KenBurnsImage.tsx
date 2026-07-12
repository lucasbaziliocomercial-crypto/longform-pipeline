import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { Segment } from "../types";

const FADE = 12; // frames de crossfade na entrada/saída de cada take

/**
 * Imagem com efeito Ken Burns (zoom in/out + pan) e crossfade nas bordas.
 * `slug` resolve o asset em public/<slug>/<segment.image>.
 */
export const KenBurnsImage: React.FC<{ slug: string; segment: Segment }> = ({ slug, segment }) => {
  const frame = useCurrentFrame();
  const dur = segment.durationInFrames;

  const zoomIn = segment.effect !== "zoomOut";
  const scale = interpolate(frame, [0, dur], zoomIn ? [1.0, 1.1] : [1.1, 1.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // pan suave (em % do frame) na direção indicada
  const [px, py] = segment.pan;
  const amp = 3; // % de deslocamento máximo
  const tx = interpolate(frame, [0, dur], [0, px * amp], { extrapolateRight: "clamp" });
  const ty = interpolate(frame, [0, dur], [0, py * amp], { extrapolateRight: "clamp" });

  const opacity = interpolate(
    frame,
    [0, FADE, dur - FADE, dur],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={{ opacity, backgroundColor: "black" }}>
      <Img
        src={staticFile(`${slug}/${segment.image}`)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translate(${tx}%, ${ty}%)`,
        }}
      />
    </AbsoluteFill>
  );
};
