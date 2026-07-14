# -*- coding: utf-8 -*-
"""humano.py — camada de "comportamento humano" p/ o publicador (proteção do proxy/perfil).

A automação de upload roda em velocidade de máquina: loga, dispara upload, preenche tudo em
milissegundos e agenda em horário cravado (18:00, 18:10…). Isso é um PADRÃO ROBÓTICO — o que
mais chama atenção do YouTube e mais expõe o proxy do AdsPower a bloqueio. Este módulo injeta
"ruído humano" barato e reversível em cima do fluxo que já existe, SEM mudar o que ele faz:

  - `pausa()`         — espera de duração ALEATÓRIA entre passos (no lugar de esperas cravadas);
  - `scroll_leve()`   — um scroll pequeno antes de agir (o humano rola a página antes de clicar);
  - `digitar()`       — digitação em blocos curtos com micro-pausas (não "cola" o texto inteiro);
  - `descanso()`      — intervalo ALEATÓRIO entre um canal e o próximo (nunca dois perfis colados).

Tudo obedece a um INTERRUPTOR MESTRE `LONGFORM_PUB_HUMANO` (default LIGADO). Desligue (=0) p/
testes rápidos. O jitter de HORÁRIO do agendamento fica no `agenda.py` (é lá que o slot nasce).

⚠ Nada aqui torna a automação "indetectável" — só remove os tells mais grosseiros de bot. A
proteção de verdade continua sendo: 1 perfil por vez, sessão curta de upload, e o proxy do
próprio AdsPower. Ver SEGUNDO-CEREBRO/aprendizados.md.
"""

import os
import random
import time


# RNG de sessão (semente do SO no import — varia a cada rodada). Não é criptográfico; só serve
# p/ espalhar os tempos. O jitter de agenda usa um RNG DETERMINÍSTICO próprio (ver agenda.py).
_RNG = random.Random()


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _faixa(nome, default_min, default_max):
    """Lê uma faixa [lo, hi] de duas envs `<nome>_MIN` / `<nome>_MAX` (com defaults)."""
    lo = _num(os.environ.get(nome + "_MIN"), default_min)
    hi = _num(os.environ.get(nome + "_MAX"), default_max)
    return (lo, hi) if hi >= lo else (lo, lo)


def _ligado(nome, default=True):
    v = os.environ.get(nome)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "nao", "não")


def ativo():
    """Camada humana ligada? Env `LONGFORM_PUB_HUMANO` (default LIGADO)."""
    return _ligado("LONGFORM_PUB_HUMANO", True)


def pausa(page, a_ms=400, b_ms=1200):
    """Espera um tempo ALEATÓRIO em [a_ms, b_ms] ms (substitui `wait_for_timeout` cravado).
    Com a camada desligada, espera a média fixa — o fluxo continua idêntico, só sem ruído."""
    if not ativo():
        page.wait_for_timeout(int((a_ms + b_ms) / 2))
        return
    page.wait_for_timeout(int(_RNG.uniform(a_ms, b_ms)))


def scroll_leve(page):
    """Rola a página um tantinho aleatório (gesto humano antes de clicar). Best-effort."""
    if not ativo():
        return
    try:
        page.mouse.wheel(0, int(_RNG.uniform(120, 480)))
        page.wait_for_timeout(int(_RNG.uniform(300, 900)))
    except Exception:  # noqa: BLE001 — scroll é enfeite, nunca derruba o upload
        pass


def digitar(page, campo, texto):
    """Digita `texto` em `campo` com cadência humana: blocos de 3–8 chars, delay por tecla
    variável e micro-pausas entre blocos (em vez de colar o texto de uma vez). Preserva o
    comportamento antigo (`type(delay=5)`) quando a camada está desligada."""
    texto = texto or ""
    if not ativo() or not texto:
        campo.type(texto, delay=5)
        return
    i, n = 0, len(texto)
    while i < n:
        passo = int(_RNG.uniform(3, 8))
        campo.type(texto[i:i + passo], delay=int(_RNG.uniform(8, 22)))
        i += passo
        if i < n:
            page.wait_for_timeout(int(_RNG.uniform(40, 140)))


def descanso(log=lambda m: None, pular=False):
    """Descanso ALEATÓRIO (em segundos) ANTES de abrir o próximo canal/perfil — nunca dois
    perfis AdsPower colados. Faixa por env `LONGFORM_PUB_DESCANSO_MIN/_MAX` (default 40–150 s).
    `pular=True` (ex.: --dry-run) não descansa, p/ os testes ficarem rápidos."""
    if not ativo() or pular:
        return
    lo, hi = _faixa("LONGFORM_PUB_DESCANSO", 40, 150)
    s = _RNG.uniform(lo, hi)
    log("    ⏳ descanso humano de ~%ds antes do próximo canal…" % int(s))
    time.sleep(s)
