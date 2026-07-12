import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { KenBurnsImage } from "./components/KenBurnsImage";
import { Captions } from "./components/Captions";
import type { LongFormProps } from "./types";

/**
 * Composição long-form 16:9: áudio da narração + sequência de imagens com Ken Burns
 * (zoom in/out + pan) e crossfade entre takes, sincronizada pelo mapping.json.
 */
export const LongForm: React.FC<LongFormProps> = ({ slug, mapping, showCaptions }) => {
  if (!mapping) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#111", color: "#bbb", justifyContent: "center", alignItems: "center", fontFamily: "system-ui", fontSize: 40 }}>
        Sem mapping para "{slug}". Faça o staging (Etapa 8) e renderize com --props.
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Audio src={staticFile(`${slug}/${mapping.audio}`)} />
      {mapping.segments.map((seg) => (
        <Sequence key={seg.index} from={seg.fromFrame} durationInFrames={seg.durationInFrames}>
          <KenBurnsImage slug={slug} segment={seg} />
          {showCaptions ? <Captions text={seg.text} /> : null}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
