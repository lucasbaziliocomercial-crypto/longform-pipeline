# -*- coding: utf-8 -*-
"""gerar-srt-en.py — versão macOS (Apple Silicon) do transcritor Whisper da Etapa 4.

Substitui o script homônimo do projeto TINAGO (que era GPU/NVIDIA-first no Windows).
Aqui usamos o `faster-whisper` (CTranslate2) rodando na CPU — no M1/M2/M3 o int8 dá
transcrição rápida o suficiente para a narração de ~35 min, sem depender de CUDA.

Contrato (o mesmo que a Etapa 4 espera — ver s4_narracao_srt.run):
  • recebe o caminho do áudio como argv[1];
  • lê a env WHISPER_LANG (default 'en'); no MODO PT a Etapa 4 manda 'pt';
  • grava <audio_stem>.srt AO LADO do áudio (timestamps reais da narração).

Config por env (todas opcionais):
  WHISPER_LANG        idioma da transcrição (default 'en')
  WHISPER_MODEL       tamanho do modelo faster-whisper (default 'small'; use 'medium'
                      p/ mais precisão, 'base'/'tiny' p/ mais velocidade)
  WHISPER_COMPUTE     tipo de cálculo CTranslate2 (default 'int8' — leve na CPU ARM)
  WHISPER_DEVICE      'cpu' (default) — CUDA não existe no Mac

Para instalar a dependência:  pip install faster-whisper
"""

import os
import sys
from pathlib import Path


def _fmt_ts(segundos: float) -> str:
    """Segundos -> 'HH:MM:SS,mmm' (formato SRT)."""
    if segundos < 0:
        segundos = 0.0
    ms = int(round(segundos * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: gerar-srt-en.py <audio.mp3>", file=sys.stderr)
        return 2

    audio = Path(sys.argv[1]).resolve()
    if not audio.is_file():
        print("áudio não encontrado: %s" % audio, file=sys.stderr)
        return 2

    lang = os.environ.get("WHISPER_LANG", "en").strip().lower() or "en"
    modelo = os.environ.get("WHISPER_MODEL", "small").strip() or "small"
    compute = os.environ.get("WHISPER_COMPUTE", "int8").strip() or "int8"
    device = os.environ.get("WHISPER_DEVICE", "cpu").strip() or "cpu"

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper não instalado. Rode:  pip install faster-whisper\n"
            "(é a dependência da transcrição da Etapa 4 nesta máquina macOS.)",
            file=sys.stderr,
        )
        return 1

    print("[whisper] modelo=%s idioma=%s device=%s compute=%s" % (modelo, lang, device, compute), flush=True)
    print("[whisper] carregando modelo (1ª vez baixa os pesos)...", flush=True)
    model = WhisperModel(modelo, device=device, compute_type=compute)

    print("[whisper] transcrevendo %s ..." % audio.name, flush=True)
    segments, info = model.transcribe(
        str(audio),
        language=lang,
        vad_filter=True,               # corta silêncios longos -> timestamps mais firmes
        beam_size=5,
        word_timestamps=False,         # nível de segmento basta (build-mapping reagrupa)
    )

    srt_path = audio.with_suffix(".srt")
    n = 0
    with srt_path.open("w", encoding="utf-8") as fh:
        for seg in segments:
            texto = (seg.text or "").strip()
            if not texto:
                continue
            n += 1
            fh.write("%d\n" % n)
            fh.write("%s --> %s\n" % (_fmt_ts(seg.start), _fmt_ts(seg.end)))
            fh.write(texto + "\n\n")
            if n % 25 == 0:
                print("[whisper]   %d cues... (%.0fs)" % (n, seg.end), flush=True)

    if n == 0:
        print("[whisper] ERRO: nenhuma fala transcrita.", file=sys.stderr)
        return 1

    print("[whisper] OK: %s (%d cues)" % (srt_path.name, n), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
