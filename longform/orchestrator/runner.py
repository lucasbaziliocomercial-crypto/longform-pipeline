# -*- coding: utf-8 -*-
"""runner.py — motor de execução headless (porta de novela_orquestra.py).

Roda `claude -p --output-format stream-json` na pasta do projeto, com retry/backoff
em erro transitório da API, e roda scripts .py mecânicos (Whisper etc.) transmitindo
a saída pro log. As skills (slash commands) são lidas de ~/.claude/commands e
montadas com um preâmbulo headless.
"""

import os
import re
import json
import time
import subprocess
from pathlib import Path

from common import achar_claude, achar_python, COMMANDS_DIR, ErroPipeline, SUBPROCESS_FLAGS

TIMEOUT_CLAUDE = 3600   # long-form gera roteiro/validação em várias seções — folga maior
TIMEOUT_SCRIPT = 1800

CLAUDE_MAX_TENTATIVAS = 4   # 1 tentativa + até 3 re-tentativas
CLAUDE_BACKOFF_BASE = 8     # 8 -> 16 -> 32 s

_RE_ERRO_TRANSITORIO = re.compile(
    r"overload|rate.?limit|\b429\b|\b529\b"
    r"|internal server error|service unavailable|bad gateway|gateway timeout"
    r"|timed out|\btimeout\b|connection (?:error|reset)|econnreset"
    r"|temporarily|please try again|try again later",
    re.I,
)

# Tiering de modelo por etapa (mesma filosofia do TINAGO: qualidade onde importa).
# CUSTO: cada sessão claude -p tem um piso fixo (~25k tok de system prompt + tools, medido
# 2026-07-22) e Opus custa ~5× Sonnet por token. Por isso só o que exige julgamento criativo
# fica em Opus; o resto desce pra Sonnet. Todos sobrescrevíveis por env (reverta se a qualidade cair).
MODELO_ROTEIRO = os.environ.get("LONGFORM_MODELO_ROTEIRO", "opus").strip() or "opus"    # criação: Opus (qualidade do produto)
# Validador = revisão ESTRUTURAL + auto-fix in-place. Era Opus e é a sessão Opus MAIS PESADA
# (relê as ~5.000 palavras e reescreve em vários turnos). Sonnet dá conta da correção estrutural
# e o gate de nota (META_SCORE) continua valendo. Reverta com LONGFORM_MODELO_VALIDAR=opus.
MODELO_VALIDAR = os.environ.get("LONGFORM_MODELO_VALIDAR", "sonnet").strip() or "sonnet"
MODELO_CLICKUP = "sonnet"   # leitura estruturada de card (mecânico)
MODELO_PROMPTS = "sonnet"   # style bible + prompts de thumb
MODELO_IMG_PROMPTS = "sonnet"  # derivar prompts de imagem a partir da thumb
MODELO_PUBLICACAO = "sonnet"  # título/descrição/tags/hashtags do YouTube a partir do roteiro (mecânico)
# Humanização = normalização de pontuação/formatação (NÃO muda palavras) → tarefa mecânica;
# Haiku dá conta e é bem mais rápido que o Sonnet (era ~6 min). Override: LONGFORM_MODELO_HUMANIZAR.
MODELO_HUMANIZAR = os.environ.get("LONGFORM_MODELO_HUMANIZAR", "haiku").strip() or "haiku"

# Effort de raciocínio por etapa (--effort: low/medium/high/xhigh/max). None = NÃO passa o flag
# (herda o default da sessão). Só definimos onde há ganho claro e seguro:
#   - roteiro 'low'    → VELOCIDADE. O default da sessão (settings.json effortLevel) era 'low' e foi
#                        o que gerou TODOS os vídeos publicados (~10-11 min, qualidade aceita). Medição
#                        2026-06-19: subir p/ 'high' deixou o roteiro ~6 min MAIS LENTO sem ganho pedido
#                        → revertido p/ 'low'. Suba p/ medium/high/xhigh se quiser enredo mais encorpado
#                        (custo ~+6 min por nível). Override: LONGFORM_EFFORT_ROTEIRO.
#   - humanizar 'low'  → normalização mecânica não precisa de raciocínio.
EFFORT_ROTEIRO = os.environ.get("LONGFORM_EFFORT_ROTEIRO", "low").strip() or None
EFFORT_HUMANIZAR = os.environ.get("LONGFORM_EFFORT_HUMANIZAR", "low").strip() or None


