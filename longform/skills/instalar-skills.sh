#!/usr/bin/env bash
# instalar-skills.sh — copia os skills do repo para o perfil do usuário (macOS/Linux).
#
# Por que existe: o orquestrador lê as skills de ~/.claude/commands
# (common.py: COMMANDS_DIR = Path.home()/".claude"/"commands"), que fica FORA do repo.
# Ao clonar/copiar a pasta do projeto em outra máquina, as skills não vão junto.
# Este script leva a cópia versionada em longform/skills/ para o lugar certo.
#
# Uso (da pasta longform/skills/ ou de qualquer lugar):
#   ./instalar-skills.sh
set -euo pipefail

ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINO="$HOME/.claude/commands"

echo "Instalando skills long-form em: $DESTINO"
mkdir -p "$DESTINO"

for f in longform-roteiro longform-roteiro-mafia longform-validar \
         longform-prompts-img longform-thumb-mafia longform-humanizar-narracao; do
  cp -f "$ORIGEM/$f.md" "$DESTINO/$f.md"
done

echo "OK — 6 skills copiadas. Confira:"
ls -1 "$DESTINO"/longform-*.md
