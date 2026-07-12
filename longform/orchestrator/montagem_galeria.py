# -*- coding: utf-8 -*-
"""montagem_galeria.py — motor de montagem GALERIA no FFmpeg (Fase 2: substitui o Chromium).

Reproduz, SEM Remotion, o MESMO visual do engine `dynamic` de hoje (DynamicGallery.tsx):
galeria viva de imagens cheias 1920x1080, em ORDEM ALEATÓRIA (nunca repete a anterior, começa
pela capa img_000), cada uma na tela por 10–15 s com um Ken Burns calmo (zoom-in lento
1.08→1.18 + leve deriva diagonal) e transições SÓ fade/slide (SEM dip-to-black). Como a editora
removeu os efeitos que só o Chromium fazia (glow/flip/clockWipe), nada aqui exige navegador — o
FFmpeg desenha tudo (`zoompan` + `xfade`) em ordens de magnitude menos tempo que o Remotion.

Este módulo produz APENAS o `out/video_mudo.mp4` (mudo, sem legenda) — o mesmo contrato do render
dinâmico. O `s8_montagem.py` chama depois o `ffmpeg_montagem.py --finalizar` (mux da narração
tratada + queima da legenda), IDÊNTICO ao caminho `dynamic`. Assim a única coisa que muda entre os
dois motores é COMO o vídeo mudo é gerado (Chromium × FFmpeg); o áudio e a legenda são os mesmos.

A timeline de blocos (imagem escolhida / duração / transição) é portada FIELMENTE do
DynamicGallery.tsx (mesma seed determinística e mesma matemática de fechamento do último bloco),
então a soma dos blocos fecha EXATAMENTE em `durationInFrames` (== duração do áudio) e o vídeo
continua sincronizado com a narração e a legenda.

Env (todas com default seguro):
  LONGFORM_GALERIA_TRANS_FRAMES   frames de cada transição fade/slide (default 15 = ~0,5 s @30fps)
  LONGFORM_GALERIA_ZOOM_BASE      zoom inicial de cada cena (default 1.08)
  LONGFORM_GALERIA_ZOOM_AMP       quanto o zoom cresce na cena (default 0.10 → 1.08→1.18)
  LONGFORM_GALERIA_PAN_FRAC       fração da meia-margem usada na deriva diagonal (default 0.22)
"""

import os
import sys
import json
import math
import shutil
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import achar_ffmpeg, ErroPipeline, SUBPROCESS_FLAGS  # noqa: E402
import ffmpeg_montagem as fm  # reusa encoder/upscale/motionblur/paralelismo  # noqa: E402


