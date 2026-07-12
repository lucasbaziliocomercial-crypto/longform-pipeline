# -*- coding: utf-8 -*-
"""compressor.py — reduz o tamanho do final.mp4 p/ subir mais rápido no YouTube (Etapa 9).

Objetivo: encurtar o TEMPO de upload sem estragar o master. O YouTube SEMPRE re-encoda o
que você sobe, então não adianta comprimir demais — a meta é "alto porém são": um bitrate
generoso (acima da recomendação do YouTube p/ 1080p, ~8–12 Mbps) que ainda deixa o arquivo
bem menor que um master gigante. É CONDICIONAL: se o final.mp4 já for menor que o limiar
(LONGFORM_COMPRIMIR_LIMIAR_GB, default 1.5 GB), NÃO recomprime — só hardlinka/copia p/
final_upload.mp4 (o contrato da fila é sempre ter esse arquivo).

Reusa a AUTODETECÇÃO de encoder de hardware do ffmpeg_montagem (`_encoder`): NVIDIA (nvenc) →
Intel (qsv) → AMD (amf) → CPU (libx264), com probe real. Assim é rápido em máquina com GPU e
ainda funciona em qualquer PC. Força por LONGFORM_FFMPEG_ENCODER (mesma env da montagem).

Uso CLI:
    py -3 compressor.py <entrada.mp4> [saida.mp4]
    py -3 compressor.py "projects/<slug>"     # usa out/final.mp4 -> out/final_upload.mp4
"""

import os
import subprocess
import sys
from pathlib import Path

from common import achar_ffmpeg, ErroPipeline, SUBPROCESS_FLAGS, forcar_utf8_console

# ffmpeg_montagem já resolve o encoder de HW (com probe). Reusamos p/ não duplicar a lógica.
import ffmpeg_montagem as fm


def _limiar_bytes():
    """Limiar acima do qual vale recomprimir (GB → bytes). Default 1.5 GB."""
    try:
        gb = float(os.environ.get("LONGFORM_COMPRIMIR_LIMIAR_GB", "1.5"))
    except ValueError:
        gb = 1.5
    return int(gb * 1024 * 1024 * 1024)


def _bitrate_alvo():
    """Bitrate de vídeo alvo do upload (VBR com teto). Default 12M (folga sobre os 8M do YouTube)."""
    return os.environ.get("LONGFORM_UPLOAD_BITRATE", "12M").strip() or "12M"


def _args_video_compressao():
    """Args de codec p/ COMPRESSÃO (não a montagem): mesmo encoder de HW resolvido, porém com
    TETO de bitrate (VBR + maxrate) — é o teto que garante o arquivo menor. Um pouco mais
    comprimido que o master da montagem (CQ maior), ainda bem acima do que o YouTube pede."""
    enc = fm._encoder()  # "nvenc" | "qsv" | "amf" | "cpu" (com probe/cache)
    br = _bitrate_alvo()
    # maxrate = alvo; bufsize = 2x (VBV padrão). CQ/CRF um degrau acima do master (mais compressão).
    maxrate = br
    bufsize = _dobrar(br)
    if enc == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23",
                "-b:v", br, "-maxrate", maxrate, "-bufsize", bufsize,
                "-profile:v", "high", "-bf", "2", "-pix_fmt", "yuv420p"]
    if enc == "qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "25", "-maxrate", maxrate,
                "-bufsize", bufsize, "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if enc == "amf":
        return ["-c:v", "h264_amf", "-rc", "vbr_peak", "-qp_i", "24", "-qp_p", "24",
                "-b:v", br, "-maxrate", maxrate, "-bufsize", bufsize,
                "-quality", "balanced", "-pix_fmt", "yuv420p"]
    # cpu (libx264): CRF com teto de bitrate p/ garantir o encolhimento.
    return ["-c:v", "libx264", "-preset", "slow", "-crf", "21",
            "-maxrate", maxrate, "-bufsize", bufsize,
            "-profile:v", "high", "-bf", "2", "-pix_fmt", "yuv420p"]


