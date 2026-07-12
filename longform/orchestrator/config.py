# -*- coding: utf-8 -*-
"""config.py — liga a esteira "de fábrica", ANTES de qualquer etapa rodar.

Resolve a causa-raiz dos travamentos das Etapas 4 (TTS) e 6/7 (Magnific): os seams
sempre estiveram prontos, mas dependiam de variáveis de ambiente que o usuário tinha de
exportar À MÃO toda sessão (ex.: `. .\\longform\\tts\\set-tts-env.ps1`). Bastava esquecer
uma e a etapa "travava" pedindo a env. Aqui essas variáveis ganham DEFAULTS automáticos
+ um arquivo editável (longform.env), e nada é sobrescrito se já estiver no ambiente.

Precedência (maior vence): ambiente real do shell > longform.env > defaults embutidos.

Basta IMPORTAR no topo dos pontos de entrada (efeito colateral popula os.environ):
    import config  # noqa: F401
"""

import os

from common import LONGFORM_DIR, ORCH_DIR

ENV_FILE = LONGFORM_DIR / "longform.env"
_CAPCUT_ADAPTER = ORCH_DIR / "capcut_tts.py"

# Defaults "funciona de fábrica" — aplicados só se a chave ainda NÃO existir no ambiente.
DEFAULTS = {
    # --- Etapas 6/7 (Magnific) -------------------------------------------------
    # O MCP do Magnific já está conectado neste ambiente (servidor `mcp__magnific`).
    "LONGFORM_MAGNIFIC_MCP": "mcp__magnific",
    # Modelo do CORPO do vídeo (Etapa 7) — também usado nas fichas (passo 1 da E6).
    # Precisa suportar `reference type=character` (lock de personagem via Library) e 16:9.
    # NENHUM modelo é ilimitado via MCP — todos cobram crédito; por isso o default é o
    # mais BARATO com character refs. Whitelist curada em `magnific_seam.MODOS_BODY`
    # (custos por img via images_simulate_cost, 16:9):
    #   - flux-2-klein                (DEFAULT, 10 créd/img, ~5s, 2K)
    #   - imagen-nano-banana-flash    (50 créd/img, ~12s)
    #   - imagen-nano-banana-2-flash  (75 créd/img, ~40s — zerou a conta)
    #   - flux-kontext                (100 créd/img, ~13s)
    # Trocar via `longform.env` — basta um `LONGFORM_MAGNIFIC_MODE=imagen-nano-banana-flash`.
    # ATENÇÃO: o antigo `recraft-v4-1` só aceita reference type=style — quebraria
    # silenciosamente a consistência de personagem. Por isso saiu do default.
    "LONGFORM_MAGNIFIC_MODE": "flux-2-klein",
    # Modelo SÓ DA THUMB (Etapa 6 passo 2). Nano Banana envelhece/escurece os rostos e
    # derruba credibilidade da CAPA — separamos a thumb num modelo top de linha (GPT 2),
    # que é SOTA-rank-1 no catálogo do Magnific, suporta 16:9 e character refs.
    # As FICHAS (passo 1) e a Etapa 7 continuam no LONGFORM_MAGNIFIC_MODE.
    "LONGFORM_MAGNIFIC_THUMB_MODE": "gpt-2",
    # Qualidade da thumb GPT-2 (low|medium|high). 'medium' = ~450 créd nas 3 variações do
    # Gate 2; 'high' = ~1200 (NUNCA use). 'low' = ~45 se precisar apertar ainda mais.
    "LONGFORM_MAGNIFIC_THUMB_QUALITY": "medium",
    # Modelo de REFINO da thumb (Nano Banana 2). REGRA DURA: a capa nasce SEMPRE no GPT 2; é
    # PROIBIDO gerar a thumb do ZERO no Nano Banana 2 (sai escura/sem graça). O Nano Banana 2
    # SÓ edita/refina uma base que o GPT 2 já gerou, quando a cena moderou (fluxo de 2 passos).
    # ATENÇÃO: "ilimitado" só vale no painel web; via MCP o Nano Banana 2 COBRA ~75 créd/img.
    # Deixe vazio ("") para desligar o refino e ficar 100% no GPT 2.
    "LONGFORM_MAGNIFIC_THUMB_REFINE_MODE": "imagen-nano-banana-2-flash",
    # Gate de QA do Claude (Opus) sobre a capa (Etapa 6): o Claude ABRE a thumb e julga contra
    # o padrão do canal; se reprovar, a Etapa 6 regenera com as sugestões (LONGFORM_THUMB_QA_RETRY
    # vezes) e, se ainda reprovar, manda pro Gate 2 humano em vez de auto-confirmar. Gasta uso do
    # Claude (não crédito Magnific). "0" desliga (volta ao auto-confirm silencioso).
    "LONGFORM_THUMB_QA": "1",
    "LONGFORM_THUMB_QA_RETRY": "1",

    # --- Idioma do conteúdo (roteiro + narração + legendas) --------------------
    # 'en' (default — conversão original do canal) | 'pt' (MODO TESTE: vídeo em
    # português pra equipe avaliar a HISTÓRIA). Ligado pela caixa "Vídeo em português"
    # da GUI. As imagens (Etapas 5/7) ficam SEMPRE em inglês (direção visual do Magnific).
    "LONGFORM_IDIOMA": "en",
    # Voz(es) da narração no MODO PORTUGUÊS (só valem quando LONGFORM_IDIOMA=pt). IDs de
    # voz são da SUA conta CapCut — liste com:
    #   py -3 longform/orchestrator/capcut_tts.py --speakers
    # Se ambos ficarem vazios, a Etapa 4 reaproveita a cadeia EN (narra com sotaque) e avisa.
    "LONGFORM_TTS_VOICE_PT": "",            # voz primária pt-BR (ex.: uma feminina BR)
    "LONGFORM_TTS_VOICE_FALLBACK_PT": "",   # CSV de fallbacks pt-BR (mesmo papel da cadeia EN)

    # --- Etapa 4 (TTS) ---------------------------------------------------------
    # Provider padrão = sidecar CapCut (voz Joanne + cadeia de fallback dentro do PRÓPRIO
    # CapCut). Para mudar para Magnific (créditos), use "magnific". O config.py já liga
    # o CapCut por padrão; o .env de longform/tts/CapCut-TTS tem o login da usuária.
    "LONGFORM_TTS_PROVIDER": "capcut",
    "LONGFORM_TTS_VOICE": "XMWzAzwYm487GEok2uG2",  # Joanne (CapCut, artista EN feminina)
    # Cadeia de fallback CSV — usada SE a voz primária bater SmartToolRateLimit (limite
    # por conta no fluxo intelligence/create das vozes de ARTISTA da CapCut). Estas duas
    # NÃO são artistas (vão pelo multi_platform, outro pool de quota) — então a Etapa 4
    # se mantém 100% CapCut sem precisar de Magnific.
    #   cool_lady = ICL_en_female_guanggao (EN feminina calma — ideal romance/audiobook)
    #   labebe    = ICL_en_female_jiaoao   (EN feminina brilhante)
    "LONGFORM_TTS_VOICE_FALLBACK": "cool_lady,labebe",
    # Tamanho-alvo de cada bloco de texto enviado ao TTS CapCut (chars). Blocos menores
    # reduzem o blast-radius de um rate-limit (só 1 bloco precisa cair pra fallback).
    "LONGFORM_TTS_CHUNK_CHARS": "1500",
    # Backoff quando a cadeia INTEIRA de vozes cai em rate-limit num bloco (a conta CapCut
    # atingiu o limite global — pega multi_platform E intelligence/create). Em vez de
    # abortar um run de dezenas de blocos, a Etapa 4 ESPERA e tenta a cadeia de novo.
    # Rate-limit é transitório; só falha de vez após _RETRIES esperas. Espera = min(
    # _WAIT * 2**n, _WAIT_MAX) — default 45,90,180,300,300,300s (~17min de tolerância).
    "LONGFORM_TTS_RATELIMIT_RETRIES": "6",
    "LONGFORM_TTS_RATELIMIT_WAIT": "45",       # base da espera (s), dobra a cada tentativa
    "LONGFORM_TTS_RATELIMIT_WAIT_MAX": "300",  # teto de cada espera (s)
    # Legado: shell-out template (não é mais o caminho principal — synthesize_capcut
    # chama o adapter como lib). Mantido p/ debug / testes manuais via PowerShell.
    "LONGFORM_TTS_CMD": 'py -3 "%s" --text "{texto}" --voice "{voz}" --out "{saida}"' % _CAPCUT_ADAPTER,

    # Fallback provider=magnific: Rhea Sterling (631) — voz EN ideal p/ romance/audiobook.
    "LONGFORM_TTS_MAGNIFIC_VOICE": "631",
    "LONGFORM_TTS_MAGNIFIC_MODEL": "eleven_turbo_v2_5",  # aguenta blocos de até ~10k chars
    "LONGFORM_TTS_CHUNK": "9000",  # tamanho-alvo de cada bloco de texto (chars) p/ o TTS Magnific
}


