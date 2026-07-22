# -*- coding: utf-8 -*-
"""Etapa 4 — Narração + SRT.

1. synthesize(): SEAM do TTS. Dois providers:
   - "capcut" (default): chama o adapter `capcut_tts.py` direto via lib (sintetizar()),
     com chunking paragraph-aware, **cadeia de fallback de vozes** quando a Joanne
     (artista, `intelligence/create`) bater `SmartToolRateLimit`, e concat FFmpeg no fim.
   - "magnific" (fallback documentado): narração via MCP do Magnific (audio_tts),
     mesmo padrão de chunking + concat.
2. SRT: reusa o gerar-srt-en.py (faster-whisper, GPU-first) do TINAGO para transcrever
   narration.mp3 -> narration.srt com timestamps reais (a SRT nasce da narração).
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from common import (ErroPipeline, WHISPER_SCRIPT, achar_audio, achar_ffmpeg,
                    SUBPROCESS_FLAGS, idioma, nome_idioma)
from runner import (rodar_script, rodar_claude, montar_prompt, MODELO_HUMANIZAR,
                    EFFORT_HUMANIZAR)


def _humanizar_on():
    """Humanização do roteiro (pré-TTS) LIGADA por padrão. Desligue com
    LONGFORM_HUMANIZE_NARRATION=0/off/none/nao."""
    v = os.environ.get("LONGFORM_HUMANIZE_NARRATION", "1").strip().lower()
    return v not in ("0", "off", "none", "nao", "não", "no", "false")


def _fonte_roteiro(proj):
    """Texto que o TTS deve narrar: o roteiro humanizado (roteiro_tts.txt) se existir,
    senão o roteiro.txt original. Centraliza a escolha p/ os dois providers de TTS."""
    return proj.roteiro_tts if proj.existe(proj.roteiro_tts) else proj.roteiro


def humanizar_roteiro(proj, log, cancel=None):
    """Humaniza o roteiro.txt (pontuação/capitalização/formatação) p/ a Joanne ler natural.

    Roda ANTES do TTS, via skill `longform-humanizar-narracao` (claude -p, MODELO_HUMANIZAR
    =Haiku + effort low — é normalização mecânica, não criação). NÃO muda palavras nem conteúdo,
    só a pontuação/cadência
    e formatação limpa (ver a skill p/ as regras = o spec da usuária). Salva em roteiro_tts.txt,
    que o synthesize passa a narrar. Idempotente (pula se roteiro_tts.txt já existe) e
    NÃO-destrutivo (roteiro.txt original fica intacto p/ equipe/legenda).

    Idioma: só roda em US English (idioma()=='en'); no MODO PT é pulada (o spec é p/ inglês).
    Falha do passo NÃO derruba a Etapa 4: se não gerar, narra o roteiro.txt cru e avisa.
    """
    if not _humanizar_on():
        return
    if idioma() != "en":
        log("    humanização do roteiro pulada (só roda em inglês; idioma=%s)." % nome_idioma())
        return
    if proj.existe(proj.roteiro_tts):
        log("    roteiro_tts.txt já existe — humanização pulada.")
        return
    if not proj.existe(proj.roteiro):
        return
    log("▶ Etapa 4/8 — humanizando o roteiro p/ TTS (pontuação/cadência, %s, effort=%s)..."
        % (MODELO_HUMANIZAR, EFFORT_HUMANIZAR or "default"))
    try:
        rodar_claude(montar_prompt("longform-humanizar-narracao"),
                     proj.dir, log, cancel, modelo=MODELO_HUMANIZAR, effort=EFFORT_HUMANIZAR)
    except ErroPipeline as e:
        log("    ⚠ humanização falhou (%s) — narrando o roteiro.txt original." % e)
        return
    if proj.existe(proj.roteiro_tts):
        log("    ✓ roteiro_tts.txt gerado — a narração usará a versão humanizada.")
    else:
        log("    ⚠ skill não gerou roteiro_tts.txt — narrando o roteiro.txt original.")


def synthesize(proj, log, cancel=None, voz=None):
    """SEAM do TTS: gera narration.mp3 a partir de roteiro.txt.

    Escolhe o provider por env LONGFORM_TTS_PROVIDER (config.py já define o default):
      - "capcut"   -> sintetiza direto pelo adapter capcut_tts (chunking + voice fallback).
      - "magnific" -> narração via MCP do Magnific (audio_tts), ver synthesize_magnific().
    """
    provider = os.environ.get("LONGFORM_TTS_PROVIDER", "capcut").strip().lower()

    if provider == "magnific":
        return synthesize_magnific(proj, log, cancel, voz=voz)
    if provider == "capcut":
        return synthesize_capcut(proj, log, cancel, voz=voz)

    raise ErroPipeline(
        "Etapa 4 (TTS) sem provider utilizável. Defina LONGFORM_TTS_PROVIDER=capcut "
        "(default — sidecar CapCut, cadeia de vozes c/ Joanne) ou =magnific (MCP). "
        "Confira longform.env."
    )


def _voice_chain(voz_primaria, log=None):
    """Monta a cadeia [primária, fallbacks...] sem duplicar.

    Primária: argumento `voz_primaria` (CLI) > LONGFORM_TTS_VOICE (Joanne por default).
    Fallbacks: LONGFORM_TTS_VOICE_FALLBACK (CSV) — default 'cool_lady,labebe' (vozes
    EN femininas NÃO-artista, que vão pelo multi_platform e escapam do SmartToolRateLimit).

    MODO PORTUGUÊS (idioma()=='pt'): usa LONGFORM_TTS_VOICE_PT / _FALLBACK_PT. Se ambos
    estiverem vazios, reaproveita a cadeia EN (a narração sai com sotaque) e AVISA — o ID
    de voz pt-BR é da conta CapCut da usuária (liste com `capcut_tts.py --speakers`)."""
    if idioma() == "pt":
        primaria = (voz_primaria or os.environ.get("LONGFORM_TTS_VOICE_PT", "")).strip()
        fb_csv = os.environ.get("LONGFORM_TTS_VOICE_FALLBACK_PT", "").strip()
        if not primaria and not fb_csv:
            if log:
                log("    ⚠ MODO PT sem voz definida (LONGFORM_TTS_VOICE_PT vazio) — narrando "
                    "com a voz EN (vai sair com sotaque). Para uma voz pt-BR de verdade: rode "
                    "`py -3 capcut_tts.py --speakers` e defina LONGFORM_TTS_VOICE_PT no longform.env.")
            primaria = (voz_primaria or os.environ.get("LONGFORM_TTS_VOICE", "")).strip()
            fb_csv = os.environ.get("LONGFORM_TTS_VOICE_FALLBACK", "cool_lady,labebe").strip()
    else:
        primaria = (voz_primaria or os.environ.get("LONGFORM_TTS_VOICE", "")).strip()
        fb_csv = os.environ.get("LONGFORM_TTS_VOICE_FALLBACK", "cool_lady,labebe").strip()
    fallbacks = [v.strip() for v in fb_csv.split(",") if v.strip()]
    cadeia, vistos = [], set()
    for v in [primaria, *fallbacks]:
        if v and v not in vistos:
            cadeia.append(v); vistos.add(v)
    if not cadeia:
        raise ErroPipeline(
            "Etapa 4 (TTS) sem voz definida — confira LONGFORM_TTS_VOICE e LONGFORM_TTS_VOICE_FALLBACK."
        )
    return cadeia


def _esperar_cancelavel(segundos, cancel):
    """Dorme `segundos` em fatias curtas, abortando na hora se o usuário cancelar."""
    restante = float(segundos)
    while restante > 0:
        if cancel is not None and cancel.is_set():
            raise ErroPipeline("Cancelado pelo usuário.")
        passo = min(2.0, restante)
        time.sleep(passo)
        restante -= passo


def _tentar_cadeia(bloco, cadeia, chunk_mp3, base, i, n,
                   queimadas, falhas_consec, cooldown_limite, log):
    """Tenta sintetizar `bloco` percorrendo a cadeia de vozes UMA passada.

    Devolve a voz usada (str) em caso de sucesso; devolve None se TODAS as vozes
    (ainda não queimadas) caíram em rate-limit — sinal p/ o chamador esperar o limite
    liberar e tentar de novo. Erros que NÃO são rate-limit (SystemExit do adapter:
    rede, status inesperado) sobem direto, sem espera (não adianta esperar).
    """
    # import local pra evitar ciclo (orchestrator/ ↔ orchestrator/stages/)
    from capcut_tts import sintetizar, RateLimitError
    for v in cadeia:
        if v in queimadas:
            continue
        try:
            log("    bloco %d/%d (voz=%s, %d chars)..." % (i, n, v, len(bloco)))
            sintetizar(bloco, v, str(chunk_mp3), base=base, log=lambda *a, **k: None)
            falhas_consec[v] = 0
            return v
        except RateLimitError:
            falhas_consec[v] += 1
            if falhas_consec[v] >= cooldown_limite and v not in queimadas:
                queimadas.add(v)
                log("    ⚠ voz '%s' queimada nesta passada (%d falhas seguidas) — pulando até o limite liberar." % (v, falhas_consec[v]))
            else:
                log("    ⚠ voz '%s' em rate-limit — caindo p/ próxima da cadeia." % v)
            continue
    return None


def synthesize_capcut(proj, log, cancel=None, voz=None):
    """Provider 'capcut': chunking + voice fallback + backoff + concat FFmpeg.

    Estratégia em três camadas pra absorver SmartToolRateLimit sem precisar do Magnific:
      1. Quebra o roteiro em blocos de ~LONGFORM_TTS_CHUNK_CHARS (paragraph-aware).
      2. Pra cada bloco, tenta a primeira voz da cadeia; se cair em RateLimitError,
         tenta a próxima da cadeia (fallbacks são vozes não-artista do próprio CapCut,
         que vão pelo multi_platform — outro pool de quota).
      3. Se a cadeia INTEIRA cair em rate-limit no bloco (a conta CapCut atingiu o
         limite global, que pega multi_platform E intelligence/create ao mesmo tempo),
         ESPERA com backoff exponencial e tenta a cadeia de novo — em vez de abortar um
         run de dezenas de blocos. Rate-limit é transitório; só falha de vez após
         LONGFORM_TTS_RATELIMIT_RETRIES esperas. (Mesma filosofia do runner.py com erros
         transitórios da API.)
      4. Concatena os blocos em narration.mp3 via FFmpeg.

    Idempotente: blocos já gerados (`_tts_NN.mp3`) são reaproveitados — então mesmo que
    o run morra, recomeçar retoma do bloco que faltou.
    """
    # import local pra evitar ciclo (orchestrator/ ↔ orchestrator/stages/)
    from capcut_tts import garantir_sidecar

    fonte = _fonte_roteiro(proj)
    texto = fonte.read_text(encoding="utf-8", errors="replace").strip()
    if not texto:
        raise ErroPipeline("%s vazio — nada para narrar." % fonte.name)
    maxlen = int(os.environ.get("LONGFORM_TTS_CHUNK_CHARS", "1500"))
    cadeia = _voice_chain(voz, log=log)
    log("▶ Etapa 4/8 — TTS CapCut (idioma=%s, cadeia=%s, chunk=%d chars)."
        % (nome_idioma(), ", ".join(cadeia), maxlen))

    base = garantir_sidecar(log=log)
    blocos = _chunizar(texto, maxlen)
    log("    %d chars em %d bloco(s)." % (len(texto), len(blocos)))

    # Cooldown: depois de COOLDOWN falhas consecutivas de rate-limit numa voz, ela vira
    # "queimada" e é pulada nas próximas tentativas DESTA passada. Economiza chamadas.
    cooldown_limite = int(os.environ.get("LONGFORM_TTS_VOICE_COOLDOWN", "3"))
    # Backoff quando a cadeia INTEIRA cai em rate-limit num bloco: espera e tenta de novo.
    max_esperas = int(os.environ.get("LONGFORM_TTS_RATELIMIT_RETRIES", "6"))
    wait_base = float(os.environ.get("LONGFORM_TTS_RATELIMIT_WAIT", "45"))
    wait_max = float(os.environ.get("LONGFORM_TTS_RATELIMIT_WAIT_MAX", "300"))
    falhas_consec = {v: 0 for v in cadeia}
    queimadas = set()

    partes, vozes_usadas = [], []
    for i, bloco in enumerate(blocos, 1):
        if cancel is not None and cancel.is_set():
            raise ErroPipeline("Cancelado pelo usuário.")
        chunk_mp3 = proj.dir / ("_tts_%02d.mp3" % i)
        if proj.existe(chunk_mp3):
            log("    bloco %d/%d já existe — pulado." % (i, len(blocos)))
            partes.append(chunk_mp3); continue

        espera_n = 0
        while True:
            voz_ok = _tentar_cadeia(bloco, cadeia, chunk_mp3, base, i, len(blocos),
                                    queimadas, falhas_consec, cooldown_limite, log)
            if voz_ok is not None:
                vozes_usadas.append(voz_ok)
                break
            # A cadeia inteira caiu em rate-limit neste bloco.
            if espera_n >= max_esperas:
                raise ErroPipeline(
                    "Todas as vozes da cadeia CapCut continuam em rate-limit no bloco %d "
                    "mesmo após %d esperas (%s). O limite da conta CapCut não liberou. "
                    "Espere mais e rode de novo (os %d blocos já prontos são reaproveitados), "
                    "aumente LONGFORM_TTS_RATELIMIT_RETRIES/_WAIT, OU adicione vozes "
                    "não-artista em LONGFORM_TTS_VOICE_FALLBACK."
                    % (i, max_esperas, ", ".join(cadeia), i - 1)
                )
            espera = min(wait_base * (2 ** espera_n), wait_max)
            espera_n += 1
            log("    ⏳ cadeia inteira em rate-limit no bloco %d — esperando %.0fs "
                "(espera %d/%d) p/ o limite da conta CapCut liberar..."
                % (i, espera, espera_n, max_esperas))
            _esperar_cancelavel(espera, cancel)
            # O limite pode ter liberado durante a espera: reabilita as vozes queimadas
            # e zera os contadores p/ a próxima passada testar a cadeia inteira de novo.
            queimadas.clear()
            for v in cadeia:
                falhas_consec[v] = 0

        if not proj.existe(chunk_mp3):
            raise ErroPipeline("CapCut TTS não gerou %s (bloco %d)." % (chunk_mp3.name, i))
        partes.append(chunk_mp3)

    if len(partes) == 1:
        shutil.copyfile(partes[0], proj.narration_mp3)
    else:
        _concat_mp3(partes, proj.narration_mp3, log)
    for i in range(1, len(blocos) + 1):
        (proj.dir / ("_tts_%02d.mp3" % i)).unlink(missing_ok=True)
    if not proj.existe(proj.narration_mp3):
        raise ErroPipeline("CapCut TTS não produziu narration.mp3.")
    # resumo de qual voz dominou (info útil quando a cadeia caiu)
    if vozes_usadas:
        from collections import Counter
        ranking = Counter(vozes_usadas).most_common()
        log("    ✓ narration.mp3 pronto (CapCut). Vozes usadas: %s." %
            ", ".join("%s×%d" % (v, n) for v, n in ranking))


def _chunizar(texto, maxlen):
    """Quebra o roteiro em blocos <= maxlen chars, respeitando parágrafos (e frases se preciso)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", texto.strip()) if p.strip()]
    blocos, atual = [], ""
    for p in paras:
        # parágrafo sozinho maior que o limite -> quebra por frase
        pedacos = [p]
        if len(p) > maxlen:
            pedacos = re.split(r"(?<=[.!?])\s+", p)
        for ped in pedacos:
            if atual and len(atual) + len(ped) + 2 > maxlen:
                blocos.append(atual); atual = ped
            else:
                atual = (atual + "\n\n" + ped) if atual else ped
    if atual:
        blocos.append(atual)
    return blocos or [texto]