PREAMBULO = """MODO AUTOMÁTICO (headless) — você foi chamado por um orquestrador, sem humano no chat.
- A PASTA DE TRABALHO é o diretório atual (.). Os arquivos de entrada estão aqui e a saída vai aqui.
- NÃO faça perguntas, NÃO pause, NÃO espere validação humana (ela acontece fora, no painel).
- Onde a instrução mandar PARAR e perguntar, ASSUMA o default mais razoável e ANOTE no resumo final.
- Salve o(s) arquivo(s) pedido(s) com Write/Edit. NÃO rode shell a menos que a tarefa peça.

Siga as instruções da skill abaixo:

=== SKILL ===
"""


def ler_skill(nome):
    """Lê a skill `nome`.md de ~/.claude/commands, removendo o frontmatter YAML."""
    p = COMMANDS_DIR / (nome + ".md")
    if not p.is_file():
        raise ErroPipeline("Skill não encontrada: %s" % p)
    txt = p.read_text(encoding="utf-8")
    if txt.lstrip().startswith("---"):
        corpo = txt.lstrip()
        fim = corpo.find("\n---", 3)
        if fim != -1:
            txt = corpo[fim + 4:]
    return txt.strip()


def montar_prompt(skill_nome, extra=""):
    partes = [PREAMBULO, ler_skill(skill_nome)]
    if extra:
        partes.append("\n=== CONTEXTO ADICIONAL DO ORQUESTRADOR ===\n" + extra)
    return "\n".join(partes)


# Sentinela dos slots de PROMPT MESTRE ainda não preenchidos (ex.: categoria nova de Máfia
# criada com o prompt em branco para o usuário colar depois).
SENTINELA_SLOT = "(inserir)"


def skill_slot_vazio(nome):
    """True se a skill `nome` ainda tem um slot de PROMPT MESTRE em branco (sentinela
    "(inserir)") — serve para AVISAR que a categoria existe mas o prompt mestre não foi
    preenchido. Nunca levanta (skill inexistente -> False)."""
    try:
        return SENTINELA_SLOT in ler_skill(nome)
    except ErroPipeline:
        return False


# ---------------------------------------------------------------------------
# Streaming do stream-json -> log legível
# ---------------------------------------------------------------------------

def _checar_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ErroPipeline("Cancelado pelo usuário.")


def _dormir_cancelavel(segundos, cancel):
    fim = time.monotonic() + segundos
    while True:
        restante = fim - time.monotonic()
        if restante <= 0:
            return
        _checar_cancel(cancel)
        time.sleep(min(0.5, restante))


# Ferramentas que são PLUMBING do harness (não trabalho real da etapa): a descoberta de
# ferramentas deferidas via ToolSearch. Quando o MCP tem muitas tools (ex.: as ~50 do
# ClickUp), o modelo faz uma dança de ToolSearch antes de chamar a tool de verdade — isso
# não deve poluir o LOG do painel (só as chamadas reais, tipo clickup_search, aparecem).
_TOOLS_PLUMBING = {"ToolSearch"}


def _resumir_linha(linha):
    s = linha.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return linha[:200]
    try:
        ev = json.loads(s)
    except Exception:
        return linha[:200]
    tipo = ev.get("type")
    if tipo == "stream_event":
        return None
    if tipo == "rate_limit_event":
        info = ev.get("rate_limit_info") or {}
        status = info.get("status")
        if status and status != "allowed":
            return "⚠ limite de uso (%s): %s" % (info.get("rateLimitType", "?"), status)
        return None
    if tipo == "system":
        return None  # "(sessão iniciada)" era ruído — a Etapa já loga seu próprio cabeçalho ▶
    if tipo == "assistant":
        try:
            for b in ev["message"]["content"]:
                if b.get("type") == "text" and b.get("text", "").strip():
                    return "assistant: " + b["text"].strip().replace("\n", " ")[:160]
                if b.get("type") == "tool_use":
                    nome = b.get("name", "?")
                    if nome in _TOOLS_PLUMBING:
                        return None  # descoberta de tools (ToolSearch) — plumbing, não trabalho real
                    return "tool: %s" % nome
        except Exception:
            pass
        return None  # "(assistant)" vazio era ruído
    if tipo == "user":
        return None  # "(tool result)" era ruído — um por retorno de tool
    if tipo == "result":
        custo = ev.get("total_cost_usd")
        dur = ev.get("duration_ms")
        partes = []
        if isinstance(dur, (int, float)):
            partes.append("%.0fs" % (dur / 1000.0))
        if isinstance(custo, (int, float)):
            partes.append("$%.4f" % custo)
        return "(fim%s)" % ((" — " + ", ".join(partes)) if partes else "")
    return linha[:200]