def _parse_env_file(path):
    """Lê um arquivo KEY=VALUE simples (ignora linhas em branco e comentários `#`)."""
    dados = {}
    if not path.is_file():
        return dados
    for linha in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = linha.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        chave, _, valor = s.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave:
            dados[chave] = valor
    return dados


def carregar():
    """Aplica longform.env (se existir) e depois os defaults — sem sobrescrever o ambiente."""
    # 1) o arquivo do usuário tem prioridade sobre os defaults embutidos…
    for chave, valor in _parse_env_file(ENV_FILE).items():
        os.environ.setdefault(chave, valor)
    # 2) …e os defaults embutidos preenchem o que ainda faltar.
    for chave, valor in DEFAULTS.items():
        os.environ.setdefault(chave, valor)
    return os.environ


def resumo():
    """Devolve as chaves relevantes já resolvidas (para o diagnóstico / logs)."""
    chaves = ("LONGFORM_IDIOMA", "LONGFORM_TTS_VOICE_PT",
              "LONGFORM_TTS_PROVIDER", "LONGFORM_TTS_CMD", "LONGFORM_TTS_VOICE",
              "LONGFORM_TTS_MAGNIFIC_VOICE", "LONGFORM_TTS_MAGNIFIC_MODEL",
              "LONGFORM_MAGNIFIC_MCP", "LONGFORM_MAGNIFIC_MODE",
              "LONGFORM_MAGNIFIC_THUMB_MODE", "LONGFORM_MAGNIFIC_THUMB_QUALITY",
              "LONGFORM_CLICKUP_LIST", "TINAGO_DIR")
    return {k: os.environ.get(k, "") for k in chaves}


# Efeito colateral no import: a esteira fica "ligada" só por importar config.
carregar()
