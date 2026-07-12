import React from "react";
import { Composition } from "remotion";
import { LongForm } from "./LongForm";
import { Overlay } from "./Overlay";
import { DynamicGallery } from "./components/DynamicGallery";
import { loadMapping } from "./loadProject";
import type { LongFormProps, OverlayProps, DynamicGalleryProps, Mapping } from "./types";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Engine DINÂMICO (LONGFORM_RENDER_ENGINE=dynamic — PADRÃO na v2): galeria viva com ordem,
          movimento e transição ALEATÓRIOS, sem dip-to-black e sem "tremido". Renderiza só o vídeo
          MUDO (o FFmpeg muxa a narração tratada + queima a legenda depois, em s8_montagem.py). */}
      <Composition
        id="DynamicGallery"
        component={DynamicGallery}
        width={1920}
        height={1080}
        fps={30}
        durationInFrames={300}
        defaultProps={{ slug: "demo" } as DynamicGalleryProps}
        calculateMetadata={async ({ props }) => {
          let mapping: Mapping | null = null;
          try {
            mapping = await loadMapping(props.slug);
          } catch (e) {
            return { durationInFrames: 300, fps: 30, props: { ...props, mapping: null } };
          }
          return {
            durationInFrames: Math.max(1, mapping.durationInFrames),
            fps: mapping.fps,
            width: mapping.width,
            height: mapping.height,
            props: { ...props, mapping },
          };
        }}
      />
      {/* Engine LEGADO (LONGFORM_RENDER_ENGINE=remotion): Remotion desenha TUDO no Chromium
          (Ken Burns + áudio + legendas). Mais lento; mantido como fallback. */}
      <Composition
        id="LongForm"
        component={LongForm}
        width={1920}
        height={1080}
        fps={60}
        durationInFrames={300}
        defaultProps={{ slug: "demo", showCaptions: false } as LongFormProps}
        calculateMetadata={async ({ props }) => {
          // Carrega o mapping do slug e dimensiona a composição por ele.
          let mapping: Mapping | null = null;
          try {
            mapping = await loadMapping(props.slug);
          } catch (e) {
            // sem assets (ex.: abrir o Studio sem projeto) — placeholder de 5 s
            return { durationInFrames: 300, fps: 60, props: { ...props, mapping: null } };
          }
          return {
            durationInFrames: Math.max(1, mapping.durationInFrames),
            fps: mapping.fps,
            width: mapping.width,
            height: mapping.height,
            props: { ...props, mapping },
          };
        }}
      />

      {/* Engine HÍBRIDO (LONGFORM_RENDER_ENGINE=hybrid + legendas ON): o Ken Burns + áudio
          vêm prontos do FFmpeg (base.mp4); aqui o Remotion só compõe overlays por cima. */}
      <Composition
        id="LongFormOverlay"
        component={Overlay}
        width={1920}
        height={1080}
        fps={60}
        durationInFrames={300}
        defaultProps={{ slug: "demo", baseVideo: "base.mp4", showCaptions: true } as OverlayProps}
        calculateMetadata={async ({ props }) => {
          let mapping: Mapping | null = null;
          try {
            mapping = await loadMapping(props.slug);
          } catch (e) {
            return { durationInFrames: 300, fps: 60, props: { ...props, mapping: null } };
          }
          return {
            durationInFrames: Math.max(1, mapping.durationInFrames),
            fps: mapping.fps,
            width: mapping.width,
            height: mapping.height,
            props: { ...props, mapping },
          };
        }}
      />
    </>
  );
};