def _concat_mp3(partes, saida, log):
    """Concatena MP3s na ordem via FFmpeg (concat demuxer, re-encode p/ uniformizar).

    Critério de sucesso = MP3 final existe com tamanho > 0. O exit code do FFmpeg no
    Windows às vezes vem como 4294967294 (-2 não-assinado) mesmo após gerar o arquivo
    — tratar exit code como gate só esconde sucessos. O stderr é capturado p/ surgir
    no log quando houver falha de verdade.
    """
    ff = achar_ffmpeg()
    lista = saida.parent / "_tts_concat.txt"
    lista.write_text(
        "".join("file '%s'\n" % p.name for p in partes), encoding="utf-8"
    )
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
           "-c:a", "libmp3lame", "-q:a", "2", str(saida)]
    log("    Concatenando %d bloco(s) de narração via FFmpeg..." % len(partes))
    proc = subprocess.run(cmd, cwd=str(saida.parent),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          **SUBPROCESS_FLAGS)
    lista.unlink(missing_ok=True)
    ok = saida.exists() and saida.stat().st_size > 0
    if not ok:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        log("    [ffmpeg stderr] " + " | ".join(err[-6:]) if err else "    [ffmpeg sem stderr]")
        raise ErroPipeline("FFmpeg não produziu o MP3 final (código %s)." % proc.returncode)
    if proc.returncode != 0:
        log("    (FFmpeg retornou %s mas o MP3 foi gerado — seguindo.)" % proc.returncode)


