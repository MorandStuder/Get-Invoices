# Script PowerShell pour lancer automatiquement le backend et le frontend
# Usage: .\start.ps1              -> 3 fenetres (celle-ci + backend + frontend)
#        .\start.ps1 -SingleWindow -> tout dans le terminal courant (ideal pour Cursor : backend en arriere-plan, frontend au premier plan)
param([switch]$SingleWindow)

# S'assurer d'etre dans le dossier du script (racine du projet)
$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location | Select-Object -ExpandProperty Path }
Set-Location -Path $scriptRoot -ErrorAction SilentlyContinue

# Vérifier que nous sommes dans le bon dossier
if (-not (Test-Path ".\backend\main.py")) {
    Write-Host "ERREUR: Ce script doit etre execute depuis la racine du projet Get-Invoices" -ForegroundColor Red
    exit 1
}

# Vérifier que le fichier .env existe
if (-not (Test-Path ".\.env")) {
    Write-Host "ERREUR: Fichier .env non trouve!" -ForegroundColor Red
    Write-Host "Copiez .env.example vers .env et configurez vos identifiants" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Commande: Copy-Item .env.example .env" -ForegroundColor Yellow
    exit 1
}

# Lire START_SINGLE_WINDOW depuis .env si le switch n'a pas ete passe en ligne de commande
if (-not $SingleWindow) {
    $envLines = Get-Content ".\.env" -Encoding UTF8 -ErrorAction SilentlyContinue
    foreach ($line in $envLines) {
        $line = $line.Trim()
        if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -match '^START_SINGLE_WINDOW\s*=\s*(.+)$') {
            $val = $Matches[1].Trim().Trim('"').Trim("'").ToLowerInvariant()
            if ($val -in 'true', '1', 'yes', 'on') {
                $SingleWindow = $true
                break
            }
        }
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Amazon Invoice Downloader - Startup  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
if (-not $SingleWindow) {
    Write-Host "  (Pour tout garder dans ce terminal: .\start.ps1 -SingleWindow ou START_SINGLE_WINDOW=true dans .env)" -ForegroundColor Gray
}
Write-Host ""

# Vérifier que Python est installé
try {
    $pythonVersion = python --version 2>&1
    Write-Host "OK Python detecte: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERREUR: Python non installe ou absent du PATH" -ForegroundColor Red
    exit 1
}

# Vérifier que Node.js est installé
try {
    $nodeVersion = node --version 2>&1
    Write-Host "OK Node.js detecte: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "ERREUR: Node.js non installe ou absent du PATH" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Demarrage des serveurs..." -ForegroundColor Cyan
Write-Host ""

# Fonction pour tuer les processus qui ECOUTENT sur un port (LISTENING uniquement, jamais le processus courant)
function Kill-ProcessOnPort {
    param($Port)
    $currentPID = $PID
    $pids = @()
    # Uniquement netstat LISTENING avec adresse locale :Port (pas les clients qui se connectent au port)
    $lines = netstat -ano | Select-String "LISTENING"
    foreach ($l in $lines) {
        $lineStr = if ($l.Line) { $l.Line } else { $l.ToString() }
        if ($lineStr -match "(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):$Port\s" -and $lineStr -match "\s+(\d+)\s*$") {
            $pids += [int]$Matches[1]
        }
    }
    $pids = $pids | Sort-Object -Unique | Where-Object { $_ -gt 0 -and $_ -ne $currentPID }
    if ($pids) {
        Write-Host "Arret du processus existant sur le port $Port (PIDs: $($pids -join ','))..." -ForegroundColor Yellow
        foreach ($p in $pids) {
            cmd /c "taskkill /F /PID $p /T 2>nul"
        }
        Start-Sleep -Seconds 4
    }
}

# Backend sur 8001 pour eviter conflit avec Cursor/autres outils qui utilisent 8000
$backendPort = 8001
# Liberer les ports 8001 et 3000
foreach ($attempt in 1..2) {
    Kill-ProcessOnPort $backendPort
    Kill-ProcessOnPort 3000
    Start-Sleep -Seconds 2
    $onPort = netstat -ano | Select-String "LISTENING" | Where-Object { $_.Line -match "(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):$backendPort\s" }
    if (-not $onPort) { break }
    if ($attempt -eq 1) {
        Write-Host "Port $backendPort encore occupe, nouvel essai..." -ForegroundColor Yellow
    }
}
$stillInUse = netstat -ano | Select-String "LISTENING" | Where-Object { $_.Line -match "(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):$backendPort\s" }
if ($stillInUse) {
    Write-Host "Le port $backendPort est encore utilise. Lancez .\stop.ps1 puis reessayez." -ForegroundColor Red
    exit 1
}

# Creer un fichier de log
$logDir = "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$backendJob = $null
if ($SingleWindow) {
    # Mode 1 fenetre : backend en arriere-plan (logs dans logs/backend.log)
    # Passer PATH et VIRTUAL_ENV au job pour utiliser le meme Python/venv que la session courante
    $jobPath = $env:PATH
    $jobVirtualEnv = $env:VIRTUAL_ENV
    $backendLog = "$logDir\backend.log"
    Write-Host "-> Demarrage du backend en arriere-plan (port $backendPort)..." -ForegroundColor Yellow
    Write-Host "   En cas d'echec, consultez les logs: $backendLog" -ForegroundColor Gray
    $backendJob = Start-Job -ScriptBlock {
        param($workDir, $port, $logFile, $pathEnv, $venvEnv)
        Set-Location -LiteralPath $workDir
        $env:PYTHONPATH = '.'
        if ($pathEnv) { $env:PATH = $pathEnv }
        if ($venvEnv) { $env:VIRTUAL_ENV = $venvEnv }
        # Lancer via cmd pour eviter que le stderr d'uvicorn (logs INFO) declenche NativeCommandError dans PowerShell
        cmd /c "python -m uvicorn backend.main:app --host 0.0.0.0 --port $port 2>&1" | Tee-Object -FilePath $logFile
    } -ArgumentList $PWD.Path, $backendPort, (Join-Path $PWD $backendLog), $jobPath, $jobVirtualEnv
    Start-Sleep -Seconds 8
} else {
    # Mode 3 fenetres : backend dans une nouvelle fenetre (pour voir les logs)
    Write-Host "-> Demarrage du backend FastAPI (port $backendPort) dans une nouvelle fenetre..." -ForegroundColor Yellow
    $backendScript = @"
Set-Location '$PWD'
`$env:PYTHONPATH = '.'
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Backend FastAPI - Port $backendPort          ' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'API: http://localhost:$backendPort' -ForegroundColor Green
Write-Host 'Docs: http://localhost:$backendPort/docs' -ForegroundColor Green
Write-Host ''
python -m uvicorn backend.main:app --host 0.0.0.0 --port $backendPort --reload
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendScript
}

# Attendre que le backend demarre (lifespan peut prendre 10-20 s)
Write-Host "Attente du demarrage du backend (jusqu'a 60 s)..." -ForegroundColor Yellow
$maxRetries = 60
$retries = 0
$backendReady = $false
$backendUrl = "http://127.0.0.1:$backendPort/"

while ($retries -lt $maxRetries) {
    try {
        $response = Invoke-WebRequest -Uri $backendUrl -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $backendReady = $true
            break
        }
    } catch {
        # Ignorer et reessayer
    }
    Start-Sleep -Seconds 1
    $retries++
    if ($retries % 10 -eq 0) { Write-Host " ${retries}s" -NoNewline }
    Write-Host "." -NoNewline
}

Write-Host ""

if (-not $backendReady) {
    Write-Host "ERREUR: Le backend n'a pas repondu a temps." -ForegroundColor Red
    if ($SingleWindow -and $backendLog) {
        Write-Host "  - Consultez le log du backend pour l'erreur: $backendLog" -ForegroundColor Yellow
    }
    Write-Host "  - Fermez la fenetre du backend si elle est ouverte, puis lancez .\stop.ps1" -ForegroundColor Yellow
    Write-Host "  - Relancez .\start.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "OK Backend demarre avec succes!" -ForegroundColor Green
Write-Host ""

# Demarrer le frontend
if ($SingleWindow) {
    Write-Host "-> Demarrage du frontend React (port 3000) dans cette fenetre..." -ForegroundColor Yellow
    Write-Host "   (Backend en arriere-plan ; logs: logs\backend.log)" -ForegroundColor Gray
    Write-Host "   Pour arreter: Ctrl+C (backend sera arrete aussi)" -ForegroundColor Gray
    Write-Host ""
    $env:BROWSER = 'none'
    $rootDir = Get-Location
    Set-Location "$PWD\frontend"
    Start-Job -ScriptBlock { Start-Sleep -Seconds 10; Start-Process 'http://localhost:3000' } | Out-Null
    try {
        npm start
    } finally {
        if ($backendJob) {
            Stop-Job $backendJob -ErrorAction SilentlyContinue
            Remove-Job $backendJob -Force -ErrorAction SilentlyContinue
            Write-Host "Backend arrete." -ForegroundColor Yellow
        }
        Set-Location $rootDir
    }
    exit 0
}

Write-Host "-> Demarrage du frontend React (port 3000) dans une nouvelle fenetre..." -ForegroundColor Yellow
$frontendScript = @"
Set-Location '$PWD\frontend'
`$env:BROWSER = 'none'
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Frontend React - Port 3000           ' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Application: http://localhost:3000' -ForegroundColor Green
Write-Host ''
npm start
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendScript

# Attendre que le frontend démarre
Write-Host "Attente du demarrage du frontend..." -ForegroundColor Yellow
$retries = 0
$frontendReady = $false

while ($retries -lt 60) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000/" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {
        # Ignorer les erreurs et réessayer
    }
    Start-Sleep -Seconds 1
    $retries++
    if ($retries % 5 -eq 0) {
        Write-Host "." -NoNewline
    }
}

Write-Host ""

if ($frontendReady) {
    Write-Host "OK Frontend demarre avec succes!" -ForegroundColor Green
} else {
    Write-Host "Attention: Le frontend met plus de temps a demarrer" -ForegroundColor Yellow
    Write-Host "Verifiez la fenetre du frontend pour le statut" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Application demarree avec succes!     " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "URLs disponibles:" -ForegroundColor White
Write-Host "  - Frontend:      http://localhost:3000" -ForegroundColor Green
Write-Host "  - Backend API:   http://localhost:$backendPort" -ForegroundColor Green
Write-Host "  - API Docs:      http://localhost:$backendPort/docs" -ForegroundColor Green
Write-Host ""
Write-Host "Pour arreter l'application, fermez les fenetres PowerShell du backend et du frontend" -ForegroundColor Yellow
Write-Host ""

# Ouvrir le navigateur
Write-Host 'Ouverture du navigateur...' -ForegroundColor Cyan
Start-Sleep -Seconds 2
Start-Process 'http://localhost:3000'

Write-Host ""
Write-Host 'Appuyez sur une touche pour fermer cette fenetre...' -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
