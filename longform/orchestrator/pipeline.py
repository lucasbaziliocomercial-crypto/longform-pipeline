# -*- coding: utf-8 -*-
"""pipeline.py — encadeia as 8 etapas da esteira long-form + os 2 gates de decisão.

Ordem:
  1 ClickUp -> 2 Roteiro -> 3 Validador -> [GATE 1: aprovar roteiro]
  -> 4 Narração+SRT -> 5 Style bible/prompt thumb -> 6 Thumb (capa) -> [GATE 2: validar thumb]
  -> 7 Imagens (8, corpo do vídeo) -> 8 Montagem (Remotion) -> out/final.mp4

Cada etapa é idempotente (pula se a saída já existe). Os gates bloqueiam até o painel
devolver a decisão (decision.json); em modo --no-gates, aprovam automaticamente.

Uso CLI:
    py -3 pipeline.py "Alpha King"                 # do início ao fim (com gates no painel)
    py -3 pipeline.py --slug meu-video 4 5 6       # roda só as etapas 4,5,6 de um projeto
    py -3 pipeline.py "Alpha King" --no-gates       # tudo automático (testes)
"""

import os
import sys
import time

import config  # noqa: F401  (efeito colateral: liga TTS/Magnific via os.environ)
import categorias
from common import (ErroPipeline, PROJECTS_DIR, slugify, Projeto, projeto_por_slug,
                    achar_pasta_projeto)
from stages import (s1_clickup, s2_roteiro, s3_validar, s4_narracao_srt,
                    s5_prompts_img, s6_thumbnails, s7_imagens, s8_montagem,
                    s9_publicacao)
import gates
import runner

TODAS = (1, 2, 3, 4, 5, 6, 7, 8, 9)


