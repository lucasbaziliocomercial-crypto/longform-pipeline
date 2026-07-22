@echo off
REM instalar-skills.bat - copia os skills do repo para o perfil do usuario (Windows).
REM
REM Por que existe: o orquestrador le as skills de %USERPROFILE%\.claude\commands
REM (common.py: COMMANDS_DIR = Path.home()/".claude"/"commands"), que fica FORA do repo.
REM Ao passar a pasta do projeto para outro PC, as skills nao vao junto. Este script
REM leva a copia versionada em longform\skills\ para o lugar certo.
REM
REM Uso (duplo-clique OU no cmd, a partir desta pasta):
REM   instalar-skills.bat
setlocal
set "ORIGEM=%~dp0"
set "DESTINO=%USERPROFILE%\.claude\commands"

echo Instalando skills long-form em: %DESTINO%
if not exist "%DESTINO%" mkdir "%DESTINO%"

copy /Y "%ORIGEM%longform-roteiro.md"             "%DESTINO%\" >nul
copy /Y "%ORIGEM%longform-roteiro-mafia.md"       "%DESTINO%\" >nul
copy /Y "%ORIGEM%longform-validar.md"             "%DESTINO%\" >nul
copy /Y "%ORIGEM%longform-prompts-img.md"         "%DESTINO%\" >nul
copy /Y "%ORIGEM%longform-thumb-mafia.md"         "%DESTINO%\" >nul
copy /Y "%ORIGEM%longform-humanizar-narracao.md"  "%DESTINO%\" >nul

echo.
echo OK - 6 skills copiadas. Confira:
dir /b "%DESTINO%\longform-*.md"
endlocal
pause