def _stream(proc, log, cancel, prefixo="    "):
    linhas = []
    assert proc.stdout is not None
    for linha in proc.stdout:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            raise ErroPipeline("Cancelado pelo usuário.")
        linha = linha.rstrip("\n")
        if not linha.strip():
            continue
        linhas.append(linha)
        resumo = _resumir_linha(linha)
        if resumo:
            log(prefixo + resumo)
    proc.wait()
    return linhas


def _extrair_result(linhas):
    for linha in reversed(linhas):
        s = linha.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            ev = json.loads(s)
        except Exception:
            continue
        if ev.get("type") == "result" or "total_cost_usd" in ev or "result" in ev:
            return ev
    return {}


# ---------------------------------------------------------------------------
# Medição de gasto (só NOÇÃO — não altera comportamento) — 2026-07-22
# ---------------------------------------------------------------------------
# Cada `claude -p` é um agente completo; o `result` event já traz custo/tokens/duração.
# Acumulamos aqui (ponto ÚNICO por onde TODA sessão passa) para o pipeline imprimir um
# resumo no fim. Acumulador GLOBAL do processo: assume um pipeline() por vez (mesmo
# contrato do lock "uma execução por projeto"); pipeline() chama metricas_reset() no início.
_METRICAS = []


def metricas_reset():
    """Zera o acumulador do run (chamado no início de pipeline())."""
    _METRICAS.clear()


def metricas():
    """Cópia da lista de métricas por sessão coletadas até agora."""
    return list(_METRICAS)


def _registrar_metrica(res, modelo):
    """Acumula custo/tokens/duração de UMA sessão claude -p a partir do seu result event.

    Chamado a CADA tentativa que produziu um result — inclusive uma que falhou DEPOIS de já
    ter consumido tokens (retry transitório), pra a 'noção de gasto' não subestimar. Ignora
    sessões sem result (crash cedo, sem custo a medir)."""
    if not isinstance(res, dict):
        return
    custo = res.get("total_cost_usd")
    uso = res.get("usage") or {}
    if custo is None and not uso:
        return
    _METRICAS.append({
        "modelo": modelo or "default",
        "cost": float(custo) if isinstance(custo, (int, float)) else 0.0,
        "dur_ms": res.get("duration_ms") or 0,
        "in": uso.get("input_tokens") or 0,
        "out": uso.get("output_tokens") or 0,
        "cache_read": uso.get("cache_read_input_tokens") or 0,
        "cache_cria": uso.get("cache_creation_input_tokens") or 0,
    })


def _fmt_tok(x):
    """Formata contagem de tokens compacta (1.2M / 48k / 512)."""
    x = int(x or 0)
    if x >= 1_000_000:
        return "%.1fM" % (x / 1_000_000.0)
    if x >= 1000:
        return "%.0fk" % (x / 1000.0)
    return str(x)


