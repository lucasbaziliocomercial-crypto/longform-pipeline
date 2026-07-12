# -*- coding: utf-8 -*-
"""Etapa 6 — Fichas de personagem (Library) + thumbnail (via Magnific).

Dois passos:
  1) FICHAS: lê prompts_referencia.txt (Etapa 5), gera UMA ficha corpo-inteiro/fundo-branco
     por personagem, registra cada uma como *character* na Library do Magnific e grava
     referencias.json (mapa [Character N: NAME] -> Library id). É o lock REAL de consistência
     que a thumb e as imagens do vídeo (Etapa 7) reusam via references[].type=character.
  2) THUMB: lê prompts_thumbnail.txt (1 prompt) e gera thumbs/thumb_01.png — a CAPA única do
     vídeo — usando as fichas da Library para travar os personagens. Depois vem o Gate 2
     (painel) para VALIDAR a thumb -> thumb_selected.png, da qual a Etapa 7 deriva as imagens
     do corpo do vídeo (N_IMAGENS, hoje 6).
"""

import json
import os
import shutil

import categorias as _categorias

from common import ErroPipeline, thumbs_ref_estilo
from stages import enhance_thumb, magnific_seam, qa_thumb

# 1 variação só (2026-06-18, a pedido da usuária): as 3 variações saíam quase idênticas e
# gastavam 3× crédito (450 vs 150 em GPT-2 medium). Com N_THUMBS=1 o Gate 2 vira auto-select
# (gates.gate_thumb copia a única thumb direto, sem pedir aprovação no painel).
N_THUMBS = 1


def _tem_pngs_ficha(proj):
    """True se a pasta referencias/ já tem PNG de ficha baixado (ref_*.png) — sinal de que o
    passo de fichas rodou/registrou na Library e só faltou gravar referencias.json."""
    d = proj.referencias_dir
    return d.is_dir() and any(d.glob("ref_*.png"))


def _gerar_referencias(proj, log, cancel):
    """Passo 1 — fichas -> Library -> referencias.json. Idempotente via referencias.json."""
    if not proj.existe(proj.prompts_referencia):
        log("    Sem prompts_referencia.txt — pulando fichas/Library (thumbs irão só por prompt).")
        return
    if proj.existe(proj.referencias_json):
        log("    referencias.json já existe — fichas/Library já registradas, passo pulado.")
        return

    # Trava de crédito: as fichas usam LONGFORM_MAGNIFIC_MODE (modelo que COBRA crédito).
    # Só gera se o corpo estiver explicitamente liberado (LONGFORM_MAGNIFIC_CORPO_OK=1).
    magnific_seam.garantir_corpo_liberado()

    n_linhas = sum(
        1 for l in proj.prompts_referencia.read_text(encoding="utf-8").splitlines()
        if l.strip().startswith("[Character")
    ) or 1
    instr = (
        "Você é a Etapa 6 (fichas de personagem) de uma esteira de vídeo. Leia "
        "`prompts_referencia.txt` (uma linha por personagem, começa com [Character N: NAME]). "
        "NÃO peça confirmação.\n\n%s"
        % magnific_seam.receita_referencia(
            n_linhas, "referencias/ref_NN_<name>.png (NN = índice 01.. do personagem)")
    )
    log("    Gerando %d ficha(s) + registrando na Library do Magnific (%s)..."
        % (n_linhas, magnific_seam.modo()))
    magnific_seam.gerar(proj, log, cancel, instr, modelo="sonnet")

    # AUTO-CURA: o agente às vezes conclui as fichas (PNG em referencias/ + library_create feito)
    # mas ESQUECE de gravar referencias.json. As fichas e o crédito já foram — regenerar seria
    # desperdício. Se há PNG de ficha na pasta, tenta reconstruir o mapa só lendo a Library
    # (não gera imagem, não gasta crédito) antes de falhar.
    if not proj.existe(proj.referencias_json) and _tem_pngs_ficha(proj):
        log("    ⚠ referencias.json não foi gravado, mas há fichas em referencias/ — "
            "reconstruindo o mapa a partir da Library (sem gerar/gastar crédito)...")
        magnific_seam.gerar(proj, log, cancel,
                            magnific_seam.instr_reconstruir_referencias(), modelo="sonnet")

    if not proj.existe(proj.referencias_json):
        raise ErroPipeline(
            "Etapa 6 não gerou referencias.json (fichas/Library). Verifique o MCP do Magnific."
        )
    log("    ✓ Fichas registradas na Library (referencias.json).")


def _qa_retries():
    """Quantos retries de QA além da 1ª geração (default 1). Env LONGFORM_THUMB_QA_RETRY."""
    try:
        return max(0, int(os.environ.get("LONGFORM_THUMB_QA_RETRY", "1")))
    except ValueError:
        return 1


def _qa_aprovada(proj):
    """True se o QA aprovou (ou se não há veredito = QA off/erro → não bloqueia)."""
    if not proj.existe(proj.thumb_qa):
        return True
    try:
        return bool(json.loads(proj.thumb_qa.read_text(encoding="utf-8")).get("approved"))
    except Exception:  # noqa: BLE001
        return True


