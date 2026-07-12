# -*- coding: utf-8 -*-
"""Etapa 8 — Montagem (16:9). Engine DINÂMICO (v2) + híbrido FFmpeg/Remotion (legado).

Pipeline:
1) build-mapping.py: narration.srt + images/ -> mapping.json (timeline determinística).
2) Render, conforme LONGFORM_RENDER_ENGINE:
   - "dynamic" (DEFAULT na v2): galeria VIVA no Remotion (composição DynamicGallery) — ordem
     das imagens ALEATÓRIA (nunca repete a anterior), movimento ALEATÓRIO (5 efeitos, loop
     senoidal anti-"tremido") e transição ALEATÓRIA (fade/slide/wipe/flip/clockWipe, SEM
     dip-to-black). O Remotion renderiza só o VÍDEO MUDO; depois o FFmpeg (--finalizar) muxa a
     narração TRATADA (denoise/loudnorm) e queima a legenda (libass) num encode só -> final.mp4.
     É MAIS LENTO que o FFmpeg puro (Chromium desenha cada frame), mas é o único que faz as
     transições/efeitos pedidos.
   - "hybrid" e "ffmpeg" (LEGADO): FFmpeg monta o Ken Burns (movimento ease-in-out) + fade
     + áudio -> out/base.mp4 (rápido, sem Chromium). Se as legendas estiverem ligadas, o
     PRÓPRIO FFmpeg queima o narration.srt sobre o base (libass) -> out/final.mp4 numa
     passada barata. Sem legendas, base.mp4 É o final. (Nenhum dos dois chama o Remotion.)
   - "remotion" (LEGADO): Remotion desenha tudo no Chromium (Ken Burns + áudio + legendas) via
     composição LongForm. Mais lento; mantido como fallback.

Por que o dynamic: a usuária pediu vídeo imprevisível (imagens alternando aleatoriamente, sem
"transição pra mesma imagem"), movimento/transições variados e proibição de dip-to-black, além
de matar o "tremido". Isso exige transições do @remotion/transitions (flip/clockWipe/glow) que o
FFmpeg não tem — por isso a v2 volta a renderizar no Remotion. Ver MEMORIA.md e cerebro/decisoes.md.

Env:
   LONGFORM_RENDER_ENGINE = dynamic | hybrid | ffmpeg | remotion   (default: dynamic)
   LONGFORM_CAPTIONS      = 1/true/sim/on para queimar legendas (default: LIGADO;
                            desligue com LONGFORM_CAPTIONS=0)
"""

import os
import time
import json
import shutil
import subprocess
from pathlib import Path

from common import ErroPipeline, REMOTION_DIR, ORCH_DIR, SUBPROCESS_FLAGS, garantir_gpu_preferencia
from runner import rodar_script
from entrega import montar_entrega, criar_atalho_desktop

_VERDADEIRO = {"1", "true", "yes", "sim", "on"}


def _engine():
    # v2: PADRÃO = "dynamic" (galeria viva: ordem/movimento/transição aleatórios, sem dip-to-black,
    # sem "tremido"). Modos legados seguem disponíveis: hybrid | ffmpeg | remotion.
    return (os.environ.get("LONGFORM_RENDER_ENGINE", "dynamic") or "dynamic").strip().lower()


def _captions_on():
    # Legenda LIGADA por padrão (a usuária quer legenda nos vídeos). Desligue com
    # LONGFORM_CAPTIONS=0 (ou false/no/off).
    return (os.environ.get("LONGFORM_CAPTIONS", "1") or "1").strip().lower() in _VERDADEIRO


def _npx_ok():
    """True se o npx existir no PATH (Node.js instalado)."""
    return bool(shutil.which("npx") or shutil.which("npx.cmd"))


