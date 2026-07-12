# -*- coding: utf-8 -*-
"""Etapa 1 — ClickUp. Acha a TAREFA pelo TEMA (= nome do card, ex.: "14- Ela se
escondeu para assistir") via MCP do ClickUp (headless, no login do usuário), parseia o
CORPO da descrição (rótulos Título/Premissa/Thumb) e grava source.json + thumb_ref.png.

O corpo do card é estruturado: o nome da tarefa é só o tema/índice em pt-BR; o título
REAL (inglês) vem do rótulo "Título:", a premissa do rótulo "Premissa:" (fonte oficial —
NÃO segue o Google Doc do comentário) e a thumb de referência são os anexos de imagem.

source.json = {
    "titulo": ...,      # texto do rótulo "Título:" (inglês)
    "premissa": ...,    # texto do rótulo "Premissa:" (integral)
    "thumb_brief": ..., # texto do rótulo "Thumb:" ou null
    "tema": ...,        # o nome/tema digitado (card_query)
    "categoria": ...,   # categoria ativa: 'selena' | 'mafia' | ... (lida pelo QA da capa)
    "card_id": ..., "card_url": ..., "thumb_ref": ...,  # thumb_ref.png ou null
}

A busca tenta clickup_search e, se falhar, varre a hierarquia. Passe opts['list_hint']
para apontar a List se a busca não achar de primeira.
"""

import json
import os

import categorias as _categorias

from common import ErroPipeline
from runner import rodar_claude, MODELO_CLICKUP

# Prefixo do MCP do ClickUp como o `claude -p` headless o enxerga.
# IMPORTANTE: o ClickUp aqui é um *connector da claude.ai* (não um servidor do bloco
# mcpServers do .claude.json). No subprocess headless ele aparece como
# `mcp__claude_ai_ClickUp` — NÃO use o UUID volátil que a sessão interativa mostra
# (ex.: mcp__bb24…), pois ele muda a cada sessão e o --allowedTools nunca casaria.
# Override por env var p/ casos em que o connector tenha outro nome.
CLICKUP_MCP = os.environ.get("LONGFORM_CLICKUP_MCP", "mcp__claude_ai_ClickUp")

# Ferramentas (read-only) do ClickUp que a etapa precisa + Write para salvar o JSON.
# Os `*_document_*` entram para o modo "roteiro pronto" (puxar o roteiro de um ClickUp Doc).
_CLICKUP_TOOLS = " ".join(
    CLICKUP_MCP + "__" + t for t in (
        "clickup_get_workspace_hierarchy",
        "clickup_get_list",
        "clickup_get_folder",
        "clickup_filter_tasks",
        "clickup_get_task",
        "clickup_get_task_comments",
        "clickup_search",
        "clickup_list_document_pages",
        "clickup_get_document_pages",
    )
)
# Bash entra para baixar (curl) o anexo de referência da thumb que vem no card.
ALLOWED = "Read Write Bash " + _CLICKUP_TOOLS


def _bloco_roteiro_pronto():
    """Passo extra (modo ROTEIRO PRONTO): puxa o roteiro completo do Doc linkado no card e
    salva como roteiro.txt, pra a Etapa 2 usar direto (sem gerar). Suporta Google Doc e ClickUp Doc."""
    return """
4. ROTEIRO PRONTO (modo LIGADO p/ este card): o roteiro COMPLETO está num DOCUMENTO linkado no
   card (Google Doc ou ClickUp Doc). Ache o link no corpo da descrição (markdown_description) OU
   nos comentários (clickup_get_task_comments) — procure um rótulo tipo "Roteiro:"/"Script:"/
   "Documento:" ou um link solto. Baixe o TEXTO INTEGRAL e salve em `roteiro.txt` (texto puro):
   a) GOOGLE DOC (link docs.google.com/document/d/<ID>/...): extraia o <ID> e baixe o texto via
      `curl -L -o roteiro.txt "https://docs.google.com/document/d/<ID>/export?format=txt"`.
      CONFIRA o resultado: se vier começando com "<!DOCTYPE html"/"<html" ou muito curto (< 500
      caracteres), o Doc NÃO está compartilhado como "qualquer pessoa com o link pode ver" — então
      NÃO salve roteiro.txt e diga isso no resumo (a usuária precisa liberar o compartilhamento).
   b) CLICKUP DOC (link app.clickup.com/.../docs/<doc_id> ou um doc do workspace): pegue o doc_id e
      use clickup_list_document_pages + clickup_get_document_pages para ler TODAS as páginas; junte o
      conteúdo na ordem e salve em `roteiro.txt` (texto puro, sem markdown de cabeçalho).
   Salve o roteiro INTEGRAL, sem resumir nem cortar. Se NÃO achar nenhum link de Doc, NÃO invente:
   deixe sem roteiro.txt e diga no resumo que o card não tinha Doc de roteiro linkado.
"""


