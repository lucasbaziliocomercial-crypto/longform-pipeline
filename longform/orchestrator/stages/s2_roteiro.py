# -*- coding: utf-8 -*-
"""Etapa 2 — Geração de roteiro (~5.000 palavras / ~35 min).

Usa a skill `longform-roteiro` (que carrega o PROMPT MESTRE do usuário). Como uma
única passada costuma cair abaixo do alvo, o orquestrador controla um loop de
expansão: gera, conta palavras e, se ficar curto, manda crescer as cenas fracas
IN PLACE até bater o alvo (sem inflar com enchimento).
"""

import json
import os

import categorias
from common import ErroPipeline, contar_palavras, idioma, nome_idioma
from runner import (rodar_claude, montar_prompt, skill_slot_vazio,
                    MODELO_ROTEIRO, EFFORT_ROTEIRO)

# Modelo da TRADUÇÃO do roteiro-pronto (PT<->EN). Sonnet = bom equilíbrio qualidade/velocidade
# pra traduzir ~5.000 palavras de forma natural. Override por env.
MODELO_TRADUZIR = os.environ.get("LONGFORM_MODELO_TRADUZIR", "sonnet").strip() or "sonnet"
# Caracteres típicos do português que praticamente não aparecem em inglês — base da detecção.
_PT_CHARS = "ãõçáéíóúâêôàü"

# Alvo de tamanho do roteiro, configurável por env LONGFORM_ALVO_PALAVRAS (default 5000 = ~40 min
# na voz natural da Joanne). Baixe (ex.: 3200 ≈ ~25 min) p/ vídeos mais curtos SEM acelerar a fala —
# o TAMANHO do roteiro é o que controla a duração em ritmo natural. A skill recebe o alvo via
# _ctx_base e mira ele na 1ª passada. MIN/MAX = faixa ±~6% (MIN é o piso do loop de expansão).
try:
    ALVO_PALAVRAS = max(500, int(os.environ.get("LONGFORM_ALVO_PALAVRAS", "5000")))
except (TypeError, ValueError):
    ALVO_PALAVRAS = 5000
MIN_PALAVRAS = int(round(ALVO_PALAVRAS * 0.94))
MAX_PALAVRAS = int(round(ALVO_PALAVRAS * 1.06))
MAX_EXPANSOES = 1   # era 2. Cada expansão é um claude -p Opus completo (~6-9 min); a usuária
                    # priorizou velocidade. O _ctx_base agora exige acertar o tamanho NA 1ª passada,
                    # então 1 expansão é rede de segurança. Suba se o roteiro sair curto com frequência.


def _instr_idioma():
    """Linha de IDIOMA do roteiro. PT é o MODO TESTE (equipe avalia a história);
    EN é a conversão original do canal."""
    if idioma() == "pt":
        return (
            "IDIOMA: escreva a história em PORTUGUÊS (pt-BR coloquial e natural) — a narração "
            "é em português. MODO TESTE: este vídeo é pra equipe AVALIAR A HISTÓRIA, então "
            "priorize clareza, fluência e naturalidade em pt-BR (sem soar traduzido do inglês). "
        )
    return (
        "IDIOMA: escreva a história em INGLÊS (American English) — a narração é em inglês. "
    )


def _ctx_base(proj, alvo):
    src = json.loads(proj.source.read_text(encoding="utf-8"))
    return (
        "FONTE (Etapa 1 — ClickUp), use como base da história:\n"
        "TÍTULO: %s\n"
        "PREMISSA:\n%s\n\n"
        "%s"
        "ALVO DE TAMANHO: ~%d palavras (faixa %d–%d), narração contínua de ~35 min, "
        "formato YouTube long-form 16:9. CRÍTICO: entregue o roteiro JÁ NO TAMANHO-ALVO na "
        "PRIMEIRA passada (não devolva curto contando com expansão depois) — escreva todas as "
        "cenas com profundidade de diálogo e detalhe sensorial suficientes para fechar a faixa. "
        "SALVE o roteiro final como `roteiro.txt` "
        "(texto puro, sem markdown, sem cabeçalhos de cena no meio da prosa narrada)."
        % (src.get("titulo", ""), src.get("premissa", ""), _instr_idioma(),
           alvo, MIN_PALAVRAS, MAX_PALAVRAS)
    )


# Preâmbulo headless MÍNIMO para a expansão — de propósito NÃO carrega a skill de geração
# (~5.600–7.000 tok em Opus): expandir é aprofundar cenas do roteiro que JÁ existe (o modelo lê
# roteiro.txt, que já carrega o estilo), não reestabelecer o formato. Economia direta no tier caro.
_PREAMBULO_EXPANSAO = (
    "MODO AUTOMÁTICO (headless) — sem humano no chat. A PASTA DE TRABALHO é o diretório atual (.). "
    "NÃO faça perguntas, NÃO pause. Edite/salve o arquivo pedido com Write/Edit.\n\n"
)


def _ctx_expandir(faltam, palavras_atual, alvo):
    """Prompt AUTOCONTIDO da expansão (sem a skill de geração — só as regras de aprofundar)."""
    return (
        _PREAMBULO_EXPANSAO +
        "Tarefa: EXPANDIR o roteiro long-form que já está em `roteiro.txt` (romance, narração em "
        "1ª pessoa da heroína). Ele está CURTO: %d palavras (alvo ~%d; faltam ~%d). ABRA `roteiro.txt` "
        "com Read e EXPANDA-O editando o próprio arquivo: aprofunde as cenas mais rasas com diálogo, "
        "tensão e detalhe sensorial — SEM enchimento, sem repetir parágrafos, mantendo a continuidade, "
        "o tom e a 1ª pessoa. Não reescreva o que já está bom; só cresça o que está corrido. Salve por "
        "cima (Write/Edit), texto puro, sem markdown."
        % (palavras_atual, alvo, faltam)
    )


