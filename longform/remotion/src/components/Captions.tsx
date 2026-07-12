import React from "react";
import { AbsoluteFill } from "remotion";

/** Legenda opcional (texto do segmento) na faixa inferior. */
export const Captions: React.FC<{ text: string }> = ({ text }) => {
  if (!text) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", padding: "0 0 70px" }}>
      <div
        style={{
          maxWidth: "82%",
          textAlign: "center",
          fontFamily: "Inter, system-ui, sans-serif",
          fontWeight: 700,
          fontSize: 44,
          lineHeight: 1.25,
          color: "white",
          textShadow: "0 2px 12px rgba(0,0,0,0.85)",
          background: "rgba(0,0,0,0.28)",
          padding: "10px 26px",
          borderRadius: 14,
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
