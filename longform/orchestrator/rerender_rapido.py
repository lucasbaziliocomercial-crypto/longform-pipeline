# -*- coding: utf-8 -*-
"""rerender_rapido.py — re-renderiza projetos ANTIGOS no padrão novo (30 fps + FFmpeg/hybrid).

Por quê: os vídeos feitos antes de 2026-06-22 saíram pelo motor `dynamic` (Remotion no
Chromium: ~6h e MP4 >2 GB a 60 fps). A automação atual usa `hybrid` (FFmpeg puro, sem
Chromium) a 30 fps — render em minutos e arquivo menor. Este script alinha os antigos a esse
padrão: para cada slug, APAGA o mapping.json (força reconstrução a 30 fps) + as saídas antigas
(final.mp4 / video_mudo.mp4 / base.mp4 / _ffmpeg) e roda só a Etapa 8 (que reconstrói o
mapping e renderiza no FFmpeg respeitando o longform.env).

Uso:
    py -3 longform/orchestrator/rerender_rapido.py <slug> [<slug> ...]
Sem argumentos: usa a LISTA embutida (os projetos com final.mp4 e insumos completos).
Pula automaticamente quem não tiver narration.srt (não dá pra queimar legenda).
"""

import sys
import time
import subprocess
from pathlib import Path

ORCH = Path(__file__).resolve().parent
RAIZ = ORCH.parent.parent                      # raiz do repo
PROJETOS = ORCH.parent / "projects"
PIPELINE = ORCH / "pipeline.py"

# Default: antigos com final.mp4 + insumos (15 fica de fora — sem narration.srt).
SLUGS_PADRAO = [
    "00-ele-teve-que-assistir-ao-horror-de-ver-seu-inimigo-marcan",
    "07-ele-rejeitou-sua-luna-e-escolheu",
    "08-o-alpha-descobriu-o-segredo",
    "11-depois-dela-tratar-os-ferimentos-dele",
    "13-suas-meias-irmas-rasgaram-o-vestido-dela",
    "16-dormiu-na-cama-do-alpha",
]

SOBRAS = ["mapping.json", "out/final.mp4", "out/video_mudo.mp4", "out/base.mp4"]


def limpar(proj: Path):
    for rel in SOBRAS:
        f = proj / rel
        if f.is_file():
            f.unlink()
    tmp = proj / "out" / "_ffmpeg"
    if tmp.is_dir():
        for f in tmp.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass


def main():
    slugs = sys.argv[1:] or SLUGS_PADRAO
    print(">> Re-render rápido (30 fps + FFmpeg). Projetos: %d" % len(slugs), flush=True)
    for i, slug in enumerate(slugs, 1):
        proj = PROJETOS / slug
        print("\n" + "=" * 70, flush=True)
        print(">> [%d/%d] %s" % (i, len(slugs), slug), flush=True)
        if not proj.is_dir():
            print("   PULADO: pasta não existe.", flush=True)
            continue
        if not (proj / "narration.srt").is_file():
            print("   PULADO: sem narration.srt (não dá pra queimar legenda).", flush=True)
            continue
        if not list((proj / "images").glob("img_*.png")):
            print("   PULADO: sem imagens em images/.", flush=True)
            continue
        limpar(proj)
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, str(PIPELINE), "--slug", slug, "8"], cwd=str(RAIZ))
        dt = time.perf_counter() - t0
        fin = proj / "out" / "final.mp4"
        if r.returncode == 0 and fin.is_file():
            mb = fin.stat().st_size / (1024 * 1024)
            print(">> [%d/%d] OK em %.0f s (%.1f min) — final.mp4 %.0f MB"
                  % (i, len(slugs), dt, dt / 60.0, mb), flush=True)
        else:
            print(">> [%d/%d] FALHOU (código %s) após %.0f s" % (i, len(slugs), r.returncode, dt),
                  flush=True)
    print("\n>> Fim do re-render em lote.", flush=True)


if __name__ == "__main__":
    main()