def _gerar_capa_escalonada(proj, log, cancel, lock, estilo, quality, sugestoes=""):
    """Gera a CAPA com o fluxo determinístico (Python sequencia + checa o artefato):
    A) GPT 2 cheio → se sair, pronto. B) moderou → base leve no GPT 2. C) refino editando no
    Nano Banana 2 (NUNCA cold). Devolve a origem (string) ou levanta ErroPipeline."""
    thumb = proj.thumbs_dir / "thumb_01.png"
    # zera artefatos parciais desta tentativa
    for p in (thumb, proj.thumb_base_gpt2, proj.thumb_status):
        try:
            p.unlink()
        except OSError:
            pass

    mode = magnific_seam.thumb_modo()  # default gpt-2 (override por LONGFORM_MAGNIFIC_THUMB_MODE)
    cat = _categorias.atual()          # categoria ativa: adapta direção de arte e QA

    # PASSO A — GPT 2 cheio (a partir de prompts_thumbnail.txt)
    log("    [A] gerando a capa no GPT 2 (cena cheia)...")
    magnific_seam.gerar(proj, log, cancel, magnific_seam.instr_thumb_principal(
        mode, lock, estilo, "thumbs/thumb_01.png", "thumbs/thumb_status.json", quality,
        sugestoes, categoria=cat),
        modelo="sonnet")
    if proj.existe(thumb):
        enhance_thumb.enhance_if_dark(thumb, log)
        return "GPT 2"

    # moderou → PASSO B — base leve, AINDA no GPT 2 (regra: nunca cold no Nano)
    log("    [B] GPT 2 moderou — aliviando o prompt e gerando a BASE no GPT 2...")
    magnific_seam.gerar(proj, log, cancel, magnific_seam.instr_thumb_base_leve(
        mode, lock, estilo, "thumbs/_base_gpt2.png", "thumbs/thumb_status.json",
        sugestoes, categoria=cat),
        modelo="sonnet")
    if not proj.existe(proj.thumb_base_gpt2):
        raise ErroPipeline(
            "Etapa 6: nem a base leve passou no GPT 2. Alivie mais o prompts_thumbnail.txt "
            "(tire decote/pose dominante/palavras-gatilho) e rode a etapa de novo.")

    # PASSO C — refino editando a base no Nano Banana 2
    refino = magnific_seam.thumb_modo_refino()
    if not refino:
        shutil.copyfile(proj.thumb_base_gpt2, thumb)
        enhance_thumb.enhance_if_dark(thumb, log)
        log("    [C] refino DESLIGADO (LONGFORM_MAGNIFIC_THUMB_REFINE_MODE vazio) — "
            "usando a base do GPT 2 como capa.")
        return "GPT 2 (base leve, sem refino)"
    log("    [C] refinando a base no Nano Banana 2 (edição — mantém luz/personagens)...")
    magnific_seam.gerar(proj, log, cancel, magnific_seam.instr_thumb_refino(
        "thumbs/_base_gpt2.png", "thumbs/thumb_01.png", "thumbs/thumb_status.json", refino),
        modelo="sonnet")
    if proj.existe(thumb):
        enhance_thumb.enhance_if_dark(thumb, log)
        return "GPT 2 base + refino Nano Banana 2"
    raise ErroPipeline(
        "Etapa 6: o refino no Nano Banana 2 não produziu thumbs/thumb_01.png (veja o log do MCP).")


def run(proj, log, cancel=None, n_thumbs=N_THUMBS, **_):
    if not proj.existe(proj.prompts_thumb):
        raise ErroPipeline("Falta prompts_thumbnail.txt (Etapa 5) para gerar a thumb.")

    # Passo 1 — fichas de referência -> Library (lock real)
    _gerar_referencias(proj, log, cancel)

    # Passo 2 — a CAPA (única). Idempotente: se já existe, pula.
    thumb = proj.thumbs_dir / "thumb_01.png"
    if proj.existe(thumb):
        log("    thumb_01.png já existe — geração da capa pulada (idempotente).")
        return

    lock = magnific_seam.instr_char_lock() if proj.existe(proj.referencias_json) else ""
    refs_estilo = thumbs_ref_estilo()
    estilo = magnific_seam.instr_refs_estilo([str(p) for p in refs_estilo])
    quality = magnific_seam.thumb_qualidade()
    if refs_estilo:
        log("    Usando %d thumb(s) de referência de estilo do canal (base da capa)."
            % len(refs_estilo))

    # Loop de QA: gera → Claude(Opus) avalia → se reprovar, 1+ retry com as sugestões embutidas.
    retries = _qa_retries()
    sugestoes = ""
    origem = "?"
    for tent in range(1, retries + 2):
        log("▶ Etapa 6/8 — Gerando a capa (GPT 2 q=%s%s%s)%s..."
            % (quality, ", lock de personagem" if lock else "",
               ", refs de estilo" if refs_estilo else "",
               "" if tent == 1 else " — RETRY %d com ajustes do QA" % (tent - 1)))
        origem = _gerar_capa_escalonada(proj, log, cancel, lock, estilo, quality, sugestoes)
        qa = qa_thumb.avaliar(proj, log, cancel)
        if qa is None or qa.get("approved"):
            break
        if tent <= retries:
            sugestoes = ("; ".join(qa.get("suggestions", []) or [])
                         or "; ".join(qa.get("issues", []) or []))
            log("    ♻ Regenerando a capa com os ajustes do QA: %s" % (sugestoes or "(sem detalhe)"))
            for p in (thumb, proj.thumb_base_gpt2):
                try:
                    p.unlink()
                except OSError:
                    pass
        else:
            log("    ⚠ QA ainda reprovou após %d retry — a capa irá pro Gate 2 HUMANO "
                "(sem auto-confirmar em silêncio)." % retries)

    geradas = sorted(proj.thumbs_dir.glob("thumb_*.png"))
    if not geradas:
        raise ErroPipeline("Etapa 6 não gerou nenhuma capa em thumbs/.")
    proximo = ("Gate 2 (auto-confirma — QA aprovou)" if _qa_aprovada(proj)
               else "Gate 2 (validação HUMANA — QA sinalizou a capa)")
    log("    ✓ Capa pronta (%s). Próximo: %s." % (origem, proximo))