def _f(env, default):
    try:
        return float(os.environ.get(env, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _trans_frames():
    return max(1, _i("LONGFORM_GALERIA_TRANS_FRAMES", 15))


# ── Aleatoriedade SEMEADA — porta idêntica do getSeededRandom() do DynamicGallery.tsx ──
# num = soma dos charCodes (se string); x = sin(num*12345.67)*99999.9; rand = x - floor(x).
# math.sin do Python == Math.sin do JS (double IEEE754), então a sequência bate com o TSX.
def _seeded(seed, mx=1):
    if isinstance(seed, (int, float)):
        num = seed
    else:
        num = sum(ord(c) for c in str(seed))
    x = math.sin(num * 12345.67) * 99999.9
    rand = x - math.floor(x)
    return rand if mx == 1 else int(math.floor(rand * mx))


def _imagens_unicas(mapping):
    """Lista de imagens ÚNICAS na ordem em que aparecem no mapping (idem DynamicGallery)."""
    vistos, lista = set(), []
    for seg in mapping.get("segments", []):
        img = seg["image"]
        if img not in vistos:
            vistos.add(img)
            lista.append(img)
    return lista


def construir_blocos(mapping):
    """Porta FIEL do useMemo `blocos` do DynamicGallery.tsx.

    Devolve lista de dicts {index, image, durationInFrames, trans_rand}. A soma dos 'contribs'
    (dur - overlap) fecha EXATAMENTE em durationInFrames — validado em __main__.
    """
    fps = int(mapping["fps"])
    total = int(mapping["durationInFrames"])
    imagens = _imagens_unicas(mapping)
    n = len(imagens)
    if n == 0:
        return []
    trans = _trans_frames()
    min_dur = max(fps * 2, trans * 2 + 1)
    blocos = []
    timeline = 0
    i = 0
    prev_idx = -1
    while timeline < total:
        overlap = 0 if i == 0 else trans
        dur = math.floor(fps * (10 + _seeded("duration-%d" % i) * 5))  # 10–15 s
        contrib = dur - overlap
        resto = total - timeline
        if contrib >= resto:
            contrib = resto
            dur = contrib + overlap
            if dur < min_dur and blocos:
                blocos[-1]["durationInFrames"] += resto
                break
        # 1º bloco = SEMPRE a capa (imagens[0] = img_000). Os demais sorteados, nunca repetindo
        # a imagem imediatamente anterior.
        idx = 0 if i == 0 else _seeded("img-%d" % i, n)
        if i > 0 and n > 1 and idx == prev_idx:
            idx = (idx + 1) % n
        prev_idx = idx
        blocos.append({
            "index": i,
            "image": imagens[idx],
            "durationInFrames": dur,
            "trans_rand": _seeded("trans-%d" % i),
        })
        timeline += contrib
        i += 1
        if i > 100000:
            break
    return blocos


# ── Ken Burns calmo (idem FullBleedImage: zoom-in linear + deriva diagonal), SEM fade-preto ──
def _expr_zoom(n):
    base = _f("LONGFORM_GALERIA_ZOOM_BASE", 1.08)
    amp = _f("LONGFORM_GALERIA_ZOOM_AMP", 0.10)
    if n <= 1:
        return "%.4f" % base
    return "%.4f+%.4f*on/%d" % (base, amp, n - 1)  # linear (o DynamicGallery não usa ease)


def _expr_pan(n, dim, sinal):
    """Deriva diagonal suave: centro + fração da meia-margem, progressiva e linear. A meia-margem
    é 0 quando zoom=1, então a deriva nunca revela borda preta (o zoom-base > 1 garante folga)."""
    centro = "%s/2-(%s/zoom/2)" % (dim, dim)
    if n <= 1:
        return centro
    frac = _f("LONGFORM_GALERIA_PAN_FRAC", 0.22)
    return "%s%s(%s-%s/zoom)/2*%.4f*on/%d" % (centro, sinal, dim, dim, frac, n - 1)


def _filtro_clipe(n, fps, w, h):
    up = fm._upscale(fps)
    up_w, up_h = w * up, h * up
    z = _expr_zoom(n)
    x = _expr_pan(n, "iw", "+")   # deriva p/ a direita…
    y = _expr_pan(n, "ih", "+")   # …e p/ baixo (diagonal fixa, igual em toda imagem)
    partes = [
        "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos" % (up_w, up_h),
        "crop=%d:%d" % (up_w, up_h),
        "zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d" % (z, x, y, n, w, h, fps),
    ]
    mb = fm._motionblur(fps)
    if mb > 1:
        partes.append("tmix=frames=%d" % mb)
    partes.append("setsar=1")
    partes.append("format=yuv420p")
    return ",".join(partes)


def _xfade_nome(trans_rand):
    """Mapeia o sorteio p/ uma transição do xfade — MESMA regra do DynamicGallery.transicao():
    r<=0.65 → fade; senão slide numa das 4 direções. SEM dip-to-black."""
    if trans_rand <= 0.65:
        return "fade"
    dirs = ["slideright", "slideleft", "slidedown", "slideup"]  # from-left/right/top/bottom
    return dirs[int(math.floor(trans_rand * 997)) % len(dirs)]


def construir_mudo(pasta, out=None, log=print):
    """Gera out/video_mudo.mp4 (mudo, sem legenda) no estilo galeria, via FFmpeg.

    1) build-mapping já rodou (s8) → lê mapping.json.
    2) monta os blocos (ordem/duração/transição) portados do DynamicGallery.
    3) renderiza 1 clipe Ken Burns por bloco (paralelo, reusando o encoder/paralelismo do FFmpeg).
    4) encadeia os clipes com xfade (fade/slide) → vídeo mudo, cuja duração fecha com o áudio.
    """
    pasta = Path(pasta).resolve()
    mp = pasta / "mapping.json"
    if not mp.is_file():
        raise ErroPipeline("mapping.json não encontrado em %s (rode build-mapping.py)." % pasta)
    mapping = json.loads(mp.read_text(encoding="utf-8"))
    fps, w, h = int(mapping["fps"]), int(mapping["width"]), int(mapping["height"])
    total = int(mapping["durationInFrames"])
    blocos = construir_blocos(mapping)
    if not blocos:
        raise ErroPipeline("montagem galeria: nenhum bloco (mapping sem imagens?).")

    ffmpeg = achar_ffmpeg()
    out = Path(out) if out else (pasta / "out" / "video_mudo.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = pasta / "out" / "_galeria"
    tmp.mkdir(parents=True, exist_ok=True)
    base_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats"]

    # 1) Renderiza cada bloco como um clipe Ken Burns (SEM fade-preto).
    def _montar(k, b):
        img = pasta / b["image"]
        if not img.is_file():
            raise ErroPipeline("imagem do bloco %d não existe: %s" % (k, img))
        n = max(1, int(b["durationInFrames"]))
        clip = tmp / ("blk_%03d.mp4" % k)
        filtro = _filtro_clipe(n, fps, w, h)
        cpu = fm._encoder() == "cpu"
        thr_glob = ["-filter_threads", "1"] if cpu else []
        thr_out = ["-threads", "1"] if cpu else []
        cmd = base_cmd + thr_glob + [
            "-i", str(img),
            "-filter_complex", "[0:v]" + filtro + "[v]",
            "-map", "[v]", "-frames:v", str(n),
            "-r", str(fps), *thr_out, *fm._args_video(), str(clip),
        ]
        return k, clip, cmd, n

    trabalhos = [_montar(k, b) for k, b in enumerate(blocos)]
    clips = [None] * len(blocos)
    durs = [t[3] for t in trabalhos]
    par = fm._paralelo(len(blocos))
    log("▶ Galeria FFmpeg: %d blocos (Ken Burns), %d em paralelo, xfade fade/slide (sem preto)."
        % (len(blocos), par))
    t0 = time.perf_counter()
    erros = []

    def _exec(t):
        k, clip, cmd, _n = t
        rc, saida = fm._run_silencioso(cmd)
        return k, clip, rc, saida

    with ThreadPoolExecutor(max_workers=par) as ex:
        feitos = 0
        for fut in as_completed([ex.submit(_exec, t) for t in trabalhos]):
            k, clip, rc, saida = fut.result()
            feitos += 1
            if rc != 0:
                erros.append((k, saida))
                log("   [FALHOU] bloco %d (código %d)" % (k, rc))
            else:
                clips[k] = clip
                if feitos % 10 == 0 or feitos == len(blocos):
                    log("   [ok %d/%d] blocos Ken Burns" % (feitos, len(blocos)))
    if erros:
        k, s = erros[0]
        cauda = "\n".join((s or "").splitlines()[-6:])
        raise ErroPipeline("FFmpeg falhou no bloco %d da galeria:\n%s" % (k, cauda))
    dt = time.perf_counter() - t0
    log("   Ken Burns: %d blocos em %.0f s (%.1f min)." % (len(blocos), dt, dt / 60.0))

    # 2) Encadeia com xfade. offset_k (em s) = acumulado - trans; acumulado += dur_k - trans.
    trans = _trans_frames()
    d_sec = trans / float(fps)
    if len(clips) == 1:
        shutil.copyfile(clips[0], out)
    else:
        inputs = []
        for c in clips:
            inputs += ["-i", str(c)]
        filtros = []
        acc = durs[0] / float(fps)          # duração acumulada (s) do stream já encadeado
        rotulo = "[0:v]"
        for k in range(1, len(clips)):
            off = acc - d_sec
            nome = _xfade_nome(blocos[k - 1]["trans_rand"])
            saida = "[x%d]" % k
            filtros.append("%s[%d:v]xfade=transition=%s:duration=%.4f:offset=%.4f%s"
                           % (rotulo, k, nome, d_sec, max(0.0, off), saida))
            acc = acc + durs[k] / float(fps) - d_sec
            rotulo = saida
        fc = ";".join(filtros)
        cmd = base_cmd + inputs + [
            "-filter_complex", fc, "-map", rotulo,
            "-r", str(fps), *fm._args_video(), str(out),
        ]
        log("▶ Encadeando %d clipes com xfade → %s" % (len(clips), out.name))
        fm._run(cmd, "xfade de %d clipes" % len(clips))

    if not out.is_file():
        raise ErroPipeline("montagem galeria não gerou %s." % out)
    # Confere a duração (deve fechar com durationInFrames do mapping, ±2 frames).
    got = _contar_frames(ffmpeg, out)
    if got and abs(got - total) > 2:
        log("   ⚠ vídeo mudo com %d frames (esperado ~%d) — pode dessincronizar a legenda." % (got, total))
    else:
        log("   ✅ vídeo mudo galeria: %d frames (~%.1f min)." % (got or total, total / fps / 60.0))
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _contar_frames(ffmpeg, mp4):
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))
    for extra, chave in (([], "nb_frames"), (["-count_frames"], "nb_read_frames")):
        try:
            res = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", *extra,
                                  "-show_entries", "stream=%s" % chave, "-of",
                                  "default=nokey=1:noprint_wrappers=1", str(mp4)],
                                 capture_output=True, text=True, **SUBPROCESS_FLAGS)
            v = int((res.stdout or "0").strip() or 0)
            if v:
                return v
        except (ValueError, OSError):
            pass
    return 0


if __name__ == "__main__":
    # Modo teste: valida que a soma dos blocos fecha com durationInFrames (sem renderizar nada).
    if len(sys.argv) < 2:
        print('uso: py -3 montagem_galeria.py "<pasta_do_projeto>" [--render]')
        raise SystemExit(1)
    pasta = Path(sys.argv[1]).resolve()
    if "--render" in sys.argv:
        construir_mudo(pasta)
    else:
        mapping = json.loads((pasta / "mapping.json").read_text(encoding="utf-8"))
        fps = int(mapping["fps"])
        total = int(mapping["durationInFrames"])
        blocos = construir_blocos(mapping)
        trans = _trans_frames()
        soma = blocos[0]["durationInFrames"] + sum(b["durationInFrames"] - trans for b in blocos[1:])
        print("imagens únicas: %d" % len(_imagens_unicas(mapping)))
        print("blocos: %d | durationInFrames alvo: %d | soma (contribs): %d | diff: %d"
              % (len(blocos), total, soma, soma - total))
        print("dur (s) por bloco:", [round(b["durationInFrames"] / fps, 1) for b in blocos[:8]], "...")
        print("transições:", [_xfade_nome(b["trans_rand"]) for b in blocos[:8]], "...")