def _stage_assets(proj, log, *, base=False):
    """Copia os assets do projeto para remotion/public/<slug>/.

    Sempre leva mapping.json. No modo full-Remotion (base=False) leva áudio + imagens; no
    modo híbrido (base=True) leva o base.mp4 já montado pelo FFmpeg (vídeo + áudio).
    """
    slug = proj.dir.name
    destino = REMOTION_DIR / "public" / slug
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(proj.mapping, destino / "mapping.json")
    if base:
        shutil.copyfile(proj.base_mp4, destino / "base.mp4")
        log("    Assets em remotion/public/%s/ (mapping + base.mp4)." % slug)
    else:
        shutil.copyfile(proj.narration_mp3, destino / "narration.mp3")
        dst_img = destino / "images"
        dst_img.mkdir(exist_ok=True)
        for img in sorted(proj.images_dir.glob("img_*.png")):
            shutil.copyfile(img, dst_img / img.name)
        log("    Assets em remotion/public/%s/ (mapping + áudio + %d imagens)."
            % (slug, len(list(dst_img.glob('img_*.png')))))
    return slug


def _checar_remotion():
    """Valida que o projeto Remotion está instalado e o npx no PATH (ou ErroPipeline)."""
    if not (REMOTION_DIR / "package.json").is_file():
        raise ErroPipeline("Projeto Remotion não encontrado em %s (rode 'npm install' lá)." % REMOTION_DIR)
    if not (REMOTION_DIR / "node_modules").is_dir():
        raise ErroPipeline("Dependências do Remotion não instaladas. Rode 'npm install' em %s." % REMOTION_DIR)
    if not _npx_ok():
        raise ErroPipeline("npx não encontrado no PATH. Instale o Node.js para renderizar no Remotion.")


def _remotion_flags():
    """Flags de ACELERAÇÃO do render (o gargalo do dynamic é o Chromium desenhar cada frame).
    Defaults agressivos p/ velocidade, todos calibráveis por env (e desligáveis com "off"):
      --gl=angle               usa a GPU p/ desenhar (testado nesta máquina; cai p/ swangle se off)
      --hardware-acceleration  usa o encoder de hardware (NVENC na NVIDIA) p/ codificar o vídeo
      --concurrency=<n>        renderiza n frames em paralelo (default = nº de núcleos)
      --image-format=jpeg      captura cada frame como JPEG (não PNG). PNG é lossless mas o encode
                               por frame é MUITO mais lento; como o vídeo mudo é RE-ENCODADO depois
                               pelo FFmpeg (--finalizar muxa a narração + queima a legenda num encode
                               novo), a qualidade final é ditada pelo CQ do NVENC lá, não pelo frame
                               intermediário. JPEG q100 é visualmente lossless e corta o tempo de
                               captura de cada frame. Desligável com LONGFORM_REMOTION_IMG_FMT=png.
    """
    gl = (os.environ.get("LONGFORM_REMOTION_GL", "angle") or "angle").strip()
    hw = (os.environ.get("LONGFORM_REMOTION_HWACCEL", "if-possible") or "if-possible").strip()
    img_fmt = (os.environ.get("LONGFORM_REMOTION_IMG_FMT", "jpeg") or "jpeg").strip().lower()
    try:
        jpeg_q = int(os.environ.get("LONGFORM_REMOTION_JPEG_QUALITY", "100"))
    except (TypeError, ValueError):
        jpeg_q = 100
    try:
        conc = int(os.environ.get("LONGFORM_REMOTION_CONCURRENCY", str(os.cpu_count() or 4)))
    except (TypeError, ValueError):
        conc = os.cpu_count() or 4
    flags = ""
    if gl and gl.lower() != "off":
        flags += " --gl=%s" % gl
    if hw and hw.lower() != "off":
        flags += " --hardware-acceleration=%s" % hw
    if img_fmt and img_fmt != "off":
        flags += " --image-format=%s" % img_fmt
        if img_fmt == "jpeg" and 1 <= jpeg_q <= 100:
            flags += " --jpeg-quality=%d" % jpeg_q
    if conc and conc > 0:
        flags += " --concurrency=%d" % conc
    return flags


