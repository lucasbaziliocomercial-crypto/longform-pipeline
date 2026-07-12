# Esteira Long-form (YouTube 16:9) — ClickUp → Remotion

Pipeline novo de vídeo long-form (~5.000 palavras / ~35 min), separado do fluxo de
isca (TikTok) do TINAGO. Orquestrador Python headless + painel web nos 2 gates +
montagem no Remotion.

## Fluxo (8 etapas + 2 gates)

```
1 ClickUp ─ source.json
2 Roteiro ─ roteiro.txt (~5.000 palavras)        [skill longform-roteiro, Opus]
3 Validador ─ roteiro_validacao.json + fix       [skill longform-validar, Opus]
   └── GATE 1 (painel): aprovar/editar roteiro
4 Narração+SRT ─ narration.mp3 + narration.srt   [TTS seam + Whisper]
5 Bible+fichas+prompt ─ style_bible + prompts_referencia + prompts_thumbnail (1 = capa)  [skill longform-prompts-img]
6 Fichas→Library + Thumbnail ─ referencias.json + thumbs/thumb_01.png (a capa única)     [Magnific]
   └── GATE 2 (painel): validar a thumb (capa) → thumb_selected.png
7 Imagens ─ images/img_001..008.png (8 fixas = corpo do vídeo)   [Magnific, lock de personagem via Library + thumb]
8 Montagem ─ mapping.json → out/final.mp4         [build-mapping + Remotion]
```

## Como rodar

GUI (recomendado):
```
py -3 longform/orchestrator/gerar-longform.py "Alpha King"
```

CLI:
```
py -3 longform/orchestrator/pipeline.py "Alpha King"            # tudo, com gates
py -3 longform/orchestrator/pipeline.py --slug meu-video 5 6 7  # só etapas 5-7
py -3 longform/orchestrator/pipeline.py "Alpha King" --no-gates # automático (testes)
```

## Configuração — automática

`config.py` (importado por `pipeline.py`/`gerar-longform.py`) já liga TTS e Magnific **de
fábrica**, sem você exportar nada à mão. Para mudar voz/modelo/provider, edite
[longform.env](longform.env). Precedência: ambiente do shell > `longform.env` > defaults.

Antes de rodar a esteira, confirme o ambiente com o **diagnóstico**:

```
py -3 longform/orchestrator/testar-conexoes.py            # checagens rápidas
py -3 longform/orchestrator/testar-conexoes.py --tudo     # + sintetiza áudio e gera 1 imagem de teste
```

## Pré-requisitos (conexões externas)

| Etapa | Precisa | Estado / como mudar |
|------|---------|---------------|
| 4 (TTS) | provider de voz | ✅ default: sidecar CapCut (voz Joanne), `.env` já preenchido. Trocar p/ Magnific: `LONGFORM_TTS_PROVIDER=magnific` no `longform.env` |
| 4 (SRT) | Whisper do TINAGO | ✅ `gerar-srt-en.py` em `%USERPROFILE%\TINAGO AUTOMAÇÃO` (ou `TINAGO_DIR`) |
| 6 e 7 (imagens) | MCP do Magnific | ✅ `LONGFORM_MAGNIFIC_MCP=mcp__magnific` (default); modelo `imagen-nano-banana-2-flash` |
| 8 (render) | Node + Remotion | `cd longform/remotion && npm install` (só p/ overlays/legendas) |
| 1 (ClickUp) | MCP do ClickUp | já conectado; ajuste a List via `--list-hint` se preciso |

## Prompts mestres
As skills `longform-roteiro`, `longform-validar` e `longform-prompts-img` em
`~/.claude/commands/` têm um bloco marcado **"PROMPT MESTRE (inserir)"** — cole ali os
seus prompts mestres de roteiro / validação / padrão de thumb.

## Preview da montagem
```
cd longform/remotion && npx remotion studio
```
(depois de uma rodada que gerou `remotion/public/<slug>/`).