def synthesize_magnific(proj, log, cancel=None, voz=None):
    """Provider 'magnific': narra o roteiro via MCP do Magnific (audio_tts).

    Texto longo é quebrado em blocos (~LONGFORM_TTS_CHUNK chars) — cada bloco vira um
    claude -p simples (sintetiza 1 MP3) e no fim os blocos são concatenados com FFmpeg.
    Idempotente por bloco: blocos já gerados (_tts_NN.mp3) são reaproveitados.
    """
    from stages import magnific_seam

    fonte = _fonte_roteiro(proj)
    texto = fonte.read_text(encoding="utf-8", errors="replace").strip()
    if not texto:
        raise ErroPipeline("%s vazio — nada para narrar." % fonte.name)
    voz = voz or os.environ.get("LONGFORM_TTS_MAGNIFIC_VOICE", "631")
    modelo_tts = os.environ.get("LONGFORM_TTS_MAGNIFIC_MODEL", "eleven_turbo_v2_5")
    maxlen = int(os.environ.get("LONGFORM_TTS_CHUNK", "9000"))

    blocos = _chunizar(texto, maxlen)
    log("▶ Etapa 4/8 — TTS Magnific (voz %s, %s): %d chars em %d bloco(s)."
        % (voz, modelo_tts, len(texto), len(blocos)))

    partes = []
    for i, bloco in enumerate(blocos, 1):
        if cancel is not None and cancel.is_set():
            raise ErroPipeline("Cancelado pelo usuário.")
        chunk_txt = proj.dir / ("_tts_%02d.txt" % i)
        chunk_mp3 = proj.dir / ("_tts_%02d.mp3" % i)
        if proj.existe(chunk_mp3):
            log("    bloco %d/%d já existe — pulado." % (i, len(blocos)))
            partes.append(chunk_mp3); continue
        chunk_txt.write_text(bloco, encoding="utf-8")
        instr = ("Você é a Etapa 4 (narração TTS) de uma esteira de vídeo. "
                 + magnific_seam.receita_tts(chunk_txt.name, voz, chunk_mp3.name, modelo_tts))
        log("    Sintetizando bloco %d/%d (%d chars)..." % (i, len(blocos), len(bloco)))
        magnific_seam.gerar(proj, log, cancel, instr, modelo="sonnet")
        if not proj.existe(chunk_mp3):
            raise ErroPipeline("Magnific TTS não gerou %s (bloco %d)." % (chunk_mp3.name, i))
        partes.append(chunk_mp3)

    if len(partes) == 1:
        shutil.copyfile(partes[0], proj.narration_mp3)
    else:
        _concat_mp3(partes, proj.narration_mp3, log)
    # limpa os arquivos de bloco (mantém só narration.mp3)
    for i in range(1, len(blocos) + 1):
        (proj.dir / ("_tts_%02d.txt" % i)).unlink(missing_ok=True)
        (proj.dir / ("_tts_%02d.mp3" % i)).unlink(missing_ok=True)
    if not proj.existe(proj.narration_mp3):
        raise ErroPipeline("TTS Magnific não produziu narration.mp3.")
    log("    ✓ narration.mp3 pronto (Magnific TTS).")


