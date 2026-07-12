# Sobe o sidecar CapCut-TTS (kuwacom) em http://127.0.0.1:8080
# Pre-requisito: preencher CAPCUT_EMAIL e CAPCUT_PASSWORD no arquivo .env desta pasta.
Set-Location (Join-Path $PSScriptRoot "CapCut-TTS")
Write-Host "Subindo CapCut-TTS em http://127.0.0.1:8080 ... (Ctrl+C para parar)" -ForegroundColor Cyan
npm run dev