def _rodar_remotion(cmd_str, log, cancel, out_path):
    """Dispara um `npx remotion render` (cmd como STRING + shell=True), faz streaming do log e
    valida a saída. MESMO padrão do sidecar CapCut (capcut_tts.py) que funciona nesta máquina:
    `npx` é resolvido pelo PATH (não pelo caminho absoluto com espaço que o cmd /c quebrava); os
    caminhos com espaço vão entre aspas e, como o comando NÃO começa com aspas, o cmd.exe as preserva.
    """
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(cmd_str, cwd=str(REMOTION_DIR), env=env, shell=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, encoding="utf-8", errors="replace",
                            **SUBPROCESS_FLAGS)
    for linha in proc.stdout:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            raise ErroPipeline("Cancelado pelo usuário.")
        linha = linha.rstrip("\n")
        if linha.strip():
            log("    " + linha[:200])
    proc.wait()
    if proc.returncode != 0 or not Path(out_path).is_file():
        raise ErroPipeline("Render do Remotion falhou (código %s)." % proc.returncode)


def _render_remotion(proj, log, cancel, comp_id, props, out_path=None):
    """Renderiza uma composição do Remotion -> out_path (default: proj.final_mp4)."""
    _checar_remotion()
    # ACELERAÇÃO: garante que o Windows rode o Chromium do Remotion na GPU DEDICADA (NVIDIA),
    # não na integrada/software (~3x mais lento). Auto-curável (se o Remotion atualizar, o
    # caminho do .exe muda e isto regrava a preferência). Best-effort — nunca derruba o render.
    garantir_gpu_preferencia(log)

    out_path = Path(out_path) if out_path else proj.final_mp4
    out_path.parent.mkdir(parents=True, exist_ok=True)
    props_file = proj.dir / "_remotion_props.json"
    props_file.write_text(json.dumps(props), encoding="utf-8")
    cmd_str = 'npx remotion render %s "%s" "--props=%s"%s' % (comp_id, out_path, props_file, _remotion_flags())
    log("▶ Renderizando no Remotion (%s, 16:9 1920x1080): %s" % (comp_id, cmd_str))
    _rodar_remotion(cmd_str, log, cancel, out_path)


def _total_frames_mapping(proj):
    """Lê a duração TOTAL (em frames) do mapping.json — a mesma que a composição usa em
    calculateMetadata (mapping.durationInFrames). É o limite p/ fatiar o render em blocos."""
    dados = json.loads(Path(proj.mapping).read_text(encoding="utf-8"))
    return int(dados.get("durationInFrames") or 0)


def _render_cmd(serve, comp_id, out, props_file, flags, frames=None):
    """Monta a STRING do `npx remotion render`. Se `serve` (pasta de um bundle já pronto) for
    dado, ele entra como 1º positional (serveUrl) e o Remotion NÃO re-bundla nem re-copia o
    public/ — só renderiza. Sem `serve`, cai no formato antigo (bundla a cada chamada)."""
    fr = (" --frames=%d-%d" % frames) if frames else ""
    if serve:
        return 'npx remotion render "%s" %s "%s" "--props=%s"%s%s' % (
            serve, comp_id, out, props_file, fr, flags)
    return 'npx remotion render %s "%s" "--props=%s"%s%s' % (comp_id, out, props_file, fr, flags)


def _rodar_remotion_bundle(cmd_str, log, cancel, destino):
    """Igual ao _rodar_remotion, mas valida uma PASTA de bundle (destino/index.html) em vez de
    um arquivo de saída. Usado pelo bundle-único."""
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(cmd_str, cwd=str(REMOTION_DIR), env=env, shell=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, encoding="utf-8", errors="replace",
                            **SUBPROCESS_FLAGS)
    for linha in proc.stdout:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            raise ErroPipeline("Cancelado pelo usuário.")
        linha = linha.rstrip("\n")
        if linha.strip():
            log("    " + linha[:200])
    proc.wait()
    if proc.returncode != 0 or not (Path(destino) / "index.html").is_file():
        raise ErroPipeline("Bundle do Remotion falhou (código %s)." % proc.returncode)


