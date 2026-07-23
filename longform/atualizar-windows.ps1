# atualizar-windows.ps1 - traz as correcoes do GitHub para o PC (Windows) e deixa
# a esteira na MELHOR config para o teste real do video, num comando so.
#
# O que faz:
#   1) git pull --ff-only  (puxa as correcoes; nao mexe se houver historico divergente)
#   2) garante longform\longform.env (copia do .example se faltar; avisa se estiver com config de Mac)
#   3) npm install em longform\remotion (a engine 'dynamic' precisa do Remotion)
#   4) roda o --doctor (testar-conexoes.py) para confirmar claude/ffmpeg/Whisper/Magnific/TTS
#
# Uso (PowerShell, a partir de qualquer lugar):
#   .\longform\atualizar-windows.ps1
#   .\longform\atualizar-windows.ps1 -Card "Alpha King"   # ja roda a pipeline no fim
#   .\longform\atualizar-windows.ps1 -SkipPull -SkipNpm   # so revalidar o ambiente
#
# Se der "execution policy", rode uma vez:
#   powershell -ExecutionPolicy Bypass -File .\longform\atualizar-windows.ps1
#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Card,       # opcional: nome do card para rodar a pipeline logo apos o update
    [switch]$SkipPull,   # pula o git pull
    [switch]$SkipNpm     # pula o npm install do Remotion
)

$ErrorActionPreference = 'Stop'

function Titulo($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "[OK] $t"     -ForegroundColor Green }
function Aviso($t)  { Write-Host "[AVISO] $t"  -ForegroundColor Yellow }
function Erro($t)   { Write-Host "[ERRO] $t"   -ForegroundColor Red }

# raiz do repo = pasta-pai de longform\ (onde este script vive)
$Longform = $PSScriptRoot
$Raiz     = Split-Path $Longform -Parent
Set-Location $Raiz
Write-Host "Repo: $Raiz"

# --- 1) git pull -----------------------------------------------------------
Titulo "1/4  Atualizando o codigo (git pull)"
if ($SkipPull) {
    Aviso "pulado (-SkipPull)"
} else {
    & git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) { Erro "Nao e um repositorio git: $Raiz"; exit 1 }

    # avisa sobre mudancas locais em arquivos VERSIONADOS (o longform.env e gitignored, nao conta)
    $sujo = & git status --porcelain --untracked-files=no
    if ($sujo) {
        Aviso "Ha alteracoes locais nao commitadas em arquivos versionados:"
        $sujo | ForEach-Object { Write-Host "    $_" }
    }

    $antes = (& git rev-parse HEAD).Trim()
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Erro "git pull --ff-only falhou (historico divergente ou conflito)."
        Erro "Resolva a mao (git status / git pull --rebase) e rode de novo."
        exit 1
    }
    $depois = (& git rev-parse HEAD).Trim()
    if ($antes -eq $depois) {
        Ok "Ja estava atualizado (nenhum commit novo)."
    } else {
        Ok "Atualizado. Commits novos:"
        & git log --oneline "$antes..$depois" | ForEach-Object { Write-Host "    $_" }
    }
}

# --- 2) longform.env -------------------------------------------------------
Titulo "2/4  Config (longform.env)"
$envReal = Join-Path $Longform 'longform.env'
$envEx   = Join-Path $Longform 'longform.env.example'
if (-not (Test-Path $envReal)) {
    if (Test-Path $envEx) {
        Copy-Item $envEx $envReal
        Ok "longform.env criado do template (.example) com a config otima de producao (dynamic + NVENC auto)."
    } else {
        Aviso "longform.env.example nao encontrado - rode o git pull antes (passo 1)."
    }
} else {
    Ok "longform.env ja existe (mantido - nao sobrescrevo a sua config)."
    $conteudo = Get-Content $envReal -Raw
    if ($conteudo -match '(?im)^\s*LONGFORM_RENDER_ENGINE\s*=\s*ffmpeg') {
        Aviso "Seu longform.env esta com LONGFORM_RENDER_ENGINE=ffmpeg (config de Mac)."
        Aviso "  Para o teste real no PC, troque para: LONGFORM_RENDER_ENGINE=dynamic"
    }
    if ($conteudo -match '(?im)^\s*LONGFORM_FFMPEG_ENCODER\s*=\s*cpu') {
        Aviso "Seu longform.env esta com LONGFORM_FFMPEG_ENCODER=cpu (Mac, sem GPU)."
        Aviso "  Para usar a NVENC do PC, troque para: LONGFORM_FFMPEG_ENCODER=auto"
    }
}

# --- 3) Remotion (engine dynamic) -----------------------------------------
Titulo "3/4  Dependencias do Remotion (engine dynamic)"
if ($SkipNpm) {
    Aviso "pulado (-SkipNpm)"
} else {
    $remotion = Join-Path $Longform 'remotion'
    $nodeMods = Join-Path $remotion 'node_modules'
    if (-not (Test-Path $remotion)) {
        Aviso "Pasta longform\remotion nao encontrada - pulei."
    } elseif (Test-Path $nodeMods) {
        Ok "node_modules ja instalado."
    } else {
        Write-Host "Instalando (npm install em longform\remotion) - pode demorar alguns minutos..."
        Push-Location $remotion
        & npm install
        $rc = $LASTEXITCODE
        Pop-Location
        if ($rc -ne 0) { Aviso "npm install retornou erro ($rc) - confira se Node/npm estao instalados." }
        else { Ok "Remotion pronto." }
    }
}

# --- 4) doctor -------------------------------------------------------------
Titulo "4/4  Diagnostico do ambiente (--doctor)"
$doctor = Join-Path $Longform 'orchestrator\testar-conexoes.py'
& py -3 $doctor
$rcDoctor = $LASTEXITCODE
if ($rcDoctor -ne 0) { Aviso "O doutor apontou pendencias acima - resolva antes do teste real." }
else { Ok "Ambiente saudavel." }

# --- Pronto ----------------------------------------------------------------
Titulo "Pronto"
if ($Card) {
    Write-Host "Rodando a pipeline para o card: $Card"
    & py -3 (Join-Path $Longform 'orchestrator\pipeline.py') $Card
} else {
    Write-Host "Para comecar o teste real, rode um destes:"
    Write-Host "    py -3 longform\orchestrator\pipeline.py `"Nome do Card`"" -ForegroundColor Green
    Write-Host "    py -3 longform\orchestrator\gerar-longform.py            (GUI de um clique)" -ForegroundColor Green
}