def _pid_vivo(pid):
    """True se o processo `pid` ainda está rodando (cross-plataforma)."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _adquirir_lock(proj, log):
    """Trava por projeto: impede DUAS execuções no mesmo vídeo ao mesmo tempo (rodar/continuar
    o mesmo card 2x corrompe os arquivos — ex.: dois `remotion render` escrevendo o mesmo MP4).

    Grava `<projeto>/.running` com o PID. Se já existir uma trava de um processo VIVO, recusa
    com mensagem clara. Travas órfãs (processo morto) são tratadas como obsoletas e sobrescritas.
    Devolve o Path da trava (use em `finally` p/ liberar). NÃO levanta se a trava for nossa/órfã.
    """
    lock = proj.dir / ".running"
    if lock.exists():
        try:
            outro = int((lock.read_text(encoding="utf-8").split() or ["-1"])[0])
        except (ValueError, OSError):
            outro = -1
        if outro != os.getpid() and _pid_vivo(outro):
            raise ErroPipeline(
                "Já existe uma execução em andamento para este vídeo (PID %s). Aguarde ela "
                "terminar — não rode/continue o MESMO card duas vezes ao mesmo tempo (isso "
                "corrompe os arquivos). Se tiver certeza de que travou de vez, apague o arquivo "
                "'.running' na pasta do projeto e tente de novo." % outro
            )
        log("   (trava obsoleta de um run anterior encontrada — sobrescrevendo.)")
    try:
        lock.write_text("%d %d" % (os.getpid(), int(time.time())), encoding="utf-8")
    except OSError:
        pass
    return lock


def _liberar_lock(lock):
    """Remove a trava `.running` SE for nossa (PID == este processo). Nunca levanta."""
    try:
        if lock and lock.exists():
            dono = int((lock.read_text(encoding="utf-8").split() or ["-1"])[0])
            if dono == os.getpid():
                lock.unlink()
    except (ValueError, OSError):
        pass


def _garantir_projeto(alvo, log, cancel, card_query, list_hint, slug=None, card_id=None,
                      roteiro_pronto=False):
    """Resolve a Projeto. Se vier slug, usa projects/<slug>/. Senão roda a Etapa 1
    (ClickUp) numa pasta temporária pelo título e renomeia para o slug do card."""
    if slug:
        return projeto_por_slug(slug)
    # cria projeto provisório, roda Etapa 1, e renomeia pela título do card
    tmp = Projeto(PROJECTS_DIR / ("_tmp_" + slugify(card_query)))
    dados = s1_clickup.run(tmp, log, cancel, card_query=card_query, list_hint=list_hint,
                           card_id=card_id, roteiro_pronto=roteiro_pronto)
    # Slug vem do TEMA (nome do card que o usuário digita) — curto e estável p/ --slug.
    # O título real (inglês) fica em source.json["titulo"] e alimenta só o roteiro.
    novo_slug = slugify(dados.get("tema") or card_query)
    # Layout POR CANAL (2026-07-10): o projeto nasce em projects/<Canal>/<slug> conforme a
    # categoria lida do card (source.json["categoria"] — a FONTE DA VERDADE da Etapa 1).
    #
    # ATENÇÃO (2026-07-12): os slugs COLIDEM entre canais — Máfia 1/2/3/4 reusam os mesmos
    # nomes de card e o slug ainda trunca em 60 chars, então o card 16 do Máfia 2 vira o MESMO
    # slug do card 16 do Máfia 1. Por isso, quando o card tem categoria (canal conhecido), a
    # resolução é ESTRITA ao canal certo: procura SÓ em projects/<Canal>/<slug> (respeitando um
    # projeto legado no layout plano só se não houver a pasta no canal), e NUNCA cai na pasta de
    # OUTRO canal com o mesmo slug (era isso que fazia o vídeo "virar" o do canal errado).
    canal = categorias.pasta_canal(dados.get("categoria")) if dados.get("categoria") else None
    if canal:
        no_canal = PROJECTS_DIR / canal / novo_slug
        flat = PROJECTS_DIR / novo_slug
        destino = no_canal if (no_canal.is_dir() or not flat.is_dir()) else flat
    else:
        # Sem categoria conhecida (legado): descoberta cross-channel + fallback plano.
        destino = achar_pasta_projeto(novo_slug) or (PROJECTS_DIR / novo_slug)
    if destino.resolve() != tmp.dir.resolve():
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists():
            # Já existe um projeto com esse título. Antes de descartar o tmp, RESGATA os
            # artefatos da Etapa 1 (source.json / thumb_ref.png) que a pasta destino ainda
            # não tem — senão uma casca criada por uma 1ª execução interrompida nunca
            # recupera o source.json (todo run seguinte cairia aqui e o jogaria fora).
            import shutil
            destino_proj = Projeto(destino)   # pasta EXATA do canal — não reabre por slug (colide)
            for orig, alvo in ((tmp.source, destino_proj.source),
                               (tmp.thumb_ref, destino_proj.thumb_ref)):
                if orig.exists() and not destino_proj.existe(alvo):
                    shutil.copy2(orig, alvo)
                    log("   ↳ %s resgatado do ClickUp para o projeto existente." % alvo.name)
            # Roteiro pronto: o Doc é a FONTE DA VERDADE — sobrescreve o roteiro.txt do destino
            # com o que a Etapa 1 acabou de baixar (mesmo que o destino já tenha um antigo).
            if roteiro_pronto and tmp.roteiro.exists():
                shutil.copy2(tmp.roteiro, destino_proj.roteiro)
                log("   ↳ roteiro.txt (Doc do card) atualizado no projeto existente.")
            shutil.rmtree(tmp.dir, ignore_errors=True)
        else:
            tmp.dir.rename(destino)
    return Projeto(destino)


def _marcar_card_concluido(proj, log, cancel):
    """Fim da Etapa 8: marca o card do ClickUp como concluído (some do dropdown). Só roda
    se o vídeo final existe, se a auto-conclusão está ligada e se o card_id é conhecido.
    Nunca derruba a esteira — o vídeo já está pronto."""
    import json as _json
    import clickup_api
    if not proj.existe(proj.final_mp4) or not clickup_api.auto_done_ligado():
        return
    try:
        card_id = _json.loads(proj.source.read_text(encoding="utf-8")).get("card_id")
    except Exception:  # noqa: BLE001
        card_id = None
    if not card_id:
        log("   (auto-conclusão pulada: card_id desconhecido no source.json)")
        return
    try:
        log("▶ ClickUp: marcando o card como concluído (sai da lista)...")
        novo = clickup_api.marcar_concluido(card_id, log, cancel)
        log("   ✓ Card concluído no ClickUp (status: %s)." % (novo or "done"))
    except Exception as e:  # noqa: BLE001
        log("⚠ Não consegui marcar o card como concluído no ClickUp (faça à mão): %s" % e)


def _anexar_thumb_no_card(proj, log, cancel):
    """Após o Gate 2: anexa a capa APROVADA (thumb_selected.png) no card do ClickUp.
    Idempotente (flag .thumb_anexada_clickup) e nunca derruba a esteira — a capa já está
    pronta no disco. Desligável por LONGFORM_CLICKUP_ATTACH_THUMB=0."""
    import json as _json
    import clickup_api
    if not clickup_api.auto_anexar_thumb_ligado():
        return
    if not proj.existe(proj.thumb_selected) or proj.existe(proj.thumb_anexada_flag):
        return
    try:
        card_id = _json.loads(proj.source.read_text(encoding="utf-8")).get("card_id")
    except Exception:  # noqa: BLE001
        card_id = None
    if not card_id:
        log("   (anexo da capa pulado: card_id desconhecido no source.json)")
        return
    try:
        log("▶ ClickUp: anexando a capa aprovada (thumb_selected.png) no card...")
        clickup_api.anexar_arquivo(card_id, str(proj.thumb_selected), log, cancel)
        proj.thumb_anexada_flag.write_text("ok", encoding="utf-8")
        log("   ✓ Capa anexada no card do ClickUp.")
    except Exception as e:  # noqa: BLE001
        log("⚠ Não consegui anexar a capa no ClickUp (faça à mão): %s" % e)


def _exportar_roteiro(proj, log):
    """Gera roteiro.docx (+ .pdf, se possível) a partir do roteiro.txt. Nunca derruba o pipeline."""
    if not proj.existe(proj.roteiro):
        return
    try:
        import roteiro_doc
        roteiro_doc.exportar(proj.roteiro, log)
    except Exception as e:  # noqa: BLE001
        log("⚠ Não consegui exportar o roteiro p/ DOCS/PDF: %s" % e)


def pipeline(alvo=None, etapas=TODAS, log=print, cancel=None, *,
             slug=None, card_query="Alpha King", list_hint=None, card_id=None,
             categoria=None, pular_gates=False, voz=None, seg_por_imagem=None,
             on_proj=None, refazer=False, roteiro_pronto=False):
    etapas = set(etapas)
    t0 = time.time()
    runner.metricas_reset()  # zera o medidor de gasto deste run (resumo impresso no fim)

    # Categoria (= franquia/board do ClickUp): restringe a fonte de cards à List dela.
    cat = categorias.aplicar(categoria)
    log("📂 Categoria: %s (lista do ClickUp: %s)" % (categorias.label_de(cat), categorias.nome_lista_de(cat)))
    # Sem dica de List explícita, usa o NOME da List da categoria como dica da busca da Etapa 1.
    list_hint = list_hint or categorias.nome_lista_de(cat)

    proj = _garantir_projeto(alvo, log, cancel, card_query, list_hint, slug=slug, card_id=card_id,
                             roteiro_pronto=roteiro_pronto)
    # Avisa quem chamou qual projeto foi resolvido — o "Continuar" da GUI usa isso para
    # saber o slug mesmo que uma etapa adiante falhe.
    if on_proj:
        try:
            on_proj(proj)
        except Exception:  # noqa: BLE001
            pass
    log("=== Projeto: %s ===" % proj.dir)

    # Trava por projeto: recusa uma 2ª execução do MESMO vídeo enquanto a 1ª roda (rodar/continuar
    # o mesmo card 2x ao mesmo tempo corrompe os arquivos). Liberada no `finally`.
    lock = _adquirir_lock(proj, log)
    try:
        # "Refazer tudo": como cada etapa é idempotente (pula se o artefato existe), num projeto
        # já feito o "Gerar" não regenera nada. Aqui apagamos os artefatos das etapas pedidas
        # ANTES de rodar, forçando a regeneração do zero. Preserva source.json/thumb_ref.png
        # (vêm do ClickUp) — a Etapa 1 não entra na limpeza.
        if refazer:
            limpaveis = sorted(n for n in etapas if n != 1)
            apagados = proj.limpar_etapas(limpaveis)
            log("♻ Refazer tudo: %d artefato(s) apagado(s) das etapas %s — regenerando do zero."
                % (len(apagados), ", ".join(map(str, limpaveis)) or "(nenhuma)"))

        # ROTEIRO PRONTO: usa o roteiro do Doc linkado no card em vez de gerar. No "Gerar" o
        # _garantir_projeto já puxou (Etapa 1); aqui cobrimos o "Continuar" (slug dado, Etapa 1
        # pulada) — se faltar o roteiro.txt, roda a Etapa 1 só pra baixar o Doc (idempotente).
        if roteiro_pronto and not proj.existe(proj.roteiro) and proj.existe(proj.source):
            import json as _json
            _src = _json.loads(proj.source.read_text(encoding="utf-8"))
            s1_clickup.run(proj, log, cancel, card_query=_src.get("tema") or card_query,
                           card_id=_src.get("card_id"), roteiro_pronto=True)
        if roteiro_pronto and proj.existe(proj.roteiro):
            log("    📄 Roteiro pronto (Doc do card) em uso — Etapa 2 (geração) pulada.")
            # Roteiro pronto pode estar em PT e o vídeo ser EN (ou vice-versa): traduz p/ o
            # idioma-alvo ANTES da narração (no-op se já bate). Assim áudio E legenda saem certos.
            s2_roteiro.traduzir_se_preciso(proj, log, cancel)
        elif 2 in etapas:
            s2_roteiro.run(proj, log, cancel)
        if 3 in etapas: s3_validar.run(proj, log, cancel)

        # Entrega do roteiro em DOCS/PDF (regra fixa do usuário): sempre que o roteiro for
        # (re)gerado/validado. Idempotente — só regenera se roteiro.txt mudou.
        if (2 in etapas or 3 in etapas):
            _exportar_roteiro(proj, log)

        # GATE 1 — aprovar/editar roteiro
        if etapas & {4, 5, 6, 7, 8} and not pular_gates:
            gates.gate_roteiro(proj, log, cancel)
            # o usuário pode ter editado o roteiro no gate -> re-exporta (pula se inalterado)
            _exportar_roteiro(proj, log)

        if 4 in etapas: s4_narracao_srt.run(proj, log, cancel, voz=voz)
        if 5 in etapas: s5_prompts_img.run(proj, log, cancel)
        if 6 in etapas: s6_thumbnails.run(proj, log, cancel)

        # GATE 2 — escolher a thumb -> thumb_selected.png
        if etapas & {7, 8}:
            if pular_gates:
                gates.auto_escolher_thumb(proj, log)
            else:
                gates.gate_thumb(proj, log, cancel)
            # Capa aprovada -> anexa de volta no card do ClickUp (idempotente).
            _anexar_thumb_no_card(proj, log, cancel)

        if 7 in etapas:
            kw = {} if seg_por_imagem is None else {"seg_por_imagem": seg_por_imagem}
            s7_imagens.run(proj, log, cancel, **kw)
        if 8 in etapas:
            s8_montagem.run(proj, log, cancel)
            _marcar_card_concluido(proj, log, cancel)

        # Etapa 9 — Publicação: gera metadados (título/descrição/tags), comprime e ENFILEIRA o
        # vídeo p/ o publicador (que sobe/agenda no YouTube via AdsPower, à parte, com o Gate 3).
        if 9 in etapas:
            s9_publicacao.run(proj, log, cancel)

        dt = time.time() - t0
        log("")
        log("✅ Concluído. Pasta: %s" % proj.dir)
        for nome, p in (("source.json", proj.source), ("roteiro.txt", proj.roteiro),
                        ("roteiro.docx", proj.roteiro_docx), ("roteiro.pdf", proj.roteiro_pdf),
                        ("roteiro_validacao.json", proj.validacao), ("narration.mp3", proj.narration_mp3),
                        ("narration.srt", proj.narration_srt), ("style_bible.txt", proj.style_bible),
                        ("prompts_referencia.txt", proj.prompts_referencia),
                        ("prompts_thumbnail.txt", proj.prompts_thumb), ("referencias.json", proj.referencias_json),
                        ("thumb_selected.png", proj.thumb_selected),
                        ("mapping.json", proj.mapping), ("out/final.mp4", proj.final_mp4),
                        ("publicacao.json", proj.publicacao_json),
                        ("out/final_upload.mp4", proj.final_upload_mp4)):
            log("   %s %s" % ("✓" if proj.existe(p) else "·", nome))
        log("⏱ Tempo total: %.0f s (%.1f min)" % (dt, dt / 60.0))
        return proj
    finally:
        # Resumo de gasto de modelo do run (sai mesmo se uma etapa falhar/cancelar — assim você
        # vê o que já gastou antes de quebrar). Medição NUNCA derruba o run.
        try:
            for _l in runner.formatar_resumo_custo():
                log(_l)
        except Exception:  # noqa: BLE001
            pass
        _liberar_lock(lock)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = sys.argv[1:]
    if not args:
        print('uso: py -3 pipeline.py "Alpha King" [etapas...] [--no-gates] [--refazer] [--pt] '
              '[--roteiro-pronto] [--categoria selena|mafia] [--slug NOME] [--list-hint TXT]')
        return
    pular = "--no-gates" in args
    args = [a for a in args if a != "--no-gates"]
    # --refazer: apaga os artefatos das etapas pedidas antes de rodar (regenera do zero).
    refazer = "--refazer" in args
    args = [a for a in args if a != "--refazer"]
    # --roteiro-pronto: pula a geração (Etapa 2) e usa o roteiro do Doc linkado no card.
    roteiro_pronto = "--roteiro-pronto" in args
    args = [a for a in args if a != "--roteiro-pronto"]
    # --pt: MODO TESTE em português (roteiro/narração/legenda em pt-BR). Espelha a caixa
    # "Vídeo em português" da GUI. As imagens (Etapas 5/7) seguem em inglês.
    if "--pt" in args:
        import os
        os.environ["LONGFORM_IDIOMA"] = "pt"
        args = [a for a in args if a != "--pt"]
    slug = None
    list_hint = None
    categoria = None
    if "--slug" in args:
        i = args.index("--slug"); slug = args[i + 1]; del args[i:i + 2]
    if "--list-hint" in args:
        i = args.index("--list-hint"); list_hint = args[i + 1]; del args[i:i + 2]
    if "--categoria" in args:
        i = args.index("--categoria"); categoria = args[i + 1]; del args[i:i + 2]

    etapas = [int(a) for a in args if a.isdigit()]
    alvo = next((a for a in args if not a.isdigit()), "Alpha King")
    try:
        pipeline(alvo, etapas or TODAS, print, None,
                 slug=slug, card_query=alvo, list_hint=list_hint, categoria=categoria,
                 pular_gates=pular, refazer=refazer, roteiro_pronto=roteiro_pronto)
    except ErroPipeline as e:
        print("\n❌ %s" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