def _pausa_opt_on():
    """Otimização de pausa LIGADA por padrão. Desligue com LONGFORM_PAUSE_OPT=0/off/none/nao."""
    v = os.environ.get("LONGFORM_PAUSE_OPT", "1").strip().lower()
    return v not in ("0", "off", "none", "nao", "não", "no", "false")


def _duracao(ffmpeg, arq):
    """Duração (s) de um arquivo de áudio via ffprobe (ao lado do ffmpeg). 0.0 se falhar."""
    ffprobe = str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(arq)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **SUBPROCESS_FLAGS)
        return float((r.stdout or b"").decode("utf-8", errors="replace").strip() or 0)
    except Exception:
        return 0.0


def _ritmo_alvo_min():
    """Alvo de duração da narração em minutos (LONGFORM_NARRATION_TARGET_MIN). 0/vazio = desligado."""
    v = os.environ.get("LONGFORM_NARRATION_TARGET_MIN", "").strip()
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def _atempo_chain(fator):
    """Monta o filtro atempo do FFmpeg. Cada instância de atempo aceita 0.5..2.0; fatores maiores
    são ENCADEADOS (atempo=2.0,atempo=...). Aqui o fator já vem clampado a <=~1.8, então sai 1 só."""
    fator = max(0.5, fator)
    partes = []
    while fator > 2.0:
        partes.append("atempo=%.4f" % 2.0); fator /= 2.0
    partes.append("atempo=%.4f" % fator)
    return ",".join(partes)


