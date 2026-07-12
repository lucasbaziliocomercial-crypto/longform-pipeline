# -*- coding: utf-8 -*-
"""esteira.py — roda a esteira INTEIRA de uma categoria em lote (todos os cards não-concluídos).

É o "one-click da linha de produção": você escolhe SÓ a categoria (= 1 List do ClickUp / 1 canal)
e este runner:
  1. lista TODOS os cards não-concluídos daquela List (clickup_api.listar_videos);
  2. roda o `pipeline()` completo (Etapas 1→9) em CADA card, um por vez, em modo automático;
  3. (opcional) no FIM, publica a fila inteira no YouTube via AdsPower (publicador.drenar).

Cada card é idempotente e independente: um que falhar NÃO derruba a esteira — a gente loga e segue
pro próximo. Ao concluir a Etapa 8 de um card, o pipeline já marca o card como concluído no ClickUp
(sai da lista), então rodar a esteira de novo retoma só o que faltou.

IMPORTANTE — publicação: a Etapa 9 de cada card só ENFILEIRA (publicacao/fila/<slug>.json). Subir de
verdade abre o perfil do canal no AdsPower + Playwright (UI frágil). Por isso a publicação em lote é
um passo À PARTE, ligado por `--publicar` (CLI) ou pela checkbox na GUI — nunca dispara sozinho sem
você pedir (os perfis do AdsPower são compartilhados/ao vivo pela equipe).

Uso CLI:
    py -3 esteira.py --todas                             # GERAR TUDO: todas as categorias, uma após a outra
    py -3 esteira.py --categoria mafia-2                 # gera todos os vídeos da categoria (sem gates)
    py -3 esteira.py --categoria selena --publicar       # gera todos e, no fim, publica a fila
    py -3 esteira.py --categoria mafia --limite 3        # só os 3 primeiros cards da lista
    py -3 esteira.py --categoria selena --com-gates      # mantém os gates (para em cada card)
    py -3 esteira.py --categoria selena --roteiro-pronto # usa o Doc linkado em cada card (pula Etapa 2)
    py -3 esteira.py --todas --limite 2                  # todas as categorias, no máx. 2 cards por categoria
"""

import argparse
import sys
import time

import config  # noqa: F401  (efeito colateral: liga TTS/Magnific/ClickUp via os.environ)
import categorias
import clickup_api
import pipeline as pl
import publicador
from common import ErroPipeline, forcar_utf8_console, slugify