def _prompt(card_query, list_hint, card_id=None, roteiro_pronto=False):
    hint = ("\nDica de localização (use se a busca não achar de primeira): %s" % list_hint) if list_hint else ""
    bloco_roteiro = _bloco_roteiro_pronto() if roteiro_pronto else ""
    if card_id:
        # Caminho determinístico: o card já foi escolhido no dropdown da GUI (id em mãos).
        passo1 = (
            '1. ABRIR A TAREFA DIRETAMENTE pelo id já conhecido "%s":\n'
            "   - Chame clickup_get_task com esse id. NÃO faça busca — o card já está escolhido.\n"
            '   - Confirme que o nome bate com o tema "%s"; se o id falhar, caia para a busca pelo nome.'
            % (card_id, card_query)
        )
    else:
        passo1 = f"""1. ACHAR A TAREFA pelo nome "{card_query}":
   - Primeiro tente clickup_search por "{card_query}".
   - Se não achar, chame clickup_get_workspace_hierarchy (max_depth=3), localize a List que
     contém esses cards (ex.: um Space/Folder/List de romance long-form) e use
     clickup_filter_tasks para encontrar a tarefa cujo NOME contém "{card_query}".
   - Escolha a tarefa cujo nome bate melhor com o tema. Se houver várias parecidas, prefira a
     que ainda NÃO foi produzida (status "to do"/aberto)."""
    return f"""Você é a Etapa 1 (ClickUp) de uma esteira de produção de vídeo. Use as ferramentas do
MCP do ClickUp para localizar o card de origem e extrair o conteúdo. NÃO faça perguntas.

ALVO: a TAREFA cujo nome é (ou contém) "{card_query}". Esse texto é o TEMA = o NOME do card.{hint}

PASSOS:
{passo1}
2. Leia a tarefa com clickup_get_task e pegue o CORPO da descrição
   (markdown_description, ou description). O corpo é ESTRUTURADO com rótulos em negrito —
   parseie assim (o rótulo pode vir como "Título:", "**Título:**", "Titulo:" etc.):
   - titulo      = o texto DEPOIS de "Título:" (geralmente em INGLÊS — é o título real do vídeo).
                   NÃO use o nome da tarefa como título; o nome é só o tema/índice.
   - premissa    = o texto DEPOIS de "Premissa:" (a fonte oficial da premissa é ESTE campo do
                   corpo — NÃO siga links de Google Doc). Pegue INTEGRAL, sem resumir.
   - thumb_brief = o texto DEPOIS de "Thumb:" (instruções da thumb de referência), se existir.
   Se algum rótulo não existir, caia para o fallback: titulo = nome da tarefa; premissa =
   descrição integral. Anote no resumo qual rótulo faltou.
3. THUMB DE REFERÊNCIA → salve como `thumb_ref.png` na pasta (Bash + curl). A referência é o que
   mais alimenta a capa (a Etapa 5 reflete a AÇÃO dela), então CACE em TODO o corpo do card —
   NÃO só no rótulo "Thumb:". Procure um link de YOUTUBE em QUALQUER lugar: no rótulo "Thumb:",
   num rótulo "Vídeo inspiração"/"Inspiração"/"Referência", ou um link SOLTO (youtu.be/<ID>,
   youtube.com/watch?v=<ID>, youtube.com/shorts/<ID>) em qualquer parte do markdown_description.
   Ordem de preferência:
   a) Se houver link do YOUTUBE sob o rótulo "Thumb:", use ESSE (é o mais intencional). Senão,
      use QUALQUER link de YouTube achado no corpo (inclusive solto / "Vídeo inspiração"). Extraia
      o VIDEO_ID e baixe a thumbnail na MAIOR resolução:
      `curl -L -o thumb_ref.png "https://i.ytimg.com/vi/<VIDEO_ID>/maxresdefault.jpg"`
      Se vier vazio/pequeno (<5 KB) ou 404, caia para `hqdefault.jpg` no mesmo padrão.
   b) Senão, se houver alguma URL de imagem direta no corpo (jpg/png/webp), baixe-a.
   c) Senão, procure em `attachments` (se o MCP expuser) a 1ª imagem e baixe.
   No resumo, DIGA de onde veio a referência (rótulo Thumb / link solto / inspiração / anexo) ou
   que não havia nenhuma. Se NADA der, só anote (a Etapa 5 segue sem referência). NÃO falhe a
   etapa por causa da thumb — ela é opcional.
{bloco_roteiro}
SAÍDA (obrigatória): NÃO monte JSON você mesmo (títulos com aspas quebram o JSON). Em vez disso,
salve cada campo num arquivo de TEXTO PURO separado, com Write, EXATAMENTE como aparece no card —
sem aspas extras em volta, sem escapar nada, sem markdown. O orquestrador (Python) é quem monta o
source.json a partir destes arquivos. Salve na pasta de trabalho:
  - `_f_titulo.txt`      -> o título real (texto do rótulo "Título:", geralmente em inglês)
  - `_f_premissa.txt`    -> a premissa INTEGRAL (texto do rótulo "Premissa:")
  - `_f_thumb_brief.txt` -> o texto do rótulo "Thumb:" (deixe o arquivo VAZIO se não houver)
  - `_f_card_nome.txt`   -> o NOME LITERAL da tarefa no ClickUp, EXATAMENTE como aparece (ex.:
                           "01 - Grávida do Alpha"). É o índice/tema com o número — é o que vira o
                           nome do arquivo do vídeo final. NÃO use o "Título:" aqui.
  - `_f_card_id.txt`     -> o id da tarefa
  - `_f_card_url.txt`    -> a url da tarefa
(O `tema` e o `thumb_ref` o orquestrador preenche sozinho — não precisa salvar.)

Depois imprima no chat um resumo de 2 linhas: o título escolhido, o id do card e se baixou a
thumb_ref. Se NÃO encontrar o card, salve `_f_titulo.txt` e `_f_premissa.txt` VAZIOS e explique no
resumo o que faltou (qual List procurar)."""


