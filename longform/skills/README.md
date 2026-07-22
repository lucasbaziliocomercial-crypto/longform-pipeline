# longform/skills — cópia versionada das skills (prompts mestres)

As skills criativas (Etapas 2, 3, 5) são lidas pelo orquestrador de
**`~/.claude/commands/`** (no Windows: `%USERPROFILE%\.claude\commands\`) —
ver `common.py`: `COMMANDS_DIR = Path.home()/".claude"/"commands"`.

Esse diretório fica **fora** da pasta do projeto. Por isso, ao copiar/passar o
repositório para outra máquina (ex.: o PC de produção Windows), as skills **não
iam junto** — inclusive o PROMPT MESTRE do roteiro Máfia (HELÔ STORIES™).

Esta pasta resolve isso: guarda a **cópia canônica** das skills dentro do repo,
para o projeto ser autossuficiente e transferível.

## Skills incluídas

| Arquivo | Etapa | Uso |
|---|---|---|
| `longform-roteiro.md` | 2 | Roteiro — canais Selena / Alpha King |
| `longform-roteiro-mafia.md` | 2 | Roteiro — canais Máfia (**HELÔ STORIES™**, dark romance, história única) |
| `longform-validar.md` | 3 | Valida e corrige o roteiro |
| `longform-prompts-img.md` | 5 | Character Bible + fichas + prompt da thumbnail |
| `longform-thumb-mafia.md` | 5 | Override de CAPA (thumbnail) da categoria Máfia (LENA) |
| `longform-humanizar-narracao.md` | 4 | Normaliza pontuação/cadência para o TTS |

## Instalar (levar para `~/.claude/commands/`)

**Windows** (duplo-clique ou no `cmd`, a partir desta pasta):
```
instalar-skills.bat
```

**macOS / Linux:**
```bash
./instalar-skills.sh
```

Ambos copiam os 6 `.md` para `~/.claude/commands/` (criando a pasta se preciso),
sobrescrevendo as versões antigas. Rode **sempre que atualizar uma skill** — ou
edite o `.md` aqui, rode o instalador, e a próxima geração já usa a versão nova.

## Fluxo de edição (fonte da verdade = esta pasta)

1. Edite o `.md` **aqui em `longform/skills/`** (fonte versionada).
2. Rode o instalador (`instalar-skills.bat` / `.sh`) para publicar em `~/.claude/commands/`.
3. Registre a mudança em `MEMORIA.md` (topo) e, se o estado mudou, em `cerebro/`.
