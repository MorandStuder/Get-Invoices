# Script PowerShell pour arrêter le backend et le frontend
# Usage: .\stop.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Amazon Invoice Downloader - Stop     " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Fonction pour tuer les processus qui ECOUTENT sur un port (LISTENING, adresse locale uniquement)
function Kill-ProcessOnPort {
    param($Port, $Name)
    $currentPID = $PID
    $pids = @()
    $lines = netstat -ano | Select-String "LISTENING"
    foreach ($l in $lines) {
        $lineStr = if ($l.Line) { $l.Line } else { $l.ToString() }
        if ($lineStr -match "(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):$Port\s" -and $lineStr -match "\s+(\d+)\s*$") {
            $pids += [int]$Matches[1]
        }
    }
    $pids = $pids | Sort-Object -Unique | Where-Object { $_ -gt 0 -and $_ -ne $currentPID }
    if ($pids) {
        Write-Host "-> Arret du $Name (PIDs: $($pids -join ', '))..." -ForegroundColor Yellow
        foreach ($p in $pids) {
            cmd /c "taskkill /F /PID $p /T 2>nul"
        }
        Start-Sleep -Seconds 4
        Write-Host "OK $Name arrete" -ForegroundColor Green
    } else {
        Write-Host "Info: Aucun processus sur le port $Port" -ForegroundColor Gray
    }
}

# Arreter le backend (port 8001)
Kill-ProcessOnPort 8001 "Backend"

# Arrêter le frontend (port 3000)
Kill-ProcessOnPort 3000 "Frontend"

Write-Host ""
Write-Host "OK Application arretee avec succes!" -ForegroundColor Green
Write-Host ""
