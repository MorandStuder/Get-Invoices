#!/usr/bin/env python3
"""
Script d'initialisation du projet Amazon Invoice Downloader.
Crée la structure nécessaire et configure l'environnement.
"""
import os
import subprocess
import sys
from pathlib import Path


def create_directories() -> None:
    """Crée les répertoires nécessaires."""
    directories = [
        "backend/services",
        "backend/models",
        "frontend/src/components",
        "frontend/src/services",
        "frontend/public",
        "tests",
        "factures",
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✓ Répertoire créé: {directory}")


def check_env_file() -> None:
    """Vérifie si le fichier .env existe."""
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if not env_file.exists():
        if env_example.exists():
            print("⚠️  Le fichier .env n'existe pas.")
            print("   Copiez .env.example vers .env et remplissez vos identifiants.")
        else:
            print("⚠️  Aucun fichier .env trouvé. Créez-en un avec vos identifiants.")
    else:
        print("✓ Fichier .env trouvé")


def install_python_dependencies() -> None:
    """Installe les dépendances Python."""
    print("\n📦 Installation des dépendances Python...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✓ Dépendances Python installées")
    except subprocess.CalledProcessError:
        print("⚠️  Erreur lors de l'installation des dépendances Python")
        print("   Exécutez manuellement: pip install -r requirements.txt")


def install_node_dependencies() -> None:
    """Installe les dépendances Node.js."""
    frontend_dir = Path("frontend")
    if not frontend_dir.exists():
        print("⚠️  Le répertoire frontend n'existe pas")
        return
    
    print("\n📦 Installation des dépendances Node.js...")
    try:
        os.chdir("frontend")
        subprocess.check_call(
            ["npm", "install"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        os.chdir("..")
        print("✓ Dépendances Node.js installées")
    except subprocess.CalledProcessError:
        os.chdir("..")
        print("⚠️  Erreur lors de l'installation des dépendances Node.js")
        print("   Exécutez manuellement: cd frontend && npm install")
    except FileNotFoundError:
        print("⚠️  npm n'est pas installé. Installez Node.js pour utiliser le frontend")


def main() -> None:
    """Fonction principale."""
    print("🚀 Initialisation du projet Amazon Invoice Downloader\n")
    
    create_directories()
    check_env_file()
    install_python_dependencies()
    install_node_dependencies()
    
    print("\n✅ Initialisation terminée!")
    print("\nProchaines étapes:")
    print("1. Créez un fichier .env avec vos identifiants Amazon")
    print("2. Lancez le backend: cd backend && uvicorn main:app --reload")
    print("3. Lancez le frontend: cd frontend && npm start")


if __name__ == "__main__":
    main()

