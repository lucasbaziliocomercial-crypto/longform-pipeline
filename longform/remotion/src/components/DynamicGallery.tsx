import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import type { TransitionPresentation } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import type { Mapping } from "../types";

/**
 * DynamicGallery — motor de montagem (v3: movimento ÚNICO calmo, "Ken Burns fixo").
 *
 * A galeria continua VIVA (imagem cheia 1920x1080, ordem sem repetir a anterior, cobre a duração
 * do áudio), mas o MOVIMENTO foi PADRONIZADO a pedido da editora: em vez de sortear 1 de 5 efeitos
 * por imagem (com glow-pulse, micro-rotação, etc.), toda imagem faz o MESMO movimento — um Ken
 * Burns clássico, calmo e dinâmico: zoom-in lento e contínuo + pan diagonal suave, ao longo de
 * toda a cena. Nada de brilho pulsante, rotação ou "respiração" senoidal (o senoidal saiu porque
 * o zoom monotônico já nunca congela — está sempre avançando). Ver decisoes-changelog 2026-07-09.
 *
 *   1) ESCOLHA + TEMPO: a cada bloco sorteia uma imagem (NUNCA repete a imagem imediatamente
 *      anterior) e um tempo de tela exclusivo (10–15 s). A galeria cobre exatamente o áudio.
 *   2) MOVIMENTO FIXO: zoom-in de scale 1.08 → 1.18 + pan diagonal ~±12 px, progressivo ao longo
 *      da cena (mesmo em toda imagem). Base > 1 garante margem — o pan nunca revela borda preta.
 *   3) TRANSIÇÃO (SEM tela preta): só fade (padrão, o mais calmo) ou slide. Flip / clockWipe / wipe
 *      foram removidos por serem bruscos demais. O "Dip to Black" continua BANIDO.
 *
 * Determinismo: escolha de imagem / duração / transição são sorteadas por seed (índice do bloco),
 * porque o Remotion re-renderiza o componente a cada frame e em vários processos — `Math.random()`
 * faria o vídeo piscar. Seed = vídeo reprodutível, idêntico a cada render. O movimento não usa
 * sorteio (é o mesmo em toda imagem).
 *
 * O áudio e a legenda NÃO entram aqui: esta composição renderiza só o VÍDEO MUDO; o FFmpeg muxa
 * a narração (tratada) e queima a legenda numa passada só (ver s8_montagem.py / ffmpeg_montagem.py).
 */

// ── Aleatoriedade ESTÁTICA (seeded): mesma seed => mesmo número, sempre ──────────
const getSeededRandom = (seed: string | number, max = 1): number => {
  const num =
    typeof seed === "number"
      ? seed
      : seed.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  const x = Math.sin(num * 12345.67) * 99999.9;
  const rand = x - Math.floor(x);
  return max === 1 ? rand : Math.floor(rand * max);
};

const TRANS_FRAMES = 15; // duração da transição (~0,5 s a 30 fps)
const DIRS = ["from-left", "from-right", "from-top", "from-bottom"] as const;

// ── Imagem FULL-BLEED com movimento ÚNICO calmo (Ken Burns fixo) ─────────────────
// A imagem preenche a tela (objectFit: cover) com um zoom-base > 1 que cria margem suficiente
// para o pan NUNCA revelar borda preta. O movimento é o MESMO em toda imagem: zoom-in lento e
// contínuo (scale 1.08 → 1.18) + pan diagonal suave (~±12 px), progressivo ao longo da cena.
// Monotônico ⇒ está sempre avançando, então nunca "congela" (dispensa o loop senoidal antigo) e
// nunca "treme". Sem brilho/rotação. p = progresso 0→1 da cena (frame relativo à Sequence).
const FullBleedImage: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const p = durationInFrames > 1 ? Math.min(frame / (durationInFrames - 1), 1) : 0;
  const scale = 1.08 + 0.1 * p; // zoom-in lento: 1.08 -> 1.18
  const x = (p - 0.5) * 24; // pan horizontal: -12 -> +12 px
  const y = (p - 0.5) * 14; // pan vertical:   -7  -> +7  px
  const transform = `scale(${scale}) translate(${x}px, ${y}px)`;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform,
        }}
      />
    </AbsoluteFill>
  );
};

type Bloco = {
  id: string;
  durationInFrames: number;
  src: string;
  transRand: number; // sorteio da transição que SAI deste bloco (usa entre bloco i e i+1)
};

