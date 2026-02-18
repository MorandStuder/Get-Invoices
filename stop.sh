#!/bin/bash
# Script Bash pour arrêter le backend et le frontend
# Usage: ./stop.sh

echo "========================================"
echo "  Amazon Invoice Downloader - Stop     "
echo "========================================"
echo ""

# Fonction pour tuer les processus sur un port
kill_port() {
    local port=$1
    local name=$2
    local pid=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        echo "→ Arrêt du $name (PID: $pid)..."
        kill -9 $pid 2>/dev/null
        echo "✓ $name arrêté"
    else
        echo "ℹ Aucun processus trouvé sur le port $port"
    fi
}

# Arrêter le backend (port 8000)
kill_port 8000 "Backend"

# Arrêter le frontend (port 3000)
kill_port 3000 "Frontend"

# Supprimer les fichiers PID
rm -f logs/backend.pid logs/frontend.pid

echo ""
echo "✓ Application arrêtée avec succès!"
echo ""