def run(proj, log, cancel=None, card_query="Alpha King", list_hint=None, card_id=None,
        roteiro_pronto=False, **_):
    # Idempotência: se já há source.json E (no modo roteiro-pronto) já há roteiro.txt, pula.
    if proj.existe(proj.source) and (not roteiro_pronto or proj.existe(proj.roteiro)):
        log("    source.json já existe — usando o existente (Etapa 1 pulada).")
        return _carregar(proj)

    via = ("id %s" % card_id) if card_id else "busca por nome"
    extra = " + ROTEIRO PRONTO (puxando o Doc do card)" if roteiro_pronto else ""
    log("▶ Etapa 1/8 — ClickUp: lendo título + premissa de '%s' (%s, %s)%s..."
        % (card_query, via, MODELO_CLICKUP, extra))
    rodar_claude(_prompt(card_query, list_hint, card_id, roteiro_pronto), proj.dir, log, cancel,
                 modelo=MODELO_CLICKUP, allowed_tools=ALLOWED)

    # Monta o source.json a partir dos _f_*.txt que o agente salvou (Python escapa tudo via
    # json.dumps — robusto a aspas no título). Fallback: se o agente, à moda antiga, escreveu um
    # source.json válido direto, mantém.
    _montar_source(proj, card_query, log)

    if not proj.existe(proj.source):
        raise ErroPipeline("Etapa 1 não gerou source.json (verifique o MCP do ClickUp e a List do card).")

    # Modo roteiro-pronto: o roteiro.txt é OBRIGATÓRIO (a Etapa 2 vai usá-lo direto). Se não veio,
    # falha com mensagem clara em vez de deixar a Etapa 2 GERAR um roteiro (que não é o que se quer).
    if roteiro_pronto and not proj.existe(proj.roteiro):
        raise ErroPipeline(
            "ROTEIRO PRONTO ligado, mas não consegui puxar o roteiro do Doc do card '%s'. "
            "Confira: (1) há um link de Google Doc/ClickUp Doc no corpo do card ou num comentário; "
            "(2) se for Google Doc, ele está compartilhado como 'qualquer pessoa com o link pode ver'. "
            "Ou desligue a opção 'Roteiro pronto' para gerar o roteiro normalmente." % card_query
        )
    if roteiro_pronto:
        from common import contar_palavras
        n = contar_palavras(proj.roteiro.read_text(encoding="utf-8", errors="replace"))
        log("    ✓ Roteiro pronto puxado do Doc do card (%d palavras) — a Etapa 2 vai usá-lo direto." % n)
    dados = _carregar(proj)
    if not dados.get("titulo") or not dados.get("premissa"):
        raise ErroPipeline(
            "source.json veio sem título/premissa — confirme que o card '%s' tem os rótulos "
            "'Título:' e 'Premissa:' no corpo da descrição, e rode de novo (passe list_hint "
            "se a busca não achar o card)." % card_query
        )
    log("    ✓ Card lido: %r (id %s)" % (dados.get("titulo"), dados.get("card_id")))
    return dados


