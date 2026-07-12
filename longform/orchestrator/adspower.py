# -*- coding: utf-8 -*-
"""adspower.py — cliente fino da Local API do AdsPower (usado pelo publicador do YouTube).

O AdsPower (navegador anti-detecção) roda um servidor HTTP LOCAL (só na versão PAGA, com a
Local API ligada). Cada CANAL do YouTube é um PERFIL do AdsPower, com fingerprint + proxy +
login próprios. Fluxo do publicador:

    start(user_id) -> devolve o endpoint CDP (ws puppeteer) do Chromium já aberto e LOGADO
    -> Playwright conecta via connect_over_cdp e automatiza o YouTube Studio
    stop(user_id)  -> fecha o perfil

Base URL por env `ADSPOWER_API` (default http://local.adspower.net:50325). A porta PODE mudar
no app do AdsPower — se mudar, ajuste a env. As chamadas são SERIALIZADAS com um respiro
(rate limit da Local API: ~1–2 req/s) p/ não tomar erro.

Doc: https://localapi-doc-en.adspower.com/
"""

import os
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    import config  # noqa: F401 — efeito colateral: carrega longform.env em os.environ
except Exception:  # noqa: BLE001 — se rodar fora do orchestrator, seguimos com o env do shell
    pass

from common import ErroPipeline, forcar_utf8_console

# Respiro entre chamadas (Local API limita a poucas req/s; algumas rotas a 1 req/s).
_MIN_INTERVALO = float(os.environ.get("ADSPOWER_MIN_INTERVALO", "0.8"))
_ultimo_call = [0.0]


def base_url():
    return os.environ.get("ADSPOWER_API", "http://local.adspower.net:50325").rstrip("/")


def _headers():
    """Header de autenticação da Local API. Quando a 'Verificação de API' está LIGADA no
    AdsPower, toda chamada exige a API Key no header `Authorization: Bearer <key>`
    (validado no disco 2026-07-09). Sem chave configurada, não manda header (verificação off)."""
    key = os.environ.get("ADSPOWER_API_KEY", "").strip()
    return {"Authorization": "Bearer %s" % key} if key else {}


def _throttle():
    """Serializa as chamadas respeitando o intervalo mínimo (usa o relógio monotônico)."""
    agora = time.monotonic()
    espera = _MIN_INTERVALO - (agora - _ultimo_call[0])
    if espera > 0:
        time.sleep(espera)
    _ultimo_call[0] = time.monotonic()


def _req(rota, params=None):
    """GET numa rota da Local API. Levanta ErroPipeline com mensagem clara se code != 0."""
    if requests is None:
        raise ErroPipeline("A lib 'requests' não está instalada (py -3 -m pip install requests) — "
                           "o publicador precisa dela p/ falar com o AdsPower.")
    _throttle()
    url = base_url() + rota
    try:
        r = requests.get(url, params=params or {}, headers=_headers(), timeout=60)
    except Exception as e:  # noqa: BLE001
        raise ErroPipeline(
            "Não consegui falar com o AdsPower em %s (%s). O AdsPower está aberto e com a "
            "Local API ligada? (versão paga). Ajuste ADSPOWER_API se a porta mudou." % (url, e))
    try:
        data = r.json()
    except ValueError:
        raise ErroPipeline("Resposta não-JSON do AdsPower (%s): %s" % (url, r.text[:200]))
    if data.get("code") != 0:
        msg = str(data.get("msg") or data)
        if "api" in msg.lower() and "key" in msg.lower():
            raise ErroPipeline(
                "AdsPower exige API Key (%s). No app: API & MCP → 'Gerar' a API Key e ou "
                "(a) desligue 'Verificação de API', ou (b) ponha a chave em ADSPOWER_API_KEY "
                "(longform.env). Detalhe: %s" % (rota, msg))
        raise ErroPipeline("AdsPower recusou %s: %s" % (rota, msg))
    return data.get("data") or {}


def start(user_id, headless=False):
    """Inicia o perfil `user_id` e devolve o endpoint CDP do Puppeteer/Playwright.

    Retorna dict: {"cdp": "ws://127.0.0.1:xxxx/devtools/browser/...",
                   "selenium": "127.0.0.1:xxxx", "debug_port": "xxxx", "webdriver": "...\\chromedriver.exe"}.
    A porta é DINÂMICA (muda a cada start) — nunca fixe."""
    if not user_id:
        raise ErroPipeline("adspower.start: user_id vazio — configure o perfil do canal "
                           "(categorias.py / env LONGFORM_ADSPOWER_<CANAL>).")
    params = {"user_id": user_id, "open_tabs": 1}
    if headless:
        params["headless"] = 1
    data = _req("/api/v1/browser/start", params)
    ws = data.get("ws") or {}
    cdp = ws.get("puppeteer")
    if not cdp:
        raise ErroPipeline("AdsPower iniciou o perfil %s mas não devolveu o endpoint CDP "
                           "(ws.puppeteer). Resposta: %s" % (user_id, data))
    return {
        "cdp": cdp,
        "selenium": ws.get("selenium"),
        "debug_port": data.get("debug_port"),
        "webdriver": data.get("webdriver"),
    }


def stop(user_id):
    """Para o perfil `user_id`. Best-effort: não levanta (usado em finally)."""
    if not user_id:
        return
    try:
        _req("/api/v1/browser/stop", {"user_id": user_id})
    except ErroPipeline:
        pass


def esta_ativo(user_id):
    """True se o perfil `user_id` está com o browser aberto."""
    try:
        data = _req("/api/v1/browser/active", {"user_id": user_id})
    except ErroPipeline:
        return False
    return (data.get("status") == "Active")


def listar_perfis(page=1, page_size=100):
    """Lista os perfis do AdsPower (p/ descobrir o user_id de cada canal). Devolve a lista `list`."""
    data = _req("/api/v1/user/list", {"page": page, "page_size": page_size})
    return data.get("list") or []


def _cli():
    """Utilitário de linha de comando p/ configurar/testar:
        py -3 adspower.py list          -> lista perfis (nome + user_id) p/ você mapear os canais
        py -3 adspower.py start <id>    -> inicia e imprime o CDP (teste da ponte)
        py -3 adspower.py stop <id>     -> para o perfil
    """
    import sys
    forcar_utf8_console()
    args = sys.argv[1:]
    if not args or args[0] == "list":
        for p in listar_perfis():
            print("%-16s %s" % (p.get("user_id", "?"), p.get("name") or p.get("remark") or ""))
        return 0
    if args[0] == "start" and len(args) > 1:
        info = start(args[1])
        print("CDP:", info["cdp"])
        print("selenium:", info.get("selenium"))
        return 0
    if args[0] == "stop" and len(args) > 1:
        stop(args[1])
        print("parado:", args[1])
        return 0
    print(_cli.__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
