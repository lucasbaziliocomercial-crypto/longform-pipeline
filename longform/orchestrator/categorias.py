# -*- coding: utf-8 -*-
"""categorias.py — categorias de produção (= franquia / board do ClickUp).

Cada categoria aponta para UMA List do ClickUp. Escolher a categoria RESTRINGE a
fonte dos cards (dropdown da GUI + busca da Etapa 1) só àquela List — em vez de varrer
o workspace inteiro. É o "você só deixa a LENA/Máfia na lista de cards".

Categorias (atualizado 2026-07-09 — novos canais "inicio 10/07"):
  - selena   (Selena / Alpha King) -> List "1- Selena"                (901327552227)
  - mafia                          -> List "1- Máfia"                 (901327627550)
  - selena-2 (Selena / Alpha King) -> List "2- Selena (inicio 10/07)" (901327800267)
  - mafia-2                        -> List "2- Máfia (inicio 10/07)"  (901327786380)
  - mafia-3                        -> List "3- Máfia (inicio 10/07)"  (901327800276)
  - mafia-4                        -> List "4- Máfia (inicio 10/07)"  (901327801269)
As categorias -2/-3/-4 são CANAIS NOVOS que herdam as MESMAS skills das irmãs (Selena/Máfia);
só muda a List de onde vêm os cards (reaproveitam premissas/thumbs em canais diferentes).

Para adicionar/trocar uma categoria, edite só o dicionário CATEGORIAS abaixo.
`aplicar()` injeta LONGFORM_CLICKUP_LIST (e, quando conhecido, LONGFORM_CLICKUP_SPACES)
no ambiente; o clickup_api.py já usa LONGFORM_CLICKUP_LIST para listar SÓ aquela List
(REST e — desde esta mudança — também o fallback pelo login do Claude).
"""

import os

