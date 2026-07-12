# -*- coding: utf-8 -*-
"""watcher.py — ponte SEMI-AUTOMÁTICA ClickUp → fila de publicação.

Observa (polling) os cards marcados como PRONTOS PARA PUBLICAR no ClickUp e ENFILEIRA os
vídeos correspondentes JÁ PRODUZIDOS localmente (publicacao/fila/<slug>.json), pra que o
publicador só precise DRENAR a fila. NÃO abre o AdsPower nem publica nada — respeita a regra de
não abrir perfil sem confirmação. Ou seja: o card "pronto" no ClickUp cai sozinho na fila; a
publicação de fato (que abre o AdsPower) continua sendo você quem dispara ("Publicar fila" na
GUI ou `py -3 publicador.py`).

Como casa card ↔ projeto: pelo `card_id` gravado no source.json de cada projeto local (chave
robusta — independe do nome/slug). Se o vídeo já foi produzido (out/final_upload.mp4 ou
out/final.mp4), os metadados existem (publicacao.json) e o slug ainda não está na fila nem em
publicados, enfileira reusando `s9_publicacao.enfileirar()`.

Requer LONGFORM_CLICKUP_TOKEN (API REST) no longform.env — o watcher lê o status dos cards
(inclusive os do status-alvo, que a listagem normal ESCONDE). Config:
    LONGFORM_STATUS_PUBLICAR  status-alvo do card (default "publicar"; casa por substring)
    LONGFORM_WATCH_INTERVALO  minutos entre varreduras no modo --loop (default 10)

Uso:
    py -3 watcher.py                      # UMA varredura em TODAS as categorias e sai
    py -3 watcher.py --loop               # varre a cada LONGFORM_WATCH_INTERVALO min
    py -3 watcher.py --categoria mafia-3  # só uma categoria (canal)
"""

import argparse
import json
import os
import time

try:
    import config  # noqa: F401 — efeito colateral: carrega longform.env em os.environ
except Exception:  # noqa: BLE001
    pass

from common import (FILA_DIR, PUBLICACAO_DIR, PROJECTS_DIR, ErroPipeline,
                    forcar_utf8_console, Projeto)
import categorias
import clickup_api
from stages import s9_publicacao

PUBLICADOS_DIR = PUBLICACAO_DIR / "publicados"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _status_alvo():
    return (os.environ.get("LONGFORM_STATUS_PUBLICAR") or "publicar").strip().casefold()


def _intervalo_min():
    try:
        return max(1, int(os.environ.get("LONGFORM_WATCH_INTERVALO") or "10"))
    except ValueError:
        return 10


# ---------------------------------------------------------------------------
# ClickUp: cards no status-alvo (a listagem normal ESCONDE o status "publicar", então
# consultamos a List da categoria direto, sem o filtro de skip)
# ---------------------------------------------------------------------------

def _cards_prontos(cat):
    """Cards da List da categoria cujo status CONTÉM o status-alvo (default 'publicar')."""
    list_id = clickup_api.resolver_list_id(categorias.lista_env(cat))
    alvo = _status_alvo()
    prontos = []
    for it in clickup_api._listar_por_list(list_id):
        if alvo in (it.get("status") or "").casefold():
            prontos.append(it)
    return prontos


# ---------------------------------------------------------------------------
# Projetos locais: mapa card_id -> pasta do projeto
# ---------------------------------------------------------------------------

def _iter_projetos():
    """Itera as pastas de projeto (layout plano projects/<slug> E por canal projects/<Canal>/<slug>)."""
    if not PROJECTS_DIR.is_dir():
        return
    canais = set(categorias.pastas_canais())
    for p in PROJECTS_DIR.iterdir():
        if not p.is_dir() or p.name.startswith("_tmp_"):
            continue
        if p.name in canais:                       # pasta de canal -> desce nos projetos
            for q in p.iterdir():
                if q.is_dir() and not q.name.startswith("_tmp_"):
                    yield q
        else:                                      # projeto solto (layout legado)
            yield p


def _mapa_por_card_id():
    """{card_id (str) -> pasta do projeto} lendo o source.json de cada projeto local."""
    mapa = {}
    for d in _iter_projetos():
        src = d / "source.json"
        if not src.is_file():
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        cid = data.get("card_id")
        if cid:
            mapa[str(cid)] = d
    return mapa


def _ja_na_fila(slug):
    return (FILA_DIR / ("%s.json" % slug)).is_file() or (PUBLICADOS_DIR / ("%s.json" % slug)).is_file()


# ---------------------------------------------------------------------------
# Varredura
# ---------------------------------------------------------------------------

def varrer(cats=None, log=print):
    """Uma passada: enfileira os vídeos prontos dos cards no status-alvo. Devolve quantos novos."""
    if not clickup_api._tem_token():
        raise ErroPipeline(
            "O watcher precisa do LONGFORM_CLICKUP_TOKEN (API REST) no longform.env — é o que "
            "permite ler o status dos cards (inclusive os de 'publicar', que a listagem esconde).")
    cats = cats or [k for k, _ in categorias.labels()]
    mapa = _mapa_por_card_id()
    novos = 0
    for cat in cats:
        canal = categorias.canal_de(cat)
        try:
            prontos = _cards_prontos(cat)
        except ErroPipeline as e:
            log("  ⚠ %s: %s" % (canal, e))
            continue
        for card in prontos:
            cid = str(card.get("id"))
            pasta = mapa.get(cid)
            if pasta is None:
                log("  · '%s' (%s) marcado pronto, mas sem projeto local (card_id %s) — pulei."
                    % (card.get("name"), canal, cid))
                continue
            proj = Projeto(pasta)
            slug = proj.dir.name
            if _ja_na_fila(slug):
                continue  # já enfileirado/publicado — nada a fazer
            if not (proj.existe(proj.final_upload_mp4) or proj.existe(proj.final_mp4)):
                log("  · %s (%s) pronto no ClickUp, mas sem vídeo final local — pulei." % (slug, canal))
                continue
            if not proj.existe(proj.publicacao_json):
                log("  · %s sem publicacao.json (rode a Etapa 9 nele) — pulei." % slug)
                continue
            try:
                s9_publicacao.enfileirar(proj, log)
                novos += 1
            except Exception as e:  # noqa: BLE001
                log("  ✖ %s: falha ao enfileirar (%s)." % (slug, e))
    log("Varredura concluída: %d novo(s) enfileirado(s)." % novos)
    return novos


def _loop(cats, log):
    seg = _intervalo_min() * 60
    log("watcher em loop a cada %d min (Ctrl+C p/ sair). Status-alvo: '%s'."
        % (_intervalo_min(), _status_alvo()))
    while True:
        try:
            varrer(cats, log)
        except ErroPipeline as e:
            log("erro: %s" % e)
        except Exception as e:  # noqa: BLE001
            log("erro inesperado na varredura: %s" % e)
        time.sleep(seg)


def main():
    forcar_utf8_console()
    ap = argparse.ArgumentParser(description="Watcher ClickUp → fila de publicação (semi-auto).")
    ap.add_argument("--loop", action="store_true",
                    help="fica varrendo a cada LONGFORM_WATCH_INTERVALO min")
    ap.add_argument("--categoria", help="só esta categoria/canal (chave/label/alias)")
    args = ap.parse_args()

    cats = [categorias.resolver(args.categoria)] if args.categoria else None
    if args.loop:
        _loop(cats, print)
    else:
        varrer(cats, print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
