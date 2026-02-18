#!/bin/bash
# Script Bash pour lancer automatiquement le backend et le frontend
# Usage: ./start.sh

echo "========================================"
echo "  Amazon Invoice Downloader - Startup  "
echo "========================================"
echo ""

# Vérifier que nous sommes dans le bon dossier
if [ ! -f "backend/main.py" ]; then
    echo "ERREUR: Ce script doit être exécuté depuis la racine du projet Get-Invoices"
    exit 1
fi

# Vérifier que le fichier .env existe
if [ ! -f ".env" ]; then
    echo "ERREUR: Fichier .env non trouvé!"
    echo "Veuillez copier .env.example vers .env et configurer vos identifiants"
    echo ""
    echo "Commande: cp .env.example .env"
    exit 1
fi

# Vérifier que Python est installé
if ! command -v python3 &> /dev/null; then
    echo "✗ Python3 n'est pas installé"
    exit 1
fi
echo "✓ Python détecté: $(python3 --version)"

# Vérifier que Node.js est installé
if ! command -v node &> /dev/null; then
    echo "✗ Node.js n'est pas installé"
    exit 1
fi
echo "✓ Node.js détecté: $(node --version)"

echo ""
echo "Démarrage des serveurs..."
echo ""

# Fonction pour tuer les processus sur un port
kill_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        echo "Arrêt du processus existant sur le port $port..."
        kill -9 $pid 2>/dev/null
        sleep 2
    fi
}

# Libérer les ports si nécessaire
kill_port 8000
kill_port 3000

# Créer un fichier de log
mkdir -p logs

# Démarrer le backend en arrière-plan
echo "→ Démarrage du backend FastAPI (port 8000)..."
export PYTHONPATH="."
nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > logs/backend.pid

# Attendre que le backend démarre
echo "Attente du démarrage du backend..."
max_retries=30
retries=0
backend_ready=false

while [ $retries -lt $max_retries ]; do
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        backend_ready=true
        break
    fi
    sleep 1
    retries=$((retries+1))
    echo -n "."
done

echo ""

if [ "$backend_ready" = false ]; then
    echo "✗ Le backend n'a pas démarré correctement"
    echo "Vérifiez logs/backend.log pour les erreurs"
    exit 1
fi

echo "✓ Backend démarré avec succès!"
echo ""

# Démarrer le frontend en arrière-plan
echo "→ Démarrage du frontend React (port 3000)..."
cd frontend
export BROWSER=none
nohup npm start > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
cd ..

# Attendre que le frontend démarre
echo "Attente du démarrage du frontend..."
retries=0
frontend_ready=false

while [ $retries -lt 60 ]; do
    if curl -s http://localhost:3000/ > /dev/null 2>&1; then
        frontend_ready=true
        break
    fi
    sleep 1
    retries=$((retries+1))
    if [ $((retries % 5)) -eq 0 ]; then
        echo -n "."
    fi
done

echo ""

if [ "$frontend_ready" = true ]; then
    echo "✓ Frontend démarré avec succès!"
else
    echo "⚠ Le frontend prend plus de temps que prévu à démarrer"
    echo "Vérifiez logs/frontend.log pour le statut"
fi

echo ""
echo "========================================"
echo "  Application démarrée avec succès!    "
echo "========================================"
echo ""
echo "URLs disponibles:"
echo "  • Frontend:      http://localhost:3000"
echo "  • Backend API:   http://localhost:8000"
echo "  • API Docs:      http://localhost:8000/docs"
echo ""
echo "Logs:"
echo "  • Backend:       logs/backend.log"
echo "  • Frontend:      logs/frontend.log"
echo ""
echo "Pour arrêter l'application, exécutez: ./stop.sh"
echo ""

# Ouvrir le navigateur (optionnel, peut ne pas fonctionner sur tous les systèmes)
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:3000 &
elif command -v open &> /dev/null; then
    open http://localhost:3000 &
fi