# chave canônica -> configuração da categoria.
#   label     = rótulo exibido na GUI / CLI.
#   list_id   = ID NUMÉRICO da List do ClickUp (sai da URL .../v/li/<ID>). É o que vai pro
#               LONGFORM_CLICKUP_LIST — robusto (independe de acento/nome) e funciona mesmo
#               com a lista em "Shared with me" (o token convidado acessa por ID, não enumera).
#   list_name = nome legível da List (logs + dica de busca da Etapa 1 + fallback sem token).
#   spaces    = CSV de Spaces (backup p/ o fallback sem token; "" = usa o default do clickup_api).
#   aliases   = como o usuário pode escrever a categoria (case/acentos-insensível).
#   skill_roteiro        = skill (~/.claude/commands/<nome>.md) do PROMPT MESTRE do roteiro
#                          (Etapa 2). Default = "longform-roteiro" (Selena/Alpha King).
#   skill_thumb_override = skill com a ESPECIFICAÇÃO DE CAPA específica da categoria, injetada
#                          como OVERRIDE na Etapa 5 (precedência sobre o formato selena da skill
#                          compartilhada). None = usa o formato padrão (Selena) da skill.
#   youtube_canal        = nome legível do CANAL do YouTube da categoria (logs + painel de
#                          publicação). Neste repo a categoria É o canal (1 List = 1 canal).
#   adspower_user_id     = ID do perfil no AdsPower (um perfil anti-detecção por canal, com
#                          proxy + login próprios) que a Etapa 9/publicador abre p/ subir o
#                          vídeo. VAZIO = ainda não configurado; preencha aqui OU por env
#                          `LONGFORM_ADSPOWER_<CHAVE>` (ex.: LONGFORM_ADSPOWER_SELENA=h1yynkm).
#                          A env vence o dict (deixa configurar sem editar código).
CATEGORIAS = {
    "selena": {
        "label": "Selena (Alpha King)",
        "list_id": "901327552227",          # lista "Selena (AUTOMAÇÃO)" (Shared with me)
        "list_name": "Selena (AUTOMAÇÃO)",
        "spaces": "Selena,Selena 2",
        "aliases": ("lena", "selena", "alpha king", "alphaking", "selena automacao",
                    "lena automacao", "selena (automação)"),
        "skill_roteiro": "longform-roteiro",
        "skill_thumb_override": None,
        "youtube_canal": "Selena",
        "pasta_canal": "Selena 1",        # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1cyr053",   # perfil AdsPower "1- Selena" (2026-07-09)
    },
    "mafia": {
        "label": "Máfia",
        "list_id": "901327627550",           # lista "Máfia (AUTOMAÇÃO)" (Shared with me)
        "list_name": "Máfia (AUTOMAÇÃO)",
        "spaces": "",
        "aliases": ("mafia", "máfia", "mafia automacao", "máfia automação",
                    "máfia (automação)"),
        "skill_roteiro": "longform-roteiro-mafia",
        "skill_thumb_override": "longform-thumb-mafia",
        "youtube_canal": "Máfia",
        "pasta_canal": "Mafia 1",         # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1cyli2q",   # perfil AdsPower "1 - Máfia" (2026-07-09)
    },
    # ── Canais novos (inicio 10/07). Mesmas skills das irmãs; só muda a List. ──
    "selena-2": {
        "label": "Selena 2",
        "list_id": "901327800267",           # lista "2- Selena (inicio 10/07)" (Shared with me)
        "list_name": "2- Selena (inicio 10/07)",
        "spaces": "",
        "aliases": ("selena 2", "selena2", "selena-2", "2 selena", "2- selena",
                    "2-selena", "2- selena (inicio 10/07)"),
        "skill_roteiro": "longform-roteiro",
        "skill_thumb_override": None,
        "youtube_canal": "Selena 2",
        "pasta_canal": "Selena 2",        # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1egt2wf",   # perfil AdsPower "2- Selana" (2026-07-09)
    },
    "mafia-2": {
        "label": "Máfia 2",
        "list_id": "901327786380",           # lista "2- Máfia (inicio 10/07)" (Shared with me)
        "list_name": "2- Máfia (inicio 10/07)",
        "spaces": "",
        "aliases": ("mafia 2", "máfia 2", "mafia2", "mafia-2", "máfia-2", "2 mafia",
                    "2- máfia", "2- mafia", "2- máfia (inicio 10/07)"),
        "skill_roteiro": "longform-roteiro-mafia",
        "skill_thumb_override": "longform-thumb-mafia",
        "youtube_canal": "Máfia 2",
        "pasta_canal": "Mafia 2",         # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1dko4b6",   # perfil AdsPower "2- Máfia" (2026-07-09)
    },
    "mafia-3": {
        "label": "Máfia 3",
        "list_id": "901327800276",           # lista "3- Máfia (inicio 10/07)" (Shared with me)
        "list_name": "3- Máfia (inicio 10/07)",
        "spaces": "",
        "aliases": ("mafia 3", "máfia 3", "mafia3", "mafia-3", "máfia-3", "3 mafia",
                    "3- máfia", "3- mafia", "3- máfia (inicio 10/07)"),
        "skill_roteiro": "longform-roteiro-mafia",
        "skill_thumb_override": "longform-thumb-mafia",
        "youtube_canal": "Máfia 3",
        "pasta_canal": "Mafia 3",         # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1dlxiwc",   # perfil AdsPower "3- Máfia" (2026-07-09)
    },
    "mafia-4": {
        "label": "Máfia 4",
        "list_id": "901327801269",           # lista "4- Máfia (inicio 10/07)" (Shared with me)
        "list_name": "4- Máfia (inicio 10/07)",
        "spaces": "",
        "aliases": ("mafia 4", "máfia 4", "mafia4", "mafia-4", "máfia-4", "4 mafia",
                    "4- máfia", "4- mafia", "4- máfia (inicio 10/07)"),
        "skill_roteiro": "longform-roteiro-mafia",
        "skill_thumb_override": "longform-thumb-mafia",
        "youtube_canal": "Máfia 4",
        "pasta_canal": "Mafia 4",         # subpasta em projects/ (organização por canal, 2026-07-10)
        "adspower_user_id": "k1egvlde",   # perfil AdsPower "4- Máfia" (2026-07-09)
    },
}

PADRAO = "selena"


def _norm(s):
    return (s or "").strip().casefold()


def resolver(nome):
    """nome (chave/label/alias, case e acento-insensível) -> chave canônica.
    Vazio ou desconhecido -> PADRAO (nunca quebra)."""
    n = _norm(nome)
    if not n:
        return PADRAO
    if n in CATEGORIAS:
        return n
    for chave, cfg in CATEGORIAS.items():
        if n == _norm(cfg["label"]) or n in {_norm(a) for a in cfg.get("aliases", ())}:
            return chave
    return PADRAO