def ajustar_ritmo(proj, log):
    """Acelera a narração para caber em ~LONGFORM_NARRATION_TARGET_MIN minutos, via FFmpeg atempo
    (time-stretch que PRESERVA o timbre — a voz continua a mesma, só fala mais rápido).

    Roda DEPOIS do TTS e ANTES da otimização de pausa/Whisper, então a SRT nasce do áudio já no
    ritmo final e fica sincronizada. É NECESSÁRIO porque o parâmetro `speed` do CapCut é um
    playbackRate do editor e NÃO altera a duração do MP3 gerado (medido: speed 10 e 16 dão a MESMA
    duração) — o ajuste de verdade tem de ser aqui. Só ACELERA (fator>1); nunca desacelera. Clamp por
    LONGFORM_NARRATION_TEMPO_MAX (default 1.8) para não soar artificial. NÃO-destrutivo (guarda
    narration_semritmo.mp3), idempotente (proj.ritmo_flag). Invalida a SRT/pausas antigas p/ o áudio novo.
    """
    alvo = _ritmo_alvo_min()
    if alvo <= 0:
        return
    if proj.existe(proj.ritmo_flag):
        log("    ritmo já ajustado — pulado.")
        return
    if not proj.existe(proj.narration_mp3):
        return
    ff = achar_ffmpeg()
    dur = _duracao(ff, proj.narration_mp3)
    if dur <= 0:
        return
    fator = dur / (alvo * 60.0)
    if fator <= 1.01:
        log("    narração já ≤ alvo (%.1f min ≤ %.0f min) — sem acelerar." % (dur / 60.0, alvo))
        proj.ritmo_flag.write_text("alvo=%.0fmin fator=1.0 (no-op, %.1fs)\n" % (alvo, dur), encoding="utf-8")
        return
    maxf = float(os.environ.get("LONGFORM_NARRATION_TEMPO_MAX", "1.8"))
    fator = min(fator, maxf)
    if not proj.existe(proj.narration_semritmo):
        shutil.copyfile(proj.narration_mp3, proj.narration_semritmo)
    tmp = proj.dir / "_narration_ritmo.mp3"
    af = _atempo_chain(fator)
    log("▶ Etapa 4/8 — ajustando ritmo da narração p/ ~%.0f min (atempo=%.3f, preserva timbre)..."
        % (alvo, fator))
    proc = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                           "-i", str(proj.narration_semritmo), "-filter:a", af,
                           "-c:a", "libmp3lame", "-q:a", "2", str(tmp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SUBPROCESS_FLAGS)
    if not (tmp.exists() and tmp.stat().st_size > 0):
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ErroPipeline("Falha ao ajustar ritmo da narração (FFmpeg): %s" % (err[-300:] or "sem stderr"))
    os.replace(str(tmp), str(proj.narration_mp3))
    # a SRT/pausas/raw antigas nasceram do áudio no ritmo ANTIGO — invalida p/ refazer do novo.
    for artefato in (proj.narration_srt, proj.pausas_flag, proj.narration_raw):
        if proj.existe(artefato):
            artefato.unlink()
    dur2 = _duracao(ff, proj.narration_mp3)
    proj.ritmo_flag.write_text("alvo=%.0fmin fator=%.4f antes=%.1fs depois=%.1fs\n"
                               % (alvo, fator, dur, dur2), encoding="utf-8")
    log("    ✓ ritmo ajustado: %.1f min → %.1f min (atempo=%.3f)." % (dur / 60.0, dur2 / 60.0, fator))