def run(proj, log, cancel=None, alvo=ALVO_PALAVRAS, **_):
    if proj.existe(proj.roteiro):
        n = contar_palavras(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
        log("    roteiro.txt já existe (%d palavras) — Etapa 2 pulada." % n)
        return
    if not proj.existe(proj.source):
        raise ErroPipeline("Falta source.json (Etapa 1) para gerar o roteiro.")

    from common import nome_idioma
    skill = categorias.skill_roteiro()
    if skill_slot_vazio(skill):
        log("    ⚠ A skill de roteiro da categoria (%s) está com o PROMPT MESTRE em branco "
            "('(inserir)') — preencha-a antes de gerar (o roteiro sairá genérico)." % skill)
    log("▶ Etapa 2/8 — Roteiro (~%d palavras, %s, effort=%s, idioma=%s, skill=%s)..."
        % (alvo, MODELO_ROTEIRO, EFFORT_ROTEIRO or "default", nome_idioma(), skill))
    rodar_claude(montar_prompt(skill, _ctx_base(proj, alvo)),
                 proj.dir, log, cancel, modelo=MODELO_ROTEIRO, effort=EFFORT_ROTEIRO)
    if not proj.existe(proj.roteiro):
        raise ErroPipeline("Etapa 2 não gerou roteiro.txt.")

    # Loop de expansão até o mínimo.
    for tent in range(MAX_EXPANSOES):
        n = contar_palavras(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
        if n >= MIN_PALAVRAS:
            log("    ✓ Roteiro com %d palavras (>= mínimo %d)." % (n, MIN_PALAVRAS))
            return
        faltam = alvo - n
        log("    Roteiro curto (%d/%d). Expansão %d/%d (prompt enxuto, sem reenviar a skill)..."
            % (n, alvo, tent + 1, MAX_EXPANSOES))
        rodar_claude(_ctx_expandir(faltam, n, alvo),
                     proj.dir, log, cancel, modelo=MODELO_ROTEIRO, effort=EFFORT_ROTEIRO)

    n = contar_palavras(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
    if n < MIN_PALAVRAS:
        log("    ⚠ Roteiro com %d palavras após %d expansões (abaixo de %d) — seguindo; "
            "o validador pode reforçar." % (n, MAX_EXPANSOES, MIN_PALAVRAS))


def _idioma_do_texto(txt):
    """Heurística PT vs EN pela DENSIDADE de acentos típicos do português (ç, ã, õ, á, é…).
    PT é cheio de acentos (~1% dos caracteres); EN tem ~zero. Densidade funciona p/ qualquer
    tamanho de texto. Limite baixo (0,2%) DE PROPÓSITO: o erro perigoso é PT passar por EN (não
    traduzir → vídeo errado); um EN raro com 1 acento solto fica bem abaixo do limite."""
    baixo = txt.lower()
    if not baixo.strip():
        return "en"
    marcas = sum(baixo.count(c) for c in _PT_CHARS)
    return "pt" if (marcas / len(baixo)) > 0.002 else "en"


def _prompt_traduzir(alvo):
    destino = ("American English (coloquial e natural, como uma narração de YouTube)"
               if alvo == "en" else "português do Brasil (pt-BR coloquial e natural)")
    return (
        "Você é um TRADUTOR de roteiros de narração long-form (canal de romance/Alpha King no "
        "YouTube). O arquivo `roteiro.txt` na pasta de trabalho tem o roteiro COMPLETO. Traduza-o "
        "para %s e salve POR CIMA do `roteiro.txt` (texto puro, sem markdown). REGRAS:\n"
        "- Preserve a HISTÓRIA inteira e TODAS as cenas, na mesma ordem.\n"
        "- Mantenha ~o MESMO tamanho (NÃO resuma, NÃO corte) — é narração de ~35 min.\n"
        "- Mantenha a 1ª pessoa, o tom dramático/emocional e a quebra de parágrafos.\n"
        "- Deve soar como se tivesse sido ESCRITO no idioma-alvo (sem literalidade travada).\n"
        "- NÃO faça perguntas nem comentários — só traduza e salve o arquivo." % destino
    )


def traduzir_se_preciso(proj, log, cancel=None):
    """Modo ROTEIRO PRONTO: se o roteiro.txt está num idioma DIFERENTE do alvo do vídeo
    (idioma()), traduz para o alvo preservando história/tamanho/tom. No-op (e idempotente) se já
    bate — ex.: roteiro PT + vídeo EN => traduz PT→EN antes da narração; roteiro já EN => pula."""
    if not proj.existe(proj.roteiro):
        return
    origem = _idioma_do_texto(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
    alvo = idioma()
    if origem == alvo:
        log("    Roteiro pronto já está em %s — sem tradução." % nome_idioma(alvo))
        return
    log("▶ Traduzindo o roteiro pronto de %s → %s (%s) antes da narração..."
        % (nome_idioma(origem), nome_idioma(alvo), MODELO_TRADUZIR))
    rodar_claude(_prompt_traduzir(alvo), proj.dir, log, cancel,
                 modelo=MODELO_TRADUZIR, allowed_tools="Read Write Edit")
    n = contar_palavras(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
    log("    ✓ Roteiro traduzido para %s (%d palavras)." % (nome_idioma(alvo), n))