def formatar_resumo_custo():
    """Linhas de resumo do gasto de modelo do run atual, agrupado por modelo. Lista vazia se
    nenhuma sessão claude -p rodou (ex.: só etapas de montagem FFmpeg). O custo é o
    `total_cost_usd` que o CLI reporta — no login/assinatura ele é EQUIVALENTE a list price
    (proxy de gasto), não uma cobrança real."""
    if not _METRICAS:
        return []
    por_modelo = {}
    for m in _METRICAS:
        g = por_modelo.setdefault(m["modelo"],
                                  {"n": 0, "cost": 0.0, "dur_ms": 0, "in": 0, "out": 0,
                                   "cr": 0, "cc": 0})
        g["n"] += 1
        g["cost"] += m["cost"]
        g["dur_ms"] += m["dur_ms"]
        g["in"] += m["in"]
        g["out"] += m["out"]
        g["cr"] += m["cache_read"]
        g["cc"] += m["cache_cria"]

    linhas = ["", "💸 Gasto de modelo neste run (sessões claude -p — custo ≈ list price, proxy):"]
    tot = {"n": 0, "cost": 0.0, "dur_ms": 0, "in": 0, "out": 0, "cr": 0, "cc": 0}
    for modelo in sorted(por_modelo):
        g = por_modelo[modelo]
        for k in tot:
            tot[k] += g[k]
        entrada = g["in"] + g["cr"] + g["cc"]
        linhas.append(
            "   %-8s: %d sessão(ões) · $%.4f · %.0fs · in %s (cache %s) / out %s"
            % (modelo, g["n"], g["cost"], g["dur_ms"] / 1000.0,
               _fmt_tok(entrada), _fmt_tok(g["cr"]), _fmt_tok(g["out"])))
    entrada_tot = tot["in"] + tot["cr"] + tot["cc"]
    linhas.append(
        "   ─ total : %d sessão(ões) · $%.4f · %.0fs de modelo · in %s / out %s"
        % (tot["n"], tot["cost"], tot["dur_ms"] / 1000.0,
           _fmt_tok(entrada_tot), _fmt_tok(tot["out"])))
    return linhas


# ---------------------------------------------------------------------------
# Execução de claude / scripts
# ---------------------------------------------------------------------------

def rodar_claude(prompt, pasta, log, cancel=None, modelo=None,
                 allowed_tools="Read Edit Write", effort=None):
    """Roda `claude -p` headless na pasta. Devolve o dict 'result'.

    `allowed_tools`: string separada por espaço de ferramentas liberadas (a Etapa 1
    estende com as ferramentas do MCP do ClickUp). Re-tenta em erro transitório com
    backoff, mantendo o MESMO modelo (não degrada qualidade).
    `effort`: nível de raciocínio (--effort low/medium/high/xhigh/max). None = herda o
    default da sessão (não passa o flag).
    """
    cmd = achar_claude() + [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "acceptEdits",
        "--allowedTools", allowed_tools,
    ]
    if modelo:
        cmd += ["--model", modelo]
    if effort:
        cmd += ["--effort", effort]
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # força o login/assinatura do Claude Code

    ultimo_erro = None
    for tent in range(1, CLAUDE_MAX_TENTATIVAS + 1):
        _checar_cancel(cancel)
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(pasta), env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True, encoding="utf-8", errors="replace",
                **SUBPROCESS_FLAGS,
            )
        except FileNotFoundError as e:
            raise ErroPipeline("Falha ao iniciar o claude: %s" % e)

        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except Exception:
            pass

        linhas = _stream(proc, log, cancel)
        res = _extrair_result(linhas)
        _registrar_metrica(res, modelo)  # mede o gasto de CADA tentativa (inclui retry)
        if proc.returncode == 0 and not res.get("is_error"):
            return res

        msg_res = str(res.get("result", ""))
        if proc.returncode != 0:
            ultimo_erro = "claude retornou código %d (veja o log acima)." % proc.returncode
        else:
            ultimo_erro = "claude reportou erro: %s" % msg_res[:300]

        transitorio = bool(_RE_ERRO_TRANSITORIO.search("\n".join(linhas))) \
            or bool(_RE_ERRO_TRANSITORIO.search(msg_res))
        if transitorio and tent < CLAUDE_MAX_TENTATIVAS:
            espera = CLAUDE_BACKOFF_BASE * (2 ** (tent - 1))
            log("⚠ erro transitório da API (tentativa %d/%d): %s — re-tentando em %ds..."
                % (tent, CLAUDE_MAX_TENTATIVAS, ultimo_erro, espera))
            _dormir_cancelavel(espera, cancel)
            continue
        break

    raise ErroPipeline(ultimo_erro or "claude falhou sem detalhe.")


def rodar_script(args, pasta, log, cancel=None):
    """Roda um script .py (Whisper / build-mapping) transmitindo a saída pro log."""
    _checar_cancel(cancel)
    cmd = achar_python() + [str(a) for a in args]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd, cwd=str(pasta), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, encoding="utf-8", errors="replace",
        **SUBPROCESS_FLAGS,
    )
    _stream(proc, log, cancel, prefixo="    ")
    if proc.returncode != 0:
        raise ErroPipeline("Script falhou (código %d): %s" % (proc.returncode, " ".join(cmd)))