def _bundle_uma_vez(proj, log, cancel):
    """Faz UM bundle do Remotion e devolve o caminho da pasta, p/ REUSAR em TODOS os blocos.

    PORQUÊ (medido nesta máquina, RTX 2060): cada bloco roda um `npx remotion render` que
    RE-BUNDLA o projeto (webpack) e RE-COPIA a pasta public/ inteira (~960 MB, dezenas de
    projetos staged) — ~6 s desperdiçados POR BLOCO. Um vídeo de ~29 min tem ~15 blocos ⇒
    ~1,5 min só de bundle repetido. Bundlando UMA vez e passando o serveUrl (a pasta do bundle)
    pra cada `render`, esse custo vira ~6 s no TOTAL do render inteiro. O bundle depende só do
    CÓDIGO + assets, então o vídeo mudo sai IDÊNTICO (frames byte a byte — seed por frame
    absoluto). Best-effort: se o bundle falhar, devolve None e o caller cai no modo antigo
    (bundla por bloco). Desligável com LONGFORM_REMOTION_BUNDLE_UMA_VEZ=0.
    """
    v = (os.environ.get("LONGFORM_REMOTION_BUNDLE_UMA_VEZ", "1") or "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return None
    if cancel is not None and cancel.is_set():
        raise ErroPipeline("Cancelado pelo usuário.")
    destino = proj.dir / "out" / "_bundle"
    shutil.rmtree(destino, ignore_errors=True)  # sempre fresco (o código pode ter mudado; custa ~5 s)
    cmd = 'npx remotion bundle --out-dir "%s"' % destino
    log("▶ Bundle ÚNICO do Remotion (reusado em todos os blocos, evita re-bundle+cópia por bloco): %s" % cmd)
    try:
        _rodar_remotion_bundle(cmd, log, cancel, destino)
    except ErroPipeline as e:
        log("    ⚠ bundle único falhou (%s) — caindo no modo antigo (cada bloco bundla)." % e)
        shutil.rmtree(destino, ignore_errors=True)
        return None
    return str(destino)


def _render_remotion_blocos(proj, log, cancel, comp_id, props, out_path):
    """Renderiza o vídeo MUDO da DynamicGallery em BLOCOS (faixas de frames), um processo Remotion
    por bloco, e concatena sem recompressão (-c copy) -> out_path.

    PORQUÊ: o Chromium/Remotion vaza memória ao longo de um render de dezenas de milhares de frames;
    nesta máquina (RTX 2060, 6 GB de VRAM) a VRAM enche, cai pra swap e o render ou rasteja por horas
    ou estoura ("código 1"). Cada bloco é um PROCESSO NOVO: a memória zera entre blocos, então o
    render mantém o ritmo rápido do começo ao fim E nunca estoura. A galeria é SEMEADA por frame
    ABSOLUTO (índice do bloco visual + useCurrentFrame()), então as faixas casam perfeitamente — o
    vídeo final é IDÊNTICO ao render de uma tacada só. Determinístico ⇒ sem flicker nas emendas.

    Tamanho do bloco em frames por LONGFORM_REMOTION_CHUNK_FRAMES (default 3600 = 2 min @30fps).
    0/negativo desliga o fatiamento (volta ao render único). Blocos já prontos são reaproveitados
    (idempotência/retomada). Os blocos só são apagados após a concatenação dar certo.
    """
    _checar_remotion()
    garantir_gpu_preferencia(log)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    props_file = proj.dir / "_remotion_props.json"
    props_file.write_text(json.dumps(props), encoding="utf-8")

    total = _total_frames_mapping(proj)
    try:
        passo = int(os.environ.get("LONGFORM_REMOTION_CHUNK_FRAMES", "3600"))
    except (TypeError, ValueError):
        passo = 3600

    # OTIMIZAÇÃO (2026-07-09): bundle UMA vez e reusa em todos os blocos (elimina o re-bundle +
    # a re-cópia de ~960 MB de public/ por bloco). `serve` = pasta do bundle, ou None (fallback:
    # cada render bundla sozinho, comportamento antigo). O try/finally garante a limpeza do bundle.
    serve = _bundle_uma_vez(proj, log, cancel)
    try:
        # Sem fatiamento (desligado ou vídeo curto): render único — mais simples e sem overhead de emenda.
        if passo <= 0 or total <= 0 or total <= passo:
            cmd_str = _render_cmd(serve, comp_id, out_path, props_file, _remotion_flags())
            log("▶ Render único no Remotion (%s, sem fatiar): %s" % (comp_id, cmd_str))
            _rodar_remotion(cmd_str, log, cancel, out_path)
            return

        blocos_dir = proj.dir / "out" / "_mudo_chunks"
        blocos_dir.mkdir(parents=True, exist_ok=True)
        flags = _remotion_flags()
        faixas = [(i, min(i + passo, total) - 1) for i in range(0, total, passo)]
        log("▶ Render dinâmico em %d blocos de até %d frames (total %d) — memória zera entre blocos "
            "p/ não estourar os 6 GB de VRAM nem cair pra swap." % (len(faixas), passo, total))
        partes = []
        for n, (ini, fim) in enumerate(faixas):
            if cancel is not None and cancel.is_set():
                raise ErroPipeline("Cancelado pelo usuário.")
            parte = blocos_dir / ("chunk_%03d.mp4" % n)
            partes.append(parte)
            esperados = fim - ini + 1
            # Idempotência/retomada: reaproveita o bloco se já tem a contagem de frames certa.
            if parte.is_file() and _contar_frames(parte) == esperados:
                log("    bloco %d/%d (frames %d-%d) já existe — reaproveitando." % (n + 1, len(faixas), ini, fim))
                continue
            cmd_str = _render_cmd(serve, comp_id, parte, props_file, flags, frames=(ini, fim))
            log("▶ bloco %d/%d — frames %d-%d..." % (n + 1, len(faixas), ini, fim))
            _rodar_remotion(cmd_str, log, cancel, parte)
        _concatenar_blocos(log, partes, blocos_dir, out_path, total)
    finally:
        # Limpa o bundle único (não é necessário após o render; sempre refeito na próxima rodada).
        if serve:
            shutil.rmtree(serve, ignore_errors=True)


def _concatenar_blocos(log, partes, blocos_dir, out_path, total):
    # Concatena os blocos SEM recompressão -> vídeo mudo completo. NÃO usar o concat demuxer com
    # -c copy: os MP4 do Remotion carregam um padding de duração no último frame que o demuxer não
    # junta colado, inserindo ~0,048 s de BURACO por emenda — o vídeo fica mais longo que o áudio e a
    # narração/legenda dessincronizam acumulativamente até o fim (≈0,7 s num vídeo com ~14 emendas).
    # Solução canônica e LOSSLESS: remuxa cada bloco p/ MPEG-TS (Annex-B) e concatena pelo protocolo
    # `concat:` com +genpts, que regenera PTS CONTÍNUO (30 fps cravado, total = soma exata dos blocos).
    from common import achar_ffmpeg
    ffmpeg = achar_ffmpeg()
    tss = []
    for p in partes:
        ts = p.with_suffix(".ts")
        cmd = [ffmpeg, "-y", "-i", str(p), "-c", "copy", "-bsf:v", "h264_mp4toannexb",
               "-f", "mpegts", str(ts)]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             **SUBPROCESS_FLAGS)
        if res.returncode != 0 or not ts.is_file():
            raise ErroPipeline("Falha ao remuxar bloco p/ MPEG-TS:\n%s" % (res.stderr or "")[-600:])
        tss.append(ts)
    if out_path.is_file():
        out_path.unlink()
    entrada = "concat:" + "|".join(t.as_posix() for t in tss)
    cmd = [ffmpeg, "-y", "-fflags", "+genpts", "-i", entrada, "-c", "copy", str(out_path)]
    log("▶ Concatenando %d blocos via MPEG-TS (lossless, PTS contínuo) -> %s" % (len(partes), out_path.name))
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         **SUBPROCESS_FLAGS)
    if res.returncode != 0 or not out_path.is_file():
        raise ErroPipeline("Concatenação (MPEG-TS) dos blocos do Remotion falhou:\n%s" % (res.stderr or "")[-800:])
    # Confere a duração total e só então apaga os blocos (libera ~1,5 GB).
    got = _contar_frames(out_path)
    if got and abs(got - total) > 2:
        log("    ⚠ vídeo mudo com %d frames (esperado ~%d) — mantendo os blocos p/ inspeção." % (got, total))
    else:
        shutil.rmtree(blocos_dir, ignore_errors=True)