def _dobrar(bitrate):
    """'12M' -> '24M' (bufsize = 2x). Best-effort; devolve o original se não parsear."""
    s = bitrate.strip().upper()
    try:
        if s.endswith("M"):
            return "%dM" % (int(float(s[:-1]) * 2))
        if s.endswith("K"):
            return "%dK" % (int(float(s[:-1]) * 2))
        return "%d" % (int(s) * 2)
    except ValueError:
        return bitrate


def _hardlink_ou_copia(src: Path, dst: Path, log):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            dst.unlink()
        except OSError:
            pass
    try:
        os.link(src, dst)
        log("    [compressor] %s (hardlink — abaixo do limiar, sem recomprimir)." % dst.name)
    except OSError:
        import shutil
        shutil.copyfile(src, dst)
        log("    [compressor] %s (cópia — abaixo do limiar, sem recomprimir)." % dst.name)


def comprimir(entrada, saida, log=print):
    """Comprime `entrada` -> `saida` se valer a pena; senão hardlinka/copia. Devolve o Path de saída.

    "Valer a pena" = arquivo acima de LONGFORM_COMPRIMIR_LIMIAR_GB. Idempotente: se a saída já
    existe e é mais nova que a entrada, pula."""
    entrada = Path(entrada)
    saida = Path(saida)
    if not entrada.is_file() or entrada.stat().st_size == 0:
        raise ErroPipeline("compressor: entrada inexistente/vazia: %s" % entrada)

    if saida.exists() and saida.stat().st_size > 0 and \
       saida.stat().st_mtime >= entrada.stat().st_mtime:
        log("    [compressor] %s já existe e está atualizado — pulando." % saida.name)
        return saida

    tam = entrada.stat().st_size
    limiar = _limiar_bytes()
    mb = tam / (1024 * 1024)
    if tam <= limiar:
        log("    [compressor] entrada tem %.0f MB (≤ limiar %.1f GB) — sem recompressão."
            % (mb, limiar / (1024 ** 3)))
        _hardlink_ou_copia(entrada, saida, log)
        return saida

    ffmpeg = achar_ffmpeg()
    tmp = saida.with_suffix(".tmp.mp4")
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y",
           "-i", str(entrada),
           *_args_video_compressao(),
           "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
           "-movflags", "+faststart", str(tmp)]
    log("    [compressor] entrada %.0f MB (> limiar) — recomprimindo (%s, alvo %s)..."
        % (mb, fm._encoder(), _bitrate_alvo()))
    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, **SUBPROCESS_FLAGS)
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise ErroPipeline("compressor: ffmpeg falhou (código %d)." % proc.returncode)

    novo = tmp.stat().st_size
    # Se a "compressão" ficou MAIOR que o original (conteúdo já muito comprimido), fica com o original.
    if novo >= tam:
        log("    [compressor] recompressão ficou maior (%.0f MB ≥ %.0f MB) — mantendo o original."
            % (novo / (1024 * 1024), mb))
        try:
            tmp.unlink()
        except OSError:
            pass
        _hardlink_ou_copia(entrada, saida, log)
        return saida

    if saida.exists():
        try:
            saida.unlink()
        except OSError:
            pass
    tmp.replace(saida)
    log("    [compressor] pronto: %s (%.0f MB → %.0f MB, -%.0f%%)."
        % (saida.name, mb, novo / (1024 * 1024), 100 * (1 - novo / tam)))
    return saida


def main():
    forcar_utf8_console()
    args = sys.argv[1:]
    if not args:
        print("uso: py -3 compressor.py <entrada.mp4|projects/slug> [saida.mp4]")
        return 2
    alvo = Path(args[0])
    if alvo.is_dir():
        entrada = alvo / "out" / "final.mp4"
        saida = Path(args[1]) if len(args) > 1 else alvo / "out" / "final_upload.mp4"
    else:
        entrada = alvo
        saida = Path(args[1]) if len(args) > 1 else entrada.with_name("final_upload.mp4")
    comprimir(entrada, saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
