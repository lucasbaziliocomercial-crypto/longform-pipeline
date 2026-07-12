# Liga a Etapa 4 da esteira long-form ao TTS do CapCut (voz Joanne).
# Rode ANTES de chamar a pipeline, na MESMA sessão do PowerShell:
#     . .\longform\tts\set-tts-env.ps1
# (o ponto-espaco no comeco faz as variaveis valerem na sua sessao)

$adapter = Join-Path $PSScriptRoot "..\orchestrator\capcut_tts.py"
$adapter = (Resolve-Path $adapter).Path

$env:LONGFORM_TTS_CMD   = "py -3 `"$adapter`" --text `"{texto}`" --voice `"{voz}`" --out `"{saida}`""
$env:LONGFORM_TTS_VOICE = "XMWzAzwYm487GEok2uG2"   # Joanne

Write-Host "OK - Etapa 4 ligada ao CapCut TTS (Joanne)." -ForegroundColor Green
Write-Host "  LONGFORM_TTS_CMD   = $env:LONGFORM_TTS_CMD"
Write-Host "  LONGFORM_TTS_VOICE = $env:LONGFORM_TTS_VOICE (Joanne)"