def otimizar_pausas(proj, log):
    """Apara o EXCESSO de silêncio das pausas longas da narração (anti-robótico).

    Roda DEPOIS do TTS e ANTES do Whisper — então a SRT nasce do áudio já otimizado e fica
    sincronizada com a nova duração (legenda casa com a fala). NÃO cola palavras: só encurta
    o silêncio acima de LONGFORM_PAUSE_MIN para LONGFORM_PAUSE_KEEP (via `silenceremove`),
    preservando o ritmo de cada frase — é o "termina a frase → arrasta → continua" que some.

    Defaults = os parâmetros aprovados no A/B (cap acima de 0.30s → 0.22s, piso de -32dB).
    NÃO-destrutivo: o TTS cru é preservado em narration_raw.mp3. Idempotente via proj.pausas_flag.
    Se otimizar de fato, INVALIDA a narration.srt antiga p/ o Whisper reconstruí-la do áudio novo.
    """
    if not _pausa_opt_on():
        return
    if proj.existe(proj.pausas_flag):
        log("    pausas já otimizadas — pulado.")
        return
    if not proj.existe(proj.narration_mp3):
        return

    min_sil = os.environ.get("LONGFORM_PAUSE_MIN", "0.30")      # só apara pausas acima disso
    keep = os.environ.get("LONGFORM_PAUSE_KEEP", "0.22")        # quanto de silêncio deixa
    th = os.environ.get("LONGFORM_PAUSE_THRESHOLD", "-32dB")    # piso p/ detectar "silêncio"
    ff = achar_ffmpeg()

    # Preserva o TTS cru (1ª vez) — assim dá pra recalibrar sem regerar o TTS.
    if not proj.existe(proj.narration_raw):
        shutil.copyfile(proj.narration_mp3, proj.narration_raw)
    dur_antes = _duracao(ff, proj.narration_raw)

    tmp = proj.dir / "_narration_pausas.mp3"
    af = ("silenceremove=stop_periods=-1:stop_duration=%s:stop_threshold=%s:stop_silence=%s"
          % (min_sil, th, keep))
    log("▶ Etapa 4/8 — otimizando pausas da narração (cap >%ss → %ss, piso %s)..."
        % (min_sil, keep, th))
    proc = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                           "-i", str(proj.narration_raw), "-af", af,
                           "-c:a", "libmp3lame", "-q:a", "2", str(tmp)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SUBPROCESS_FLAGS)
    if not (tmp.exists() and tmp.stat().st_size > 0):
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise ErroPipeline("Falha ao otimizar pausas (FFmpeg): %s" % (err[-300:] or "sem stderr"))
    os.replace(str(tmp), str(proj.narration_mp3))
    dur_depois = _duracao(ff, proj.narration_mp3)

    # A SRT antiga (se houver) foi feita do áudio CRU — invalida p/ o Whisper refazer do novo.
    if proj.existe(proj.narration_srt):
        proj.narration_srt.unlink()
        log("    narration.srt antiga removida (será regerada do áudio otimizado).")

    economia = dur_antes - dur_depois
    pct = (100.0 * economia / dur_antes) if dur_antes else 0.0
    proj.pausas_flag.write_text(
        "min=%s keep=%s th=%s antes=%.1fs depois=%.1fs economia=%.1fs (%.0f%%)\n"
        % (min_sil, keep, th, dur_antes, dur_depois, economia, pct), encoding="utf-8")
    log("    ✓ pausas otimizadas: %.1fs → %.1fs (−%.1fs / −%.0f%%)."
        % (dur_antes, dur_depois, economia, pct))