def rodar_esteira(categoria, log=print, cancel=None, *, pular_gates=True,
                  publicar_no_fim=False, publicar_sem_gates=True, limite=None,
                  voz=None, roteiro_pronto=False, on_proj=None):
    """Roda a esteira inteira de uma categoria. Devolve um dict-resumo com os totais.

    - categoria: chave/label/alias da categoria (ex.: "mafia-2", "Selena"). Restringe a fonte
      de cards à List dela.
    - pular_gates: True (default) = 100% automático (sem os 3 gates). False = para em cada gate.
    - publicar_no_fim: True = após gerar TODOS, drena a fila no YouTube via AdsPower.
    - publicar_sem_gates: passa adiante o Gate 3 (revisar título/desc) ao publicar.
    - limite: processa no máximo N cards (None = todos).
    - on_proj: callback(proj) por card resolvido (a GUI usa p/ saber o slug atual).
    """
    t0 = time.time()
    cat = categorias.aplicar(categoria)
    lista = categorias.nome_lista_de(cat)
    log("═" * 64)
    log("🏭 ESTEIRA — categoria: %s  (List do ClickUp: %s)" % (categorias.label_de(cat), lista))
    log("   Canal do YouTube: %s" % categorias.canal_de(cat))
    log("═" * 64)

    # Lista TODOS os cards não-concluídos da List da categoria (mesma fonte do dropdown da GUI).
    log("▶ Buscando os cards da esteira no ClickUp…")
    try:
        vids = clickup_api.listar_videos(log=log, cancel=cancel)
    except ErroPipeline as e:
        log("❌ Não consegui listar os cards da categoria: %s" % e)
        raise

    if not vids:
        log("✓ Nenhum card pendente nesta categoria — a esteira já está vazia (tudo concluído). ✅")
        return {"categoria": cat, "total": 0, "ok": 0, "falhas": 0, "cards": []}

    if limite is not None and limite > 0:
        if len(vids) > limite:
            log("   (limite: processando só os %d primeiros de %d cards)" % (limite, len(vids)))
        vids = vids[:limite]

    log("📋 %d card(s) na esteira:" % len(vids))
    for i, v in enumerate(vids, 1):
        log("   %2d. %s" % (i, v["name"]))
    log("")

    resultados = []
    ok = falhas = 0
    for i, v in enumerate(vids, 1):
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            log("■ Cancelado — parando a esteira (os cards restantes ficam pendentes).")
            break
        nome = v["name"]
        card_id = v.get("id")
        log("─" * 64)
        log("🎬 [%d/%d] %s" % (i, len(vids), nome))
        log("─" * 64)
        try:
            proj = pl.pipeline(
                nome, pl.TODAS, log, cancel,
                card_query=nome, card_id=card_id, categoria=cat,
                pular_gates=pular_gates, voz=voz, roteiro_pronto=roteiro_pronto,
                on_proj=on_proj,
            )
            ok += 1
            resultados.append({"card": nome, "slug": getattr(proj, "dir", None) and proj.dir.name,
                               "status": "ok"})
            log("✅ [%d/%d] %s — concluído." % (i, len(vids), nome))
        except ErroPipeline as e:
            falhas += 1
            resultados.append({"card": nome, "slug": slugify(nome), "status": "erro", "erro": str(e)})
            log("❌ [%d/%d] %s FALHOU: %s" % (i, len(vids), nome, e))
            log("   (a esteira segue para o próximo card — este fica pendente no ClickUp.)")
        except Exception as e:  # noqa: BLE001
            falhas += 1
            resultados.append({"card": nome, "slug": slugify(nome), "status": "erro", "erro": str(e)})
            log("❌ [%d/%d] %s ERRO INESPERADO: %s" % (i, len(vids), nome, e))
            log("   (a esteira segue para o próximo card.)")

    dt = time.time() - t0
    log("═" * 64)
    log("🏁 ESTEIRA concluída: %d ok · %d falha(s) · %d de %d card(s) · %.1f min"
        % (ok, falhas, ok + falhas, len(vids), dt / 60.0))
    log("═" * 64)

    # Publicação em lote (opcional) — só depois de gerar TUDO ("gerar tudo, publicar a fila no fim").
    if publicar_no_fim and ok and not (cancel is not None and getattr(cancel, "is_set", lambda: False)()):
        log("")
        log("⬆ Publicando a fila no YouTube (via AdsPower)…")
        log("   ⚠ Isto ABRE o perfil do canal no AdsPower (perfil ao vivo da equipe).")
        try:
            publicados = publicador.drenar(no_gates=publicar_sem_gates, log=log, cancel=cancel)
            log("⬆ Publicação em lote: %d vídeo(s) subido(s)/agendado(s)." % publicados)
        except Exception as e:  # noqa: BLE001
            log("⚠ Publicação em lote falhou (os vídeos continuam na fila; rode 'Publicar fila' à mão): %s" % e)
    elif publicar_no_fim and not ok:
        log("⬆ Publicação pulada — nenhum vídeo novo foi gerado com sucesso.")

    return {"categoria": cat, "total": len(vids), "ok": ok, "falhas": falhas, "cards": resultados}


