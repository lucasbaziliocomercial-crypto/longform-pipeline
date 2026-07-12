# -*- coding: utf-8 -*-
"""Anexa a capa aprovada (thumb_selected.png) no card do ClickUp — pontual.

Usado quando a flag de idempotência (.thumb_anexada_clickup) sobrou de um run antigo
e fez a esteira PULAR o reenvio da capa NOVA. Reusa clickup_api.anexar_arquivo
(REST com token, senão login do Claude). Atualiza a flag ao final.
"""
import sys
import config  # noqa: F401  (efeito colateral: carrega token/seams via os.environ)
from common import projeto_por_slug
import clickup_api

slug = sys.argv[1] if len(sys.argv) > 1 else "01-vc-gravida-do-alpha"
proj = projeto_por_slug(slug)

import json
card_id = json.loads(proj.source.read_text(encoding="utf-8")).get("card_id")
if not card_id:
    print("ERRO: card_id desconhecido no source.json"); sys.exit(1)
if not proj.existe(proj.thumb_selected):
    print("ERRO: thumb_selected.png não existe."); sys.exit(1)

print("Anexando %s no card %s ..." % (proj.thumb_selected.name, card_id))
clickup_api.anexar_arquivo(card_id, str(proj.thumb_selected), print)
proj.thumb_anexada_flag.write_text("ok", encoding="utf-8")
print("OK: capa nova anexada e flag atualizada.")
