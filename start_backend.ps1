# Nettoyage des anciens logs
Remove-Item -Path logs\app.log -ErrorAction SilentlyContinue

# Configuration de l'environnement
Set-Location "C:\Users\moran\Dropbox\GitHub\Get-Invoices"
$env:PYTHONPATH = '.'

Write-Host '========================================'  -ForegroundColor Cyan
Write-Host '  Backend FastAPI - Port 8000          ' -ForegroundColor Cyan
Write-Host '========================================'  -ForegroundColor Cyan
Write-Host ''
Write-Host 'API: http://localhost:8000' -ForegroundColor Green
Write-Host 'Docs: http://localhost:8000/docs' -ForegroundColor Green
Write-Host ''
Write-Host 'Mode manuel activé - Chrome va s ouvrir' -ForegroundColor Yellow
Write-Host ''

# Lancement du backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