export const DynamicGallery: React.FC<{ slug: string; mapping?: Mapping | null }> = ({
  slug,
  mapping,
}) => {
  const { fps, durationInFrames } = useVideoConfig();

  // Lista de imagens ÚNICAS (na ordem em que aparecem no mapping), resolvidas em public/<slug>/.
  const imagens = useMemo<string[]>(() => {
    if (!mapping) return [];
    const vistos = new Set<string>();
    const lista: string[] = [];
    for (const seg of mapping.segments) {
      if (!vistos.has(seg.image)) {
        vistos.add(seg.image);
        lista.push(seg.image);
      }
    }
    return lista;
  }, [mapping]);

  // Monta os blocos cobrindo EXATAMENTE durationInFrames, descontando o overlap das transições
  // (a TransitionSeries sobrepõe TRANS_FRAMES entre blocos vizinhos), para o vídeo casar com o áudio.
  const blocos = useMemo<Bloco[]>(() => {
    const n = imagens.length;
    if (n === 0) return [];
    const lista: Bloco[] = [];
    const minDur = Math.max(fps * 2, TRANS_FRAMES * 2 + 1); // nunca menor que a transição
    let timeline = 0; // frames já ocupados na linha do tempo (com overlaps descontados)
    let i = 0;
    let prevIdx = -1;
    while (timeline < durationInFrames) {
      const overlap = i === 0 ? 0 : TRANS_FRAMES;
      let dur = Math.floor(fps * (10 + getSeededRandom(`duration-${i}`) * 5)); // 10–15 s
      let contrib = dur - overlap; // quanto este bloco adiciona à linha do tempo
      const resto = durationInFrames - timeline;
      if (contrib >= resto) {
        // último bloco: apara para fechar exatamente no fim do áudio
        contrib = resto;
        dur = contrib + overlap;
        if (dur < minDur && lista.length > 0) {
          // sobra curta demais: estica o último bloco em vez de criar um bloco minúsculo
          lista[lista.length - 1].durationInFrames += resto;
          break;
        }
      }
      // REGRA FIXA: o 1º bloco do vídeo é SEMPRE a thumb selecionada (img_000 = imagens[0],
      // pois build-mapping ordena img_*.png e o segmento 0 é a capa). A capa é o "principal" e o
      // vídeo começa por ela — ver memória "video-comeca-pela-thumb". Os demais blocos seguem
      // sorteados, NUNCA repetindo a imagem imediatamente anterior (anti "bug" de repetição).
      let idx = i === 0 ? 0 : getSeededRandom(`img-${i}`, n);
      if (i > 0 && n > 1 && idx === prevIdx) idx = (idx + 1) % n;
      prevIdx = idx;

      lista.push({
        id: `block-${i}-img-${idx}`,
        durationInFrames: dur,
        src: staticFile(`${slug}/${imagens[idx]}`),
        transRand: getSeededRandom(`trans-${i}`),
      });
      timeline += contrib;
      i++;
      if (i > 100000) break; // trava de segurança
    }
    return lista;
  }, [imagens, slug, fps, durationInFrames]);

  if (!mapping || blocos.length === 0) {
    return (
      <AbsoluteFill
        style={{
          backgroundColor: "#0e0e10",
          color: "#bbb",
          justifyContent: "center",
          alignItems: "center",
          fontFamily: "system-ui",
          fontSize: 40,
        }}
      >
        Sem mapping/imagens para "{slug}". Rode a Etapa 8 (staging) e renderize com --props.
      </AbsoluteFill>
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const transicao = (r: number): TransitionPresentation<any> => {
    // Só transições CALMAS (SEM dip-to-black): fade (padrão, maioria) ou slide. Flip / clockWipe /
    // wipe foram removidos por serem bruscos demais para o tom "dinâmico mas tranquilo".
    if (r <= 0.65) return fade();
    const dir = DIRS[Math.floor(r * 997) % DIRS.length];
    return slide({ direction: dir });
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0e0e10" }}>
      <TransitionSeries>
        {blocos.map((b, idx) => (
          <React.Fragment key={b.id}>
            <TransitionSeries.Sequence durationInFrames={b.durationInFrames}>
              <FullBleedImage src={b.src} />
            </TransitionSeries.Sequence>
            {idx < blocos.length - 1 && (
              <TransitionSeries.Transition
                presentation={transicao(b.transRand)}
                timing={linearTiming({ durationInFrames: TRANS_FRAMES })}
              />
            )}
          </React.Fragment>
        ))}
      </TransitionSeries>
    </AbsoluteFill>
  );
};