def rodar_todas(log=print, cancel=None, *, pular_gates=True, publicar_no_fim=False,
                publicar_sem_gates=True, limite_por_categoria=None, voz=None,
                roteiro_pronto=False, on_proj=None, categorias_chaves=None):
    """META-ESTEIRA — roda a esteira de TODAS as categorias, uma após a outra (o "clique único":
    gera todos os vídeos pendentes de todos os canais e para). Devolve um dict-resumo agregado.

    - categorias_chaves: lista de chaves p/ restringir/ordenar (None = TODAS, na ordem de declaração).
    - publicar_no_fim: True = depois de gerar TUDO de TODAS as categorias, drena a fila UMA vez
      (o publicador já escolhe o canal certo por vídeo). Default False — o usuário publica depois.
    - Demais parâmetros: iguais aos de `rodar_esteira`, repassados a cada categoria.

    Uma categoria que falhar (ou ficar vazia) NÃO derruba as outras — loga e segue pra próxima.
    Respeita `cancel` ENTRE categorias e dentro de cada uma (a `rodar_esteira` já checa por card).
    """
    t0 = time.time()
    chaves = categorias_chaves or [k for k, _ in categorias.labels()]
    log("█" * 64)
    log("🏭🏭 GERAR TUDO — %d categoria(s): %s"
        % (len(chaves), ", ".join(categorias.label_de(k) for k in chaves)))
    log("   Modo: %s · publicar no fim: %s"
        % ("automático (sem gates)" if pular_gates else "com gates", "sim" if publicar_no_fim else "não"))
    log("█" * 64)

    por_categoria = []
    tot = tot_ok = tot_falhas = 0
    for idx, chave in enumerate(chaves, 1):
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            log("■ Cancelado — parando o 'Gerar TUDO' (as categorias restantes ficam pendentes).")
            break
        log("")
        log("╔" + "═" * 62 + "╗")
        log("║ CATEGORIA %d/%d: %-45s ║" % (idx, len(chaves), categorias.label_de(chave)))
        log("╚" + "═" * 62 + "╝")
        try:
            # Cada categoria NÃO publica no fim (publicar_no_fim=False): a publicação, se pedida,
            # é uma passada única no final de TUDO (a fila é global e o publicador acha o canal).
            res = rodar_esteira(
                chave, log=log, cancel=cancel,
                pular_gates=pular_gates, publicar_no_fim=False,
                limite=limite_por_categoria, voz=voz, roteiro_pronto=roteiro_pronto,
                on_proj=on_proj,
            )
        except Exception as e:  # noqa: BLE001
            # rodar_esteira já loga por card; aqui só protegemos a varredura das outras categorias.
            log("❌ Categoria %s falhou por inteiro: %s" % (categorias.label_de(chave), e))
            log("   (o 'Gerar TUDO' segue para a próxima categoria.)")
            por_categoria.append({"categoria": chave, "total": 0, "ok": 0, "falhas": 0, "erro": str(e)})
            continue
        por_categoria.append(res)
        tot += res.get("total", 0)
        tot_ok += res.get("ok", 0)
        tot_falhas += res.get("falhas", 0)

    dt = time.time() - t0
    log("")
    log("█" * 64)
    log("🏁🏁 GERAR TUDO concluído: %d ok · %d falha(s) · %d card(s) em %d categoria(s) · %.1f min"
        % (tot_ok, tot_falhas, tot, len(por_categoria), dt / 60.0))
    for r in por_categoria:
        log("   • %-18s %d ok · %d falha(s) · %d total%s"
            % (categorias.label_de(r["categoria"]), r.get("ok", 0), r.get("falhas", 0),
               r.get("total", 0), (" — %s" % r["erro"]) if r.get("erro") else ""))
    log("█" * 64)

    # Publicação em lote (opcional) — UMA passada no fim de TUDO (a fila é global).
    if publicar_no_fim and tot_ok and not (cancel is not None and getattr(cancel, "is_set", lambda: False)()):
        log("")
        log("⬆ Publicando a fila no YouTube (via AdsPower) — todos os canais…")
        log("   ⚠ Isto ABRE os perfis dos canais no AdsPower (perfis ao vivo da equipe).")
        try:
            publicados = publicador.drenar(no_gates=publicar_sem_gates, log=log, cancel=cancel)
            log("⬆ Publicação em lote: %d vídeo(s) subido(s)/agendado(s)." % publicados)
        except Exception as e:  # noqa: BLE001
            log("⚠ Publicação em lote falhou (os vídeos continuam na fila; rode 'Publicar fila' à mão): %s" % e)
    elif publicar_no_fim and not tot_ok:
        log("⬆ Publicação pulada — nenhum vídeo novo foi gerado com sucesso.")

    return {"total": tot, "ok": tot_ok, "falhas": tot_falhas, "categorias": por_categoria}


def main():
    forcar_utf8_console()
    ap = argparse.ArgumentParser(
        description="Roda a esteira de UMA categoria — ou de TODAS (--todas), o 'Gerar TUDO'.")
    ap.add_argument("--categoria", default=None,
                    help="categoria/canal (ex.: selena, mafia, selena-2, mafia-2/3/4)")
    ap.add_argument("--todas", action="store_true",
                    help="ignora --categoria e gera TODAS as categorias, uma após a outra (clique único)")
    ap.add_argument("--publicar", action="store_true",
                    help="ao terminar, publica a fila no YouTube via AdsPower")
    ap.add_argument("--com-gates", action="store_true",
                    help="mantém os 3 gates (para em cada card); sem isto é 100%% automático")
    ap.add_argument("--limite", type=int, default=None, help="processa no máximo N cards")
    ap.add_argument("--roteiro-pronto", action="store_true",
                    help="usa o roteiro do Doc linkado em cada card (pula a geração)")
    ap.add_argument("--pt", action="store_true", help="MODO TESTE: roteiro/narração/legenda em pt-BR")
    args = ap.parse_args()

    if args.pt:
        import os
        os.environ["LONGFORM_IDIOMA"] = "pt"

    try:
        if args.todas:
            res = rodar_todas(
                log=print, cancel=None,
                pular_gates=not args.com_gates,
                publicar_no_fim=args.publicar,
                limite_por_categoria=args.limite,
                roteiro_pronto=args.roteiro_pronto,
            )
        else:
            if not args.categoria:
                ap.error("informe --categoria <nome> ou use --todas para gerar todas.")
            res = rodar_esteira(
                args.categoria, log=print, cancel=None,
                pular_gates=not args.com_gates,
                publicar_no_fim=args.publicar,
                limite=args.limite,
                roteiro_pronto=args.roteiro_pronto,
            )
    except ErroPipeline as e:
        print("\n❌ %s" % e)
        sys.exit(1)
    # Código de saída != 0 se algum card falhou (útil p/ automação/agendamento).
    sys.exit(1 if res.get("falhas") else 0)


if __name__ == "__main__":
    main()