_CAMPOS_F = ("_f_titulo.txt", "_f_premissa.txt", "_f_thumb_brief.txt",
             "_f_card_nome.txt", "_f_card_id.txt", "_f_card_url.txt")


def _montar_source(proj, card_query, log):
    """Monta o source.json a partir dos arquivos `_f_*.txt` que o agente salvou (texto puro),
    usando json.dumps (que escapa aspas/quebras corretamente) — assim um título com aspas NUNCA
    quebra o JSON. Se os `_f_*.txt` não existirem mas o agente tiver escrito um source.json válido
    à moda antiga, mantém esse. No fim, apaga os `_f_*.txt`."""
    def _ler(nome):
        p = proj.dir / nome
        if not p.exists():
            return None
        t = p.read_text(encoding="utf-8", errors="replace").strip()
        return t or None

    f_titulo = proj.dir / "_f_titulo.txt"
    if not f_titulo.exists():
        # Agente não usou os _f_*.txt. Se escreveu um source.json válido direto, aceita.
        if proj.existe(proj.source):
            try:
                json.loads(proj.source.read_text(encoding="utf-8"))
                log("    (Etapa 1 escreveu source.json direto e válido — usando.)")
                return
            except Exception:  # noqa: BLE001
                log("    ⚠ source.json do agente é inválido e não há _f_*.txt — não dá pra remontar.")
        return  # sem _f_ e sem source válido -> run() levanta o erro de 'não gerou source.json'

    dados = {
        "titulo": _ler("_f_titulo.txt") or "",
        "premissa": _ler("_f_premissa.txt") or "",
        "thumb_brief": _ler("_f_thumb_brief.txt"),
        "tema": card_query,
        # Nome literal do card no ClickUp ("01 - ..."). É o que renomeia o vídeo final
        # (ver entrega._nome_amigavel). Cai pro card_query se o agente não salvou.
        "card_nome": _ler("_f_card_nome.txt") or card_query,
        "card_id": _ler("_f_card_id.txt"),
        "card_url": _ler("_f_card_url.txt"),
        "thumb_ref": "thumb_ref.png" if proj.existe(proj.thumb_ref) else None,
        # Categoria ativa no momento da criação do projeto (ex.: 'mafia', 'selena').
        # Lida pelo QA (qa_thumb) para adaptar o critério do lead masculino.
        "categoria": _categorias.atual(),
    }
    proj.source.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    for nome in _CAMPOS_F:
        try:
            (proj.dir / nome).unlink()
        except OSError:
            pass


def _carregar(proj):
    try:
        return json.loads(proj.source.read_text(encoding="utf-8"))
    except Exception as e:
        raise ErroPipeline("source.json inválido: %s" % e)
