"""
fix_primeiro_take.py — substitui o primeiro take do vídeo final pela thumbnail selecionada.

Uso:
    py -3 fix_primeiro_take.py "<pasta_projeto>" "<video_entrada.mp4>" "<video_saida.mp4>"

O script:
  1. Cria clip de 29.037s a partir de thumb_selected.png (mesma duração do take 0)
  2. Queima as legendas do SRT (mesmo estilo do pipeline) sobre esse clip
  3. Extrai o vídeo (sem áudio) de 29.037s ao fim do vídeo final
  4. Concatena os dois vídeos
  5. Extrai o áudio completo do vídeo original e remuxeia
  → saída: video com thumbnail no 1º take, resto + áudio intactos
"""
import sys
import subprocess
import shutil
from pathlib import Path

# adiciona orchestrator ao path para importar ffmpeg_montagem
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from ffmpeg_montagem import _preparar_ass, LEGENDA_STYLE, CAPTION_MAX_CHARS


def _run(cmd, descricao, cwd=None):
    print(f"\n>> {descricao}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, encoding="utf-8", errors="replace")
    if r.stdout:
        print(r.stdout[-3000:])
    if r.returncode != 0:
        raise SystemExit(f"ERRO: {descricao}")


def _args_video():
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]


def fix_primeiro_take(proj_dir: str, final_in: str, final_out: str):
    proj     = Path(proj_dir).resolve()
    fin      = Path(final_in).resolve()
    fout     = Path(final_out).resolve()
    thumb    = proj / "thumb_selected.png"
    srt      = proj / "narration.srt"
    tmp      = proj / "_tmp_fixframe"
    tmp.mkdir(exist_ok=True)

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    # --- duração do take 0 (hard-coded do mapping.json; ajuste se necessário) ---
    take_dur = "29.037"

    # 1. Clip raw da thumbnail (sem áudio, sem legenda)
    first_raw = tmp / "first_raw.mp4"
    _run([ffmpeg, "-y", "-loop", "1", "-i", str(thumb),
          "-t", take_dur,
          "-vf", ("scale=1920:1080:force_original_aspect_ratio=decrease,"
                  "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"),
          "-r", "30", *_args_video(), "-an", str(first_raw)],
         "Clip thumbnail (raw, sem legenda)")

    # 2. Prepara ASS (mesmo fluxo do pipeline: slicing de cues + PlayRes 1920x1080)
    ass = _preparar_ass(ffmpeg, srt, CAPTION_MAX_CHARS)
    first_take = tmp / "first_take.mp4"
    vf = f"subtitles={ass.name}:force_style='{LEGENDA_STYLE}'"
    _run([ffmpeg, "-y", "-i", str(first_raw),
          "-vf", vf, *_args_video(), "-an", str(first_take)],
         "Queimando legendas no clip da thumbnail",
         cwd=str(ass.parent))

    # 3. Extrai vídeo (sem áudio) do trecho restante (29.037s → fim)
    rest_v = tmp / "rest_video.mp4"
    _run([ffmpeg, "-y", "-ss", take_dur, "-i", str(fin),
          "-c:v", "copy", "-an", str(rest_v)],
         "Extraindo resto do vídeo (sem áudio)")

    # 4. Concatena os dois vídeos (concat demuxer)
    concat_txt = tmp / "concat.txt"
    concat_txt.write_text(
        f"file '{str(first_take).replace(chr(92), '/')}'\n"
        f"file '{str(rest_v).replace(chr(92), '/')}'\n"
    )
    combined = tmp / "combined_video.mp4"
    # Nota: primeiro take foi re-encodado; rest_video é stream-copy → re-encoda o concat
    # para garantir compatibilidade de profile/nível entre os dois segmentos.
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
          *_args_video(), "-an", str(combined)],
         "Concatenando vídeos")

    # 5. Extrai áudio original completo
    audio = tmp / "audio.aac"
    _run([ffmpeg, "-y", "-i", str(fin), "-vn", "-c:a", "copy", str(audio)],
         "Extraindo áudio original")

    # 6. Muxeia vídeo combinado + áudio
    fout.parent.mkdir(parents=True, exist_ok=True)
    _run([ffmpeg, "-y", "-i", str(combined), "-i", str(audio),
          "-c:v", "copy", "-c:a", "copy", str(fout)],
         "Muxando vídeo final")

    print(f"\nPronto: {fout}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("uso: py -3 fix_primeiro_take.py <proj_dir> <video_in.mp4> <video_out.mp4>")
        sys.exit(1)
    fix_primeiro_take(sys.argv[1], sys.argv[2], sys.argv[3])