def run(proj, log, cancel=None, voz=None, **_):
    if not proj.existe(proj.roteiro):
        raise ErroPipeline("Falta roteiro.txt (Etapa 2/3) para narrar.")

    # 1) Narração (pula se já existir)
    if proj.existe(proj.narration_mp3):
        log("    narration.mp3 já existe — TTS pulado.")
    else:
        # 1.0) Humaniza o roteiro (pontuação/cadência) ANTES do TTS — a Joanne lê o
        #      roteiro_tts.txt resultante, lendo de forma mais natural. Não-destrutivo/idempotente.
        humanizar_roteiro(proj, log, cancel)
        synthesize(proj, log, cancel, voz=voz)

    # 1.4) Ajuste de ritmo (atempo) p/ caber no alvo de minutos (LONGFORM_NARRATION_TARGET_MIN) —
    #      ANTES da pausa/Whisper, p/ a SRT nascer sincronizada. No-op se o alvo não estiver setado.
    ajustar_ritmo(proj, log)

    # 1.5) Otimização de pausa (anti-robótico) — ANTES do Whisper, p/ a SRT nascer do áudio
    #      já otimizado e ficar sincronizada. Idempotente; não-destrutiva (guarda narration_raw).
    otimizar_pausas(proj, log)

    # 2) SRT via Whisper (pula se já existir)
    if proj.existe(proj.narration_srt):
        log("    narration.srt já existe — Whisper pulado.")
        return
    if not WHISPER_SCRIPT.is_file():
        raise ErroPipeline(
            "Script de Whisper não encontrado em %s. Ajuste a env TINAGO_DIR para a pasta "
            "que contém o gerar-srt-en.py." % WHISPER_SCRIPT
        )
    audio = achar_audio(proj.dir)
    # Idioma da transcrição: o script de Whisper (compartilhado com o TINAGO) lê WHISPER_LANG
    # (default 'en' — comportamento original). No MODO PT mandamos 'pt' p/ a legenda casar
    # com a narração (senão o Whisper transcreveria a fala PT como inglês fonético = legenda quebrada).
    os.environ["WHISPER_LANG"] = idioma()
    log("▶ Etapa 4/8 — SRT (Whisper, GPU c/ fallback CPU, idioma=%s) a partir de %s..."
        % (nome_idioma(), audio.name))
    rodar_script([WHISPER_SCRIPT, audio], proj.dir, log, cancel)
    # o script grava <audio>.srt; garante o nome canônico narration.srt
    gerado = audio.with_suffix(".srt")
    if gerado.exists() and gerado != proj.narration_srt:
        shutil.copyfile(gerado, proj.narration_srt)
    if not proj.existe(proj.narration_srt):
        raise ErroPipeline("Whisper não gerou narration.srt.")
    log("    ✓ narration.srt pronto (timestamps reais da narração).")