def _contar_frames(mp4):
    """Conta os frames de um MP4 via ffprobe (0 se não der p/ ler). Tenta primeiro o nb_frames do
    container (instantâneo, sem decodificar); só cai p/ -count_frames (decodifica tudo) se faltar."""
    from common import achar_ffmpeg
    ffprobe = str(Path(achar_ffmpeg()).with_name("ffprobe.exe"))

    def _probe(extra, chave):
        try:
            res = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", *extra,
                                  "-show_entries", "stream=%s" % chave, "-of",
                                  "default=nokey=1:noprint_wrappers=1", str(mp4)],
                                 capture_output=True, text=True, **SUBPROCESS_FLAGS)
            return int((res.stdout or "0").strip() or 0)
        except (ValueError, OSError):
            return 0

    return _probe([], "nb_frames") or _probe(["-count_frames"], "nb_read_frames")


def run(proj, log, cancel=None, **_):
    t0 = time.perf_counter()
    if not proj.existe(proj.narration_srt):
        raise ErroPipeline("Falta narration.srt (Etapa 4) para montar.")
    if not sorted(proj.images_dir.glob("img_*.png")):
        raise ErroPipeline("Faltam imagens em images/ (Etapa 7) para montar.")

    # Idempotência: se o vídeo final já existe E está no FORMATO de render atual, não re-renderiza.
    if proj.existe(proj.final_mp4) and not proj.render_desatualizado():
        log("    out/final.mp4 já existe (mesmo formato de render) — reaproveitando.")
        _entregar(proj, log)
        return

    # Final EXISTE mas é de um formato ANTIGO (motor/fps/legenda mudou — ex.: dynamic 60fps ->
    # hybrid 30fps): RE-RENDERIZA só a Etapa 8 reaproveitando roteiro/narração/imagens (FFmpeg
    # local, ZERO crédito). Apaga apenas os artefatos de RENDER (todos regeneráveis) — o
    # mapping.json some p/ ser reconstruído no fps atual; nada PAGO é tocado.
    if proj.existe(proj.final_mp4) and proj.render_desatualizado():
        log("    ♻ out/final.mp4 é de um formato de render ANTIGO — re-renderizando SÓ a Etapa 8 "
            "(FFmpeg, sem gastar crédito). Roteiro, narração e imagens são reaproveitados.")
        for alvo in (proj.mapping, proj.final_mp4, proj.base_mp4,
                     proj.dir / "out" / "video_mudo.mp4"):
            try:
                Path(alvo).unlink()
            except (OSError, FileNotFoundError):
                pass
        tmp_ffmpeg = proj.dir / "out" / "_ffmpeg"
        if tmp_ffmpeg.is_dir():
            shutil.rmtree(tmp_ffmpeg, ignore_errors=True)

    # 1) mapping.json
    if proj.existe(proj.mapping):
        log("    mapping.json já existe — reaproveitando.")
    else:
        log("▶ Etapa 8/8 — build-mapping (narration.srt + images/ -> mapping.json)...")
        rodar_script([ORCH_DIR / "build-mapping.py", proj.dir], proj.dir, log, cancel)
        if not proj.existe(proj.mapping):
            raise ErroPipeline("build-mapping.py não gerou mapping.json.")

    engine = _engine()

    # ---- Engines de GALERIA VIVA (ordem/duração/transição da galeria, sem dip-to-black): ambos
    #      produzem só o VÍDEO MUDO e depois compartilham o MESMO --finalizar (mux da narração
    #      tratada + queima da legenda num encode só). A única diferença é COMO o mudo é gerado:
    #        - "dynamic" (PADRÃO): Remotion desenha cada frame no Chromium — lento, mas foi o motor
    #          que permitia flip/clockWipe/glow. Hoje a composição só usa Ken Burns + fade/slide.
    #        - "ffmpeg-galeria" (Fase 2): o FFmpeg desenha o MESMO visual (zoompan + xfade) em uma
    #          fração do tempo (não abre Chromium). Como os efeitos que exigiam navegador foram
    #          removidos, o resultado é equivalente. Ver montagem_galeria.py. ----
    if engine in ("dynamic", "ffmpeg-galeria", "galeria", "ffgaleria"):
        mudo = proj.dir / "out" / "video_mudo.mp4"
        ffmpeg_galeria = engine in ("ffmpeg-galeria", "galeria", "ffgaleria")
        if proj.existe(mudo):
            log("    out/video_mudo.mp4 já existe — reaproveitando o render da galeria.")
        elif ffmpeg_galeria:
            log("▶ Etapa 8/8 — Galeria no FFmpeg (vídeo MUDO 16:9, sem Chromium)...")
            import montagem_galeria
            montagem_galeria.construir_mudo(proj.dir, out=mudo, log=log)
        else:
            slug = _stage_assets(proj, log, base=False)
            log("▶ Etapa 8/8 — Remotion (DynamicGallery, vídeo MUDO 16:9)...")
            log("    ⚠ O motor dinâmico desenha cada frame no Chromium — é mais lento que o FFmpeg. "
                "Render em BLOCOS (memória zera entre blocos) p/ manter o ritmo e não estourar a VRAM. "
                "Aguarde. (Alternativa rápida: LONGFORM_RENDER_ENGINE=ffmpeg-galeria.)")
            _render_remotion_blocos(proj, log, cancel, "DynamicGallery", {"slug": slug}, mudo)
        # Finaliza: mux narração tratada (+ legenda se ligada) num encode só -> final.mp4
        cmd = [ORCH_DIR / "ffmpeg_montagem.py", proj.dir, "--finalizar",
               "--in", mudo, "--out", proj.final_mp4, "--audio", proj.narration_mp3]
        if _captions_on():
            if not proj.existe(proj.narration_srt):
                raise ErroPipeline("LONGFORM_CAPTIONS ligado, mas falta narration.srt (Etapa 4). "
                                   "Desligue com LONGFORM_CAPTIONS=0 ou rode a Etapa 4.")
            cmd += ["--srt", proj.narration_srt]
            log("▶ Etapa 8/8 — FFmpeg (mux narração tratada + legenda queimada -> out/final.mp4)...")
        else:
            log("▶ Etapa 8/8 — FFmpeg (mux narração tratada, sem legenda -> out/final.mp4)...")
        rodar_script(cmd, proj.dir, log, cancel)
        if not proj.existe(proj.final_mp4):
            raise ErroPipeline("ffmpeg_montagem.py --finalizar não gerou out/final.mp4.")
        log("    ✅ Vídeo final (dinâmico Remotion + FFmpeg): %s" % proj.final_mp4)
        _entregar(proj, log, t0)
        return

    # ---- Engine LEGADO: Remotion desenha tudo ----
    if engine == "remotion":
        slug = _stage_assets(proj, log, base=False)
        _render_remotion(proj, log, cancel, "LongForm",
                         {"slug": slug, "showCaptions": _captions_on()})
        log("    ✅ Vídeo final (Remotion full): %s" % proj.final_mp4)
        _entregar(proj, log, t0)
        return

    if engine not in ("hybrid", "ffmpeg"):
        raise ErroPipeline("LONGFORM_RENDER_ENGINE inválido: %r (use dynamic | hybrid | ffmpeg | remotion)." % engine)

    # ---- Com legendas (padrão): UM ÚNICO encode — Ken Burns + legenda queimada por take ----
    # A legenda é embutida durante o próprio Ken Burns (timestamps deslocados por take), então
    # NÃO há 2º encode do vídeo inteiro (economiza ~⅓ do tempo de render). Gera final.mp4 direto.
    if _captions_on():
        if not proj.existe(proj.narration_srt):
            raise ErroPipeline("LONGFORM_CAPTIONS ligado, mas falta narration.srt (Etapa 4). "
                               "Desligue com LONGFORM_CAPTIONS=0 ou rode a Etapa 4.")
        log("▶ Etapa 8/8 — FFmpeg (Ken Burns + legenda embutida + áudio -> out/final.mp4)...")
        rodar_script([ORCH_DIR / "ffmpeg_montagem.py", proj.dir, "--com-legenda",
                      "--srt", proj.narration_srt, "--out", proj.final_mp4],
                     proj.dir, log, cancel)
        if not proj.existe(proj.final_mp4):
            raise ErroPipeline("ffmpeg_montagem.py não gerou out/final.mp4 (Ken Burns + legenda).")
        log("    ✅ Vídeo final (FFmpeg, legenda num encode só): %s" % proj.final_mp4)
        _entregar(proj, log, t0)
        return

    # ---- Sem legendas: monta o base.mp4 (que JÁ é o final) ----
    if proj.existe(proj.base_mp4):
        log("    out/base.mp4 já existe — reaproveitando.")
    else:
        log("▶ Etapa 8/8 — FFmpeg (Ken Burns + fade + áudio -> out/base.mp4)...")
        rodar_script([ORCH_DIR / "ffmpeg_montagem.py", proj.dir], proj.dir, log, cancel)
        if not proj.existe(proj.base_mp4):
            raise ErroPipeline("ffmpeg_montagem.py não gerou out/base.mp4.")
    shutil.copyfile(proj.base_mp4, proj.final_mp4)
    log("    ✅ Vídeo final (FFmpeg, sem legenda): %s" % proj.final_mp4)
    _entregar(proj, log, t0)


def _entregar(proj, log, t0=None):
    """Empacota o resultado em longform/ENTREGAS/<Categoria>/<Card>/ e garante o atalho no desktop.

    Falha do empacotamento NUNCA derruba a Etapa 8 — só loga (o final.mp4 já existe).
    `t0` (opcional): início da render p/ logar o tempo total da Etapa 8 (perf_counter).
    """
    # Marca o FORMATO de render produzido (motor/fps/legenda). É esse marcador que faz o
    # 'Continuar' reconhecer um vídeo já no formato novo e NÃO re-renderizar à toa.
    proj.gravar_render_meta()
    if t0 is not None:
        dt = time.perf_counter() - t0
        log("    ⏱ Etapa 8 (montagem) levou %.0f s (%.1f min)." % (dt, dt / 60.0))
    try:
        criar_atalho_desktop(log)
        montar_entrega(proj, log)
    except Exception as e:
        log("    [entrega] aviso: não consegui montar o pacote de entrega (%s)." % e)