def config_de(nome):
    return CATEGORIAS[resolver(nome)]


def lista_env(nome):
    """Valor que vai pro LONGFORM_CLICKUP_LIST: o ID numérico (preferido) ou, se ainda não
    houver ID configurado, o NOME da List (o clickup_api resolve por nome quando dá)."""
    cfg = config_de(nome)
    return cfg.get("list_id") or cfg.get("list_name")


def nome_lista_de(nome):
    """Nome legível da List (logs + dica de busca da Etapa 1)."""
    return config_de(nome).get("list_name") or lista_env(nome)


def label_de(nome):
    return config_de(nome)["label"]


def skill_roteiro(nome=None):
    """Skill do PROMPT MESTRE do roteiro (Etapa 2) da categoria (default = a atual no ambiente).
    Default seguro "longform-roteiro" (Selena) p/ categoria sem o campo configurado."""
    cfg = config_de(nome if nome is not None else atual())
    return cfg.get("skill_roteiro") or "longform-roteiro"


def skill_thumb_override(nome=None):
    """Skill com a ESPECIFICAÇÃO DE CAPA específica da categoria, injetada como override na
    Etapa 5. None = sem override (usa o formato padrão Selena da skill compartilhada)."""
    cfg = config_de(nome if nome is not None else atual())
    return cfg.get("skill_thumb_override")


def labels():
    """[(chave, label)] na ordem de declaração — para popular o dropdown da GUI."""
    return [(k, c["label"]) for k, c in CATEGORIAS.items()]


def aplicar(nome):
    """Fixa a categoria no ambiente: restringe a fonte de cards do ClickUp à List dela.

    Override EXPLÍCITO (escolha do usuário) — sobrescreve qualquer LONGFORM_CLICKUP_LIST
    vindo do longform.env. Devolve a chave canônica aplicada."""
    chave = resolver(nome)
    cfg = CATEGORIAS[chave]
    os.environ["LONGFORM_CATEGORIA"] = chave
    os.environ["LONGFORM_CLICKUP_LIST"] = lista_env(chave)
    if cfg.get("spaces"):
        os.environ["LONGFORM_CLICKUP_SPACES"] = cfg["spaces"]
    return chave


def atual():
    """Categoria atualmente fixada no ambiente (default PADRAO)."""
    return resolver(os.environ.get("LONGFORM_CATEGORIA"))


def canal_de(nome=None):
    """Nome legível do CANAL do YouTube da categoria (default = a atual no ambiente).
    Neste repo a categoria É o canal — cai pro label da categoria se não configurado."""
    cfg = config_de(nome if nome is not None else atual())
    return cfg.get("youtube_canal") or cfg.get("label") or resolver(nome)


def pasta_canal(nome=None):
    """Nome da SUBPASTA de canal em projects/ onde os projetos da categoria ficam.
    Ex.: 'selena' -> 'Selena 1', 'mafia-3' -> 'Mafia 3' (organização por canal, 2026-07-10).
    Default = a atual no ambiente. Cai pro youtube_canal/label se não configurado."""
    cfg = config_de(nome if nome is not None else atual())
    return cfg.get("pasta_canal") or cfg.get("youtube_canal") or cfg["label"]


def pastas_canais():
    """Todos os nomes de subpasta de canal (para a descoberta ciente de canal em common.py)."""
    return [c["pasta_canal"] for c in CATEGORIAS.values() if c.get("pasta_canal")]


def adspower_user_id(nome=None):
    """ID do perfil AdsPower do canal da categoria (default = a atual no ambiente).

    Precedência: env `LONGFORM_ADSPOWER_<CHAVE>` (ex.: LONGFORM_ADSPOWER_SELENA) > campo
    `adspower_user_id` do dict. Devolve "" se não configurado (o publicador falha com uma
    mensagem clara nesse caso — não tenta adivinhar o canal)."""
    chave = resolver(nome if nome is not None else atual())
    env = os.environ.get("LONGFORM_ADSPOWER_%s" % chave.upper(), "").strip()
    if env:
        return env
    return (CATEGORIAS[chave].get("adspower_user_id") or "").strip()
