# -*- coding: utf-8 -*-
"""Etapa 9 — Publicação (metadados + compressão + fila).

Fecha a esteira: a partir do roteiro, gera os METADADOS do YouTube (título/descrição/tags/
hashtags via skill `longform-publicacao` → publicacao.json), COMPRIME o vídeo p/ subir mais
rápido (compressor.py → out/final_upload.mp4, condicional) e ENFILEIRA o vídeo p/ publicação
(publicacao/fila/<slug>.json). Esta etapa NÃO abre browser nem sobe nada — é barata e
idempotente. Quem sobe/agenda de fato é o `publicador.py` (worker à parte, com o Gate 3),
que drena a fila. Assim todo vídeo produzido cai na fila automaticamente ("pré-selecionado"),
e você roda o publicador quando quiser subir o lote.
"""

import json
import time

import categorias
from common import ErroPipeline, FILA_DIR
from runner import rodar_claude, montar_prompt, MODELO_PUBLICACAO
import compressor
import entrega  # p/ o nome amigável (nome do card) do vídeo
import publicacao_doc  # gera o PDF de publicação (nome do card) na pasta do projeto


def _ler_source(proj):
    if not proj.existe(proj.source):
        return {}
    try:
        return json.loads(proj.source.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _gerar_metadados(proj, log, cancel):
    """Roda a skill de publicação → publicacao.json. Idempotente (pula se já existe)."""
    if proj.existe(proj.publicacao_json):
        log("    publicacao.json já existe — geração de metadados pulada.")
        return
    if not proj.existe(proj.roteiro):
        raise ErroPipeline("Etapa 9: falta roteiro.txt p/ gerar os metadados de publicação.")
    src = _ler_source(proj)
    titulo = (src.get("titulo") or src.get("card_nome") or "").strip()
    canal = categorias.canal_de(src.get("categoria"))
    extra = (
        "Gere os METADADOS de publicação do YouTube deste vídeo long-form.\n"
        + ("TÍTULO/tema do card (contexto): %s\n" % titulo if titulo else "")
        + "CANAL do YouTube: %s (categoria: %s).\n" % (canal, categorias.resolver(src.get("categoria")))
        + "Leia o roteiro.txt desta pasta e grave `publicacao.json` (+ `publicacao.txt` legível) "
          "com title/description/tags/hashtags em INGLÊS, respeitando os limites do YouTube."
    )
    log("▶ Etapa 9 — metadados de publicação (%s)…" % MODELO_PUBLICACAO)
    # WebSearch/WebFetch: a skill EXIGE busca no YouTube antes de gerar (comando do usuário).
    rodar_claude(montar_prompt("longform-publicacao", extra),
                 proj.dir, log, cancel, modelo=MODELO_PUBLICACAO,
                 allowed_tools="Read Edit Write WebSearch WebFetch")
    if not proj.existe(proj.publicacao_json):
        raise ErroPipeline("Etapa 9 não gerou publicacao.json.")


def _validar_metadados(proj, log):
    """Lê publicacao.json, valida estrutura + limites do YouTube (só AVISA, não trunca)."""
    try:
        d = json.loads(proj.publicacao_json.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ErroPipeline("publicacao.json inválido (%s) — refaça a Etapa 9." % e)
    faltando = [k for k in ("title", "description", "tags", "hashtags") if k not in d]
    if faltando:
        raise ErroPipeline("publicacao.json sem as chaves: %s." % ", ".join(faltando))
    titulo = (d.get("title") or "").strip()
    desc = d.get("description") or ""
    tags = d.get("tags") or []
    if not titulo:
        raise ErroPipeline("publicacao.json com title vazio.")
    if len(titulo) > 100:
        log("    ⚠ título com %d chars (>100, limite do YouTube) — revise no Gate 3." % len(titulo))
    if len(desc) > 5000:
        log("    ⚠ descrição com %d chars (>5000) — revise no Gate 3." % len(desc))
    soma_tags = sum(len(t) for t in tags)
    if soma_tags > 500:
        log("    ⚠ tags somam %d chars (>500) — o YouTube corta o excedente." % soma_tags)
    # Comando do usuário: EXATAMENTE 10 tags e 3 hashtags (só avisa, não trunca).
    if len(tags) != 10:
        log("    ⚠ %d tags (o padrão do comando é 10) — revise no Gate 3." % len(tags))
    n_hash = len(d.get("hashtags") or [])
    if n_hash != 3:
        log("    ⚠ %d hashtags (o padrão do comando é 3) — revise no Gate 3." % n_hash)
    log("    ✓ metadados: título %d chars · descrição %d chars · %d tags · %d hashtags."
        % (len(titulo), len(desc), len(tags), n_hash))
    return d


def enfileirar(proj, log=print):
    """Escreve publicacao/fila/<slug>.json com tudo que o publicador precisa. Idempotente.

    Público de propósito: além da Etapa 9, o `watcher.py` (ponte ClickUp→fila, semi-auto) reusa
    isto p/ enfileirar um vídeo já produzido cujo card foi marcado 'pronto p/ publicar' no ClickUp.
    Exige que os metadados (publicacao.json) e o vídeo (final_upload/final.mp4) já existam."""
    src = _ler_source(proj)
    video = proj.final_upload_mp4 if proj.existe(proj.final_upload_mp4) else proj.final_mp4
    item = {
        "slug": proj.dir.name,
        "projeto": str(proj.dir),
        "categoria": categorias.resolver(src.get("categoria")),
        "canal": categorias.canal_de(src.get("categoria")),
        "card_nome": src.get("card_nome") or entrega._nome_amigavel(proj),
        "video": str(video),
        "publicacao_json": str(proj.publicacao_json),
        "thumb": str(proj.thumb_selected) if proj.existe(proj.thumb_selected) else "",
        "status": "pendente",
        "criado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    FILA_DIR.mkdir(parents=True, exist_ok=True)
    destino = FILA_DIR / ("%s.json" % proj.dir.name)
    destino.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    proj.enfileirado_flag.write_text("ok", encoding="utf-8")
    log("    🗂 enfileirado p/ publicação: %s (canal %s)." % (destino.name, item["canal"]))


def run(proj, log, cancel=None, **_):
    # Idempotente: metadados prontos E já enfileirado -> nada a fazer.
    if proj.existe(proj.publicacao_json) and proj.enfileirado_flag.exists():
        log("    Etapa 9 já concluída (metadados + fila) — pulando.")
        return
    if not proj.existe(proj.final_mp4):
        raise ErroPipeline("Etapa 9: falta out/final.mp4 (rode a Etapa 8 antes de publicar).")

    _gerar_metadados(proj, log, cancel)
    _validar_metadados(proj, log)

    # Documento de publicação (PDF com o nome do card) na pasta do projeto — fácil de abrir/copiar.
    try:
        publicacao_doc.exportar(proj, log)
    except Exception as e:  # noqa: BLE001 — o PDF é conveniência; não derruba a etapa.
        log("    ⚠ não consegui gerar o PDF de publicação (%s) — publicacao.json/txt seguem ok." % e)

    # Compressão p/ upload (condicional; hardlinka se abaixo do limiar) → final_upload.mp4
    try:
        compressor.comprimir(proj.final_mp4, proj.final_upload_mp4, log)
    except ErroPipeline as e:
        log("    ⚠ compressão falhou (%s) — a fila usará o final.mp4 original." % e)

    enfileirar(proj, log)
    log("    ✓ Etapa 9 concluída. Rode o publicador p/ subir/agendar a fila.")
