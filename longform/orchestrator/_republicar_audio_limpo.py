# -*- coding: utf-8 -*-
"""Uso pontual: re-publica as ENTREGAS (vídeo+áudio limpos) dos projetos já renderizados.

Após limpar o áudio do final.mp4 in-place, os entregáveis ficaram defasados:
  - ENTREGAS/<slug>/video_final.mp4 era uma CÓPIA do final.mp4 antigo (áudio velho);
  - VIDEOS-PRONTOS/<tema>.mp4 era um HARDLINK que o os.replace desvinculou.
Este script re-roda entrega.montar_entrega() (que recopia/relinka o vídeo limpo) e, além
disso, regrava o narracao.mp3 do bundle com a MESMA cadeia de limpeza (MEDIA) — para que
o áudio standalone do pacote também saia sem chiado. NÃO toca no narration.mp3 do projeto
(o pipeline o mantém cru de propósito; a limpeza é aplicada no mux).
"""
import subprocess
import sys
from pathlib import Path

# Console do Windows é cp1252 — o log de entrega.py usa emoji (📦/🎬). Força UTF-8 no stdout
# pra não estourar UnicodeEncodeError (no pipeline real o log vai pra GUI/arquivo, não pro console).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Projeto, achar_ffmpeg, LONGFORM_DIR  # noqa: E402
import entrega  # noqa: E402
from ffmpeg_montagem import AUDIO_NIVEIS, AUDIO_BITRATE  # noqa: E402

SLUGS = [
    "01-vc-gravida-do-alpha",
    "11-depois-dela-tratar-os-ferimentos-dele",
    "15-ela-viu-ele-marcando-ela",
]


def limpar_mp3(entrada: Path, saida: Path):
    """Aplica a cadeia MEDIA num MP3 -> MP3 limpo (libmp3lame q0)."""
    ff = achar_ffmpeg()
    saida.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(entrada), "-af", AUDIO_NIVEIS["media"],
           "-c:a", "libmp3lame", "-q:a", "0", str(saida)]
    subprocess.run(cmd, check=True)


def main():
    for slug in SLUGS:
        base = LONGFORM_DIR / "projects" / slug
        if not base.is_dir():
            print("PULANDO %s (projeto não existe)." % slug); continue
        proj = Projeto(base)
        print(">>> Re-publicando %s" % slug)
        entrega.montar_entrega(proj, print)
        # narracao.mp3 do bundle: regravar limpo a partir do narration.mp3 cru do projeto
        # (usa pasta_entrega() p/ casar com onde montar_entrega gravou — categoria › card ou plano)
        bundle_mp3 = entrega.pasta_entrega(proj) / "narracao.mp3"
        if proj.narration_mp3.is_file():
            print("    limpando narracao.mp3 do bundle...")
            limpar_mp3(proj.narration_mp3, bundle_mp3)
            print("    ✓ narracao.mp3 limpo: %s" % bundle_mp3)
    print("=== RE-PUBLICAÇÃO CONCLUÍDA ===")


if __name__ == "__main__":
    main()
