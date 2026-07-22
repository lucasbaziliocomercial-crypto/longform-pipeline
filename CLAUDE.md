# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **long-form video production pipeline** (YouTube 16:9, ~5.000 words / ~35 min) that
turns a ClickUp card into a finished MP4. It is the long-form counterpart to the
separate TINAGO "isca" (TikTok bait) workflow — see [longform/README.md](longform/README.md).
The pipeline is **headless**: a Python orchestrator drives Claude Code (`claude -p`)
and external MCPs for the creative steps, with two human decision **gates** served by a
local web panel. Final assembly defaults (2026-06-20) to a **dynamic Remotion montage**
(`LONGFORM_RENDER_ENGINE=dynamic`): a living gallery with randomized image order, motion and
transitions (no dip-to-black, anti-jitter), rendered in GPU-accelerated Chromium; FFmpeg then
muxes the treated narration and burns **single-line captions** (libass, ≤48 chars). The older
**FFmpeg-first** Ken Burns path (`hybrid`/`ffmpeg`) and the full-Remotion `remotion` path remain
as selectable engines (the FFmpeg path is faster but can't do flip/clockWipe/glow).

All comments, docstrings, logs, and skill prompts are in **Portuguese (pt-BR)**. The
generated *content* (roteiro, prompts) is in English. Match this when editing.

## Memory — ALWAYS keep these updated

This repo has a built-in "second brain" + change log. **After any non-trivial change**
(new file, behavior/config change, decision, connecting a seam), you MUST:

1. Prepend a dated entry to [MEMORIA.md](MEMORIA.md) (newest on top — use the template there).
2. Update the relevant file under [cerebro/](cerebro/) if the *state* changed:
   [estado-atual.md](cerebro/estado-atual.md) (what works / what's pending),
   [decisoes.md](cerebro/decisoes.md) (why), [pendencias.md](cerebro/pendencias.md) (TODOs),
   [ideias.md](cerebro/ideias.md) (future ideas).

`MEMORIA.md` = the timeline (what changed, when). `cerebro/` = the stable state (how things
are now, why). Don't duplicate this CLAUDE.md — it's operating instructions for Claude.

## Commands

Run from the repo root. The orchestrator uses the Windows `py -3` launcher.

```powershell
# One-click GUI (Tkinter): card name or existing project
py -3 longform/orchestrator/gerar-longform.py "Alpha King"

# CLI: full pipeline with gates
py -3 longform/orchestrator/pipeline.py "Alpha King"
# CLI: run only specific stages (1-8) of an existing project
py -3 longform/orchestrator/pipeline.py --slug meu-video 5 6 7
# CLI: fully automatic, no gates (end-to-end tests)
py -3 longform/orchestrator/pipeline.py "Alpha King" --no-gates
# CLI: hint which ClickUp List holds the card
py -3 longform/orchestrator/pipeline.py "Alpha King" --list-hint "Romance Longform"
# CLI: use a READY script from the card's linked Doc (skips Stage 2 generation)
py -3 longform/orchestrator/pipeline.py "Alpha King" --roteiro-pronto

# Stage 8 engine is selected by an env var:
#   LONGFORM_RENDER_ENGINE = dynamic (default) | hybrid | ffmpeg | remotion
#   LONGFORM_CAPTIONS      = 1 to burn captions (default: ON; set 0 to disable)
# dynamic = Remotion DynamicGallery (random gallery) -> out/video_mudo.mp4, then FFmpeg
#   `--finalizar` muxes treated audio + burns single-line captions (libass, ≤48 chars; long
#   SRT cues are sliced into several short one-line cues). Render-accel envs (defaults aggressive):
#   LONGFORM_REMOTION_GL=angle (GPU), _HWACCEL=if-possible (NVENC), _CONCURRENCY=<cores>.
# hybrid/ffmpeg = FFmpeg burns captions (subtitles/libass) — no Remotion needed for them.
# FFmpeg must be on PATH. The FFmpeg base build can be run standalone:
py -3 longform/orchestrator/ffmpeg_montagem.py "longform/projects/<slug>"
# Burn narration.srt onto an existing base.mp4 standalone:
py -3 longform/orchestrator/ffmpeg_montagem.py "longform/projects/<slug>" --burn-subs \
    --in out/base.mp4 --out out/final.mp4 --srt narration.srt

# Remotion (run inside longform/remotion/ after a pipeline run produced public/<slug>/)
cd longform/remotion && npm install
npx remotion studio            # preview (compositions: LongForm, LongFormOverlay)
npm run render                 # renders LongForm -> out/final.mp4 (legacy full-Remotion)

# CapCut TTS sidecar (longform/tts/CapCut-TTS/) — Express + TypeScript
cd longform/tts/CapCut-TTS && npm install
npm run dev                    # tsx watch
npm run build                  # tsc + tsc-alias
npm run typecheck              # tsc --noEmit
npm run lint                   # eslint (lint:fix to autofix)
```

There is **no git repo, no test suite, and no Python lint config** here. Verification is
end-to-end via `--no-gates`, not unit tests.

## Architecture

### The 9-stage pipeline (+ 3 gates)

[orchestrator/pipeline.py](longform/orchestrator/pipeline.py) is the conductor. Each
stage is a module in [orchestrator/stages/](longform/orchestrator/stages/) exposing a
`run(proj, log, cancel, **kw)` function. **Every stage is idempotent** — it checks if its
output artifact already exists and skips if so. This is what makes `--slug X 5 6 7`
(resume from a partial project) work.

```
1 ClickUp      s1_clickup      -> source.json            (MCP ClickUp, Sonnet, read-only)
2 Roteiro      s2_roteiro      -> roteiro.txt            (skill longform-roteiro, Opus; expansion loop to ~5000 words)
3 Validador    s3_validar      -> roteiro_validacao.json (skill longform-validar, Opus; scores + auto-fixes in place)
  ── GATE 1 (panel): approve/edit roteiro before spending TTS/image budget
4 Narração+SRT s4_narracao_srt -> narration.mp3 + .srt   (TTS seam + Whisper transcription)
5 Style/Thumb  s5_prompts_img  -> style_bible.txt + prompts_thumbnail.txt (1 prompt = a capa) (skill longform-prompts-img, Sonnet)
6 Thumb        s6_thumbnails   -> thumbs/thumb_01.png (a CAPA única, Magnific seam)
  ── GATE 2 (panel): validate the single thumb -> thumb_selected.png
7 Imagens      s7_imagens      -> prompts_imagens.txt + images/img_000.png (a CAPA = 1ª imagem do vídeo, cópia da thumb) + img_001..008.png (8 imagens FIXAS = corpo, anchored to thumb)
8 Montagem     s8_montagem     -> mapping.json -> out/base.mp4 (FFmpeg) -> out/final.mp4 (hybrid: +Remotion overlay)
9 Publicação   s9_publicacao   -> publicacao.json (skill longform-publicacao, Sonnet) + out/final_upload.mp4 (compressor NVENC) + publicacao/fila/<slug>.json (enqueue)
  ── GATE 3 (panel, no PUBLICADOR): review/edit título+descrição+tags before upload
```

**Publication (Stage 9 + publisher, 2026-07-09)** — closes the pipeline into YouTube. **Stage 9**
([s9_publicacao.py](longform/orchestrator/stages/s9_publicacao.py), idempotent, no browser) generates
metadata (title/description/tags/hashtags EN → `publicacao.json`), compresses the video
([compressor.py](longform/orchestrator/compressor.py), NVENC/GPU reusing `ffmpeg_montagem._encoder`,
only if `> LONGFORM_COMPRIMIR_LIMIAR_GB`, else hardlink → `out/final_upload.mp4`) and **enqueues**
`publicacao/fila/<slug>.json`. The **publisher** ([publicador.py](longform/orchestrator/publicador.py),
a separate worker — GUI button "Publicar fila" or `py -3 publicador.py`) drains the queue: **Gate 3**
(panel) → AdsPower profile per channel ([adspower.py](longform/orchestrator/adspower.py), Local API
:50325) → Playwright `connect_over_cdp` (`contexts[0]`, logged-in) → YouTube Studio (upload + metadata
+ "not made for kids" + **Schedule** at the next slot). Schedule in [agenda.py](longform/orchestrator/agenda.py):
1/day 18:00 US Pacific, per-channel ledger. **Channel = category**: `adspower_user_id`/`youtube_canal`
in [categorias.py](longform/orchestrator/categorias.py) (env `LONGFORM_ADSPOWER_<CHANNEL>`). Uses
YouTube's **native scheduling** (YT publishes on the date; PC only on during upload). ⚠ Studio selectors
are UI-fragile (English UI) and need live calibration; requires Playwright installed and a **paid**
AdsPower with the Local API on. Run `publicador.py --bridge <id>` then `--dry-run` on a test channel first.

**Roteiro pronto (2026-06-22)** — option `--roteiro-pronto` (GUI checkbox "Roteiro pronto no card")
makes Stage 1 also pull the FINISHED script from a Doc linked in the card (Google Doc via
`export?format=txt`, needs "anyone with link"; or ClickUp Doc via `clickup_*_document_pages`) and save
it as `roteiro.txt` → Stage 2 generation is skipped (idempotent). If the Doc can't be fetched, Stage 1
**fails loud** (it won't silently generate). Stage 3 (validador) still runs (structural fixes only).
The ready script may be in a DIFFERENT language than the video: `s2_roteiro.traduzir_se_preciso()`
detects PT vs EN (accent density) and, when it differs from the target `idioma()`, translates the
script to the target before narration (so audio AND captions come out right) — e.g. PT Doc + EN video
→ PT→EN before TTS. No-op/idempotent when they already match. Model via `LONGFORM_MODELO_TRADUZIR`.

### Key abstractions

- **`Projeto` ([common.py](longform/orchestrator/common.py))** — every project lives in
  `longform/projects/<Canal>/<slug>/` (per-channel layout since 2026-07-10: `Selena 1`,
  `Selena 2`, `Mafia 1`..`Mafia 4`; the flat `projects/<slug>/` still resolves as a legacy
  fallback). The channel folder name is `categorias.pasta_canal(<categoria>)`; a new project is
  created under its channel by `pipeline._garantir_projeto` (from the card's `categoria`). Project
  discovery is channel-aware via `common.achar_pasta_projeto(slug)` (used by `projeto_por_slug`
  and `projeto_mais_recente`), so `--slug X` keeps working regardless of channel. The `Projeto`
  class is the single source of truth for artifact filenames (`proj.roteiro`,
  `proj.narration_srt`, `proj.thumb_selected`, …). Add new artifacts as properties here, not as
  string literals in stages. `slugify()` derives `<slug>` from the card title.

- **`runner.py`** — the headless engine. `rodar_claude(prompt, pasta, ...)` spawns
  `claude -p --output-format stream-json --permission-mode acceptEdits --allowedTools ...`,
  streams events into the log, and retries transient API errors (overload/429/529/timeout)
  with backoff **without downgrading the model**. It strips `ANTHROPIC_API_KEY` from the
  env to force the user's Claude Code login (not paid API). `rodar_script()` runs the
  mechanical `.py` helpers (Whisper, build-mapping).

- **Skills as master prompts** — creative stages read a skill markdown file from
  `~/.claude/commands/<name>.md` (frontmatter stripped), prepend the headless `PREAMBULO`
  ("no questions, save the file, don't pause"), and pass it as the prompt. The skills
  `longform-roteiro`, `longform-validar`, `longform-prompts-img` contain a
  **"PROMPT MESTRE (inserir)"** block the user fills with their own master prompts. To
  change generation behavior, edit the skill, not the stage.

- **Model tiering** ([runner.py](longform/orchestrator/runner.py) constants) — Opus for
  the creative/judgment work (roteiro, validador), Sonnet for the mechanical reads
  (ClickUp, prompt derivation). Keep this split when adding stages.

- **Seams for external services** — anything not yet wired is isolated behind a seam so
  the rest of the pipeline is stable:
  - **TTS** ([s4_narracao_srt.py](longform/orchestrator/stages/s4_narracao_srt.py)):
    `synthesize()` shells out to `LONGFORM_TTS_CMD` (template with `{texto} {voz} {saida}`).
    The bundled `longform/tts/CapCut-TTS/` (an Express wrapper for CapCut Web TTS) is the
    documented fallback provider.
  - **Magnific** ([magnific_seam.py](longform/orchestrator/stages/magnific_seam.py)):
    image generation runs as a `claude -p` that uses the Magnific MCP. Set
    `LONGFORM_MAGNIFIC_MCP` to the server prefix (e.g. `mcp__<id>`); the seam allows
    `<prefix>__*` tools.
  - **Whisper**: reuses `gerar-srt-en.py` from the TINAGO project (`TINAGO_DIR`, default
    `%USERPROFILE%\TINAGO AUTOMAÇÃO`). The SRT is generated *from the narration audio*, so
    timestamps are real.

- **Gates** ([gates.py](longform/orchestrator/gates.py) + [panel/app.py](longform/panel/app.py))
  — `run_gate()` spins up a stdlib `http.server` on `127.0.0.1`, opens the browser, and
  **blocks** until the user posts a decision (or cancels). Gate 1 approves `roteiro.txt`
  (the user may hand-edit it first); Gate 2 copies the clicked thumb to
  `thumb_selected.png`. `--no-gates` skips Gate 1 and auto-picks the first thumb.

### The assembly (Stage 8)

[s8_montagem.py](longform/orchestrator/stages/s8_montagem.py) is the conductor; the engine
is chosen by `LONGFORM_RENDER_ENGINE` (`dynamic` default | `hybrid` | `ffmpeg` | `remotion`).

**`dynamic` (default, 2026-06-20)** — build-mapping still produces `mapping.json`, but the
[DynamicGallery](longform/remotion/src/components/DynamicGallery.tsx) composition ignores the
Ken Burns per-segment data and instead derives the unique image list and builds its OWN random
timeline: full-bleed images in **random order (never repeating the previous image)**, **random
continuous motion** (5 seeded effects, 3s sine loop so it never freezes), **random transitions**
(fade/slide/wipe/flip/clockWipe — **dip-to-black banned**). Everything is seeded → deterministic
(else the video flickers across the multi-process render). Remotion renders a **silent**
`out/video_mudo.mp4` (GPU `--gl=angle` + NVENC `--hardware-acceleration` + `--concurrency`), then
`ffmpeg_montagem.py --finalizar` (`finalizar_video()`) muxes the treated narration + burns the
single-line captions in one encode → `out/final.mp4`. Slower than FFmpeg (Chromium per frame) but
the only path that does flip/clockWipe/glow. The FFmpeg-first path below is the alternate engine.

1. [build-mapping.py](longform/orchestrator/build-mapping.py) groups `narration.srt` cues
   into N segments (N = image count), assigning each segment one image + a deterministic
   Ken Burns effect/pan (no randomness — reproducible). Output: `mapping.json` — the single
   source of truth for the timeline, shared by both FFmpeg and Remotion.
2. **FFmpeg** ([ffmpeg_montagem.py](longform/orchestrator/ffmpeg_montagem.py)) reads
   `mapping.json` and builds `out/base.mp4`: one Ken Burns clip per take via `zoompan` with
   **ease-in-out (smoothstep) motion** (`_ease()`, so zoom/pan accelerate and decelerate
   smoothly — the "cinematic/elegant" feel), fade-through-black on the edges, concatenated
   back-to-back at each take's `durationInFrames`, then muxed with `narration.mp3`. This is
   the fast path — no Chromium. **Timing is identical** to the old Remotion render, so audio
   stays SRT-synced.
3. **Captions (default)** are burned by **FFmpeg itself**, not Remotion: when captions are on
   (`engine=hybrid|ffmpeg`), `queimar_legendas()` (CLI `--burn-subs`) renders `narration.srt`
   over `base.mp4` via the `subtitles`/libass filter (`LEGENDA_STYLE`), re-encoding only the
   video and copying the audio → `out/final.mp4`. `base.mp4` stays caption-free (reusable), so
   toggling captions never re-runs Ken Burns. No captions → `base.mp4` **is** the final (copied).
4. **Remotion** only runs for the legacy/advanced path:
   - `engine=remotion` (legacy/fallback): Remotion draws everything in Chromium via the
     `LongForm` composition (stages audio + images, not `base.mp4`).
   - The `LongFormOverlay` composition ([Overlay.tsx](longform/remotion/src/Overlay.tsx)) is
     kept for rich React overlays in the Studio but is **no longer** the default caption path.
   Both compositions are registered in [Root.tsx](longform/remotion/src/Root.tsx); their
   `calculateMetadata` loads `mapping.json` and sizes the composition (1920x1080, 30fps).

**FFmpeg must be on PATH** (`achar_ffmpeg()` in [common.py](longform/orchestrator/common.py)).
When you change `mapping.json`'s shape, update [build-mapping.py](longform/orchestrator/build-mapping.py),
[ffmpeg_montagem.py](longform/orchestrator/ffmpeg_montagem.py),
[remotion/src/types.ts](longform/remotion/src/types.ts) and the compositions together.

## Conventions

- **Idempotency is the contract.** A stage must produce its artifact and skip cleanly if
  it already exists — never re-run expensive generation unconditionally.
- **No silent truncation.** When bounding cost (e.g. the fixed `N_IMAGENS` count in
  [s7_imagens.py](longform/orchestrator/stages/s7_imagens.py)), `log()` it.
- **Fail with `ErroPipeline`** and an actionable message (which env var to set, which
  stage to run first) — these surface directly in the GUI/CLI.
- **Image consistency** flows thumb → video images: Stage 7 reads `thumb_selected.png` as
  visual truth so characters stay consistent across the whole video. Preserve that anchor.
- **One run per project.** `pipeline()` ([pipeline.py](longform/orchestrator/pipeline.py)) takes a
  `<project>/.running` PID lock at start and releases it in `finally`; a 2nd run on the same slug
  while one is live is **refused** (running/continuing the same card twice corrupts shared outputs
  like two `remotion render` writing the same `video_mudo.mp4`). Stale locks (dead PID) are
  auto-overwritten. Don't remove this without another guard.
- **Verificar antes de entregar.** Toda correção de código (orchestrator, helpers `.py`,
  Remotion/TS, skills) precisa passar pelo subagente
  [`verificador-correcoes`](.claude/agents/verificador-correcoes.md) ANTES de ser reportada
  como pronta: ele analisa o diff e **executa de verdade** (`py_compile`/import, `npm run
  typecheck`, etapa da esteira via `./longform-mac.sh --slug <slug> N`, `--doctor`, inspeção
  do artefato de saída e teste de idempotência) e só libera com a evidência real da execução
  colada. Nada de "deve funcionar" — sem prova de execução, a correção não está verificada.
- **Corrigir pela raiz, sempre.** Todo bug se conserta na causa (a etapa/função/dado que o
  origina), nunca com remendo que só cala o sintoma (except que engole erro, `if` defensivo
  mascarando `None`, valor chumbado, retry disfarçando corrida, editar o artefato à mão em vez
  da etapa que o gera). O `verificador-correcoes` **reprova** remendo mesmo com teste verde e
  exige que a correção reproduza a condição original e prove que o problema não volta. Isso é o
  que destrava a automação de vez em vez de recair no mesmo defeito.
