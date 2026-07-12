# -*- coding: utf-8 -*-
"""Etapa 3 — Validador de roteiro (revisor estrutural + corretor).

Usa a skill `longform-validar` (revisão estrutural + correção, os dois passos juntos).
A skill lista os erros ESTRUTURAIS com gravidade (grave/medio/leve), CORRIGE o roteiro.txt
in-place e grava roteiro_validacao.json. O orquestrador lê o VALID_SCORE; abaixo da meta,
reforça até MAX_REVALIDA vezes.
"""

import json

from common import ErroPipeline, nome_idioma
from runner import rodar_claude, montar_prompt, MODELO_VALIDAR

META_SCORE = 80         # nota-alvo 0–100; abaixo disso, reforça
MAX_REVALIDA = 1        # 1 passada + até 1 reforço


def _ctx(reforco=False):
    base = (
        "MODO HEADLESS: rode os DOIS passos da skill na mesma rodada sobre o `roteiro.txt` "
        "(em %s): (1) REVISÃO estrutural e (2) CORREÇÃO. Aplique as correções DIRETAMENTE no "
        "roteiro.txt (Edit/Write) — não entregue só os blocos copia-cola. Registre cada erro e "
        "a correção aplicada (original/corrigido) no `roteiro_validacao.json` e imprima na "
        "última linha EXATAMENTE: VALID_SCORE=<inteiro 0-100>. Siga a ADAPTAÇÃO LONG-FORM da "
        "skill (história única, sem Parte 1/2 nem hooks; 1ª pessoa da heroína; cena íntima "
        "elegante e não vulgar)."
    ) % nome_idioma()
    if reforco:
        base += ("\n\nESTE É UM REFORÇO: a passada anterior ficou abaixo da meta. Procure erros "
                 "estruturais remanescentes, corrija-os in-place e atualize o JSON e o VALID_SCORE.")
    return base


def _parse_score(texto):
    import re
    if not texto:
        return None
    m = re.search(r"VALID_SCORE\s*=\s*(\d{1,3})", texto, re.I)
    if not m:
        return None
    try:
        return max(0, min(100, int(m.group(1))))
    except ValueError:
        return None


def run(proj, log, cancel=None, **_):
    if not proj.existe(proj.roteiro):
        raise ErroPipeline("Falta roteiro.txt (Etapa 2) para validar.")
    if proj.existe(proj.validacao):
        log("    roteiro_validacao.json já existe — Etapa 3 pulada.")
        return _carregar(proj)

    score = None
    for tent in range(MAX_REVALIDA + 1):
        log("▶ Etapa 3/8 — Validador (nota + gravidade + auto-fix, tentativa %d/%d, %s)..."
            % (tent + 1, MAX_REVALIDA + 1, MODELO_VALIDAR))
        res = rodar_claude(montar_prompt("longform-validar", _ctx(reforco=tent > 0)),
                           proj.dir, log, cancel, modelo=MODELO_VALIDAR)
        score = _parse_score(res.get("result", ""))
        if not proj.existe(proj.validacao):
            raise ErroPipeline("Etapa 3 não gerou roteiro_validacao.json.")
        if score is None:
            log("    ⚠ VALID_SCORE não lido — entregando a validação como está.")
            break
        if score >= META_SCORE:
            log("    ✓ Validação %d/100 (>= meta %d)." % (score, META_SCORE))
            break
        if tent < MAX_REVALIDA:
            log("    ⚠ Validação %d/100 < meta %d — reforçando os trechos fracos." % (score, META_SCORE))
        else:
            log("    ⚠ Validação %d/100 ainda < meta %d — seguindo. Revise no painel." % (score, META_SCORE))

    dados = _carregar(proj)
    if dados.get("pov"):
        log("    POV: %s | história finalizada: %s" % (dados.get("pov"), dados.get("historia_finalizada")))
    graves = [i for i in dados.get("itens", []) if str(i.get("gravidade", "")).lower() in ("grave", "gravissimo", "gravíssimo")]
    if graves:
        log("    %d erro(s) estrutural(is) GRAVE(s) corrigido(s); confira no painel antes de gastar TTS/imagem." % len(graves))
    return dados


def _carregar(proj):
    try:
        return json.loads(proj.validacao.read_text(encoding="utf-8"))
    except Exception as e:
        raise ErroPipeline("roteiro_validacao.json inválido: %s" % e)
