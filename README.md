# Téléchargeur de Factures Amazon

Programme automatisé pour télécharger vos factures Amazon. Ce projet comprend un backend FastAPI et un frontend React+TypeScript.

**Version 1.2 (V0)** — Connexion continue au navigateur, pagination des commandes, scripts et code nettoyés.

## ✨ Améliorations Récentes

Le projet a été entièrement audité et amélioré avec les corrections suivantes :

### 🔧 Corrections Critiques
- ✅ **ChromeDriver corrigé** - Le driver Selenium s'initialise maintenant correctement (problème de chemin résolu)
- ✅ **FastAPI modernisé** - Migration de `@app.on_event()` (déprécié) vers `lifespan` handlers
- ✅ **Configuration validée** - Encodage UTF-8 corrigé, espaces blancs supprimés, validation automatique au démarrage
- ✅ **TypeScript sans warnings** - Tous les types de retour ajoutés, interfaces inutilisées supprimées

### 🚀 Nouvelles Fonctionnalités
- ✅ **Scripts de lancement automatique** - Démarrage en un clic avec `start.ps1` (Windows) ou `start.sh` (Linux/Mac)
- ✅ **Validation de configuration** - Vérification automatique des variables d'environnement au démarrage
- ✅ **Scripts d'arrêt** - Arrêt propre de l'application avec `stop.ps1` ou `stop.sh`
- ✅ **Connexion continue au navigateur** - Option `SELENIUM_KEEP_BROWSER_OPEN` pour laisser le navigateur ouvert à l'arrêt de l'app (session conservée)
- ✅ **Passage à la page suivante des commandes** - Téléchargement sur toutes les pages d'historique (pagination automatique jusqu'à `MAX_INVOICES`)

### 🧪 Tests Améliorés
- ✅ **100% de tests passants** - 18/18 tests réussis (vs 4/5 avant)
- ✅ **Couverture augmentée** - 35% de couverture de code (vs 23% avant)
- ✅ **9 nouveaux tests** - Tests API, validation 2FA, mode manuel, etc.

### 📊 Statistiques
| Métrique | Avant | Après |
|----------|-------|-------|
| Tests passants | 4/5 (80%) | 14/14 (100%) |
| Couverture code | 23% | 35% |
| Warnings build | 7 warnings | 0 warning |
| Configuration | Manuelle | Validée auto |

## Structure du Projet

```
Get-Invoices/
├── backend/              # API FastAPI
│   ├── services/         # Logique métier
│   ├── models/          # Modèles de données
│   └── main.py          # Point d'entrée FastAPI
├── frontend/            # Application React+TypeScript
│   └── src/
├── tests/               # Tests unitaires et d'intégration
├── .env.example         # Exemple de configuration
├── requirements.txt     # Dépendances Python
├── package.json         # Dépendances Node.js
└── init_setup.py       # Script d'initialisation
```

## Installation

### Prérequis

- Python 3.10+
- Node.js 18+
- Chrome/Chromium ou Firefox (pour Selenium)

### Configuration

1. Copier `.env.example` vers `.env` et remplir les informations :

```bash
cp .env.example .env
```

2. Installer les dépendances Python :

```bash
pip install -r requirements.txt
```

3. Installer les dépendances Node.js :

```bash
cd frontend
npm install --legacy-peer-deps
```

> **Note** : L'option `--legacy-peer-deps` est nécessaire pour résoudre les conflits de dépendances entre TypeScript 5.x et react-scripts 5.0.1.

4. Lancer le script d'initialisation :

```bash
python init_setup.py
```

## Utilisation

### 🚀 Lancement automatique (Recommandé)

Le moyen le plus simple de démarrer l'application est d'utiliser les scripts de lancement automatique :

**Windows (PowerShell) :**
```powershell
.\start.ps1
```

**Linux/Mac :**
```bash
./start.sh
```

Ces scripts vont :
- ✅ Vérifier que les prérequis sont installés (Python, Node.js)
- ✅ Valider la configuration (.env)
- ✅ Démarrer automatiquement le backend et le frontend
- ✅ Ouvrir le navigateur sur http://localhost:3000
- ✅ Afficher les logs en temps réel

**Mode de lancement (Windows)** — Configurable dans `.env` avec `START_SINGLE_WINDOW` :
- `START_SINGLE_WINDOW=true` (défaut dans .env.example) : tout dans le **terminal courant** (idéal dans Cursor : backend en arrière-plan, frontend au premier plan ; Ctrl+C arrête tout).
- `START_SINGLE_WINDOW=false` : backend et frontend dans **deux fenêtres PowerShell** séparées.
- En ligne de commande : `.\start.ps1 -SingleWindow` force le mode une fenêtre ; `.\start.ps1 -SingleWindow:$false` force les 3 fenêtres.

**Pour arrêter l'application :**

**Windows :**
```powershell
.\stop.ps1
```

**Linux/Mac :**
```bash
./stop.sh
```

### Lancement manuel

Si vous préférez démarrer les serveurs manuellement :

#### Backend (FastAPI)

Depuis la racine du projet :

**Windows (PowerShell) :**
```powershell
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Linux/Mac :**
```bash
export PYTHONPATH="."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Le backend sera disponible sur `http://localhost:8000`
- API : http://localhost:8000
- Documentation interactive : http://localhost:8000/docs
- Endpoint de debug : http://localhost:8000/api/debug

#### Frontend (React)

Depuis le dossier `frontend` :

**Windows (PowerShell) :**
```powershell
cd frontend
$env:BROWSER="none"
npm start
```

**Linux/Mac :**
```bash
cd frontend
BROWSER=none npm start
```

Le frontend sera disponible sur `http://localhost:3000`

### Lancement simultané (recommandé)

Pour lancer les deux serveurs en même temps, ouvrez deux terminaux :

**Terminal 1 - Backend :**
```powershell
# Windows
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Frontend :**
```powershell
# Windows
cd frontend
$env:BROWSER="none"
npm start
```

### Dépannage

#### Problème avec ChromeDriver

Si vous rencontrez l'erreur `[WinError 193] %1 n'est pas une application Win32 valide`, nettoyez le cache de ChromeDriver :

**Windows (PowerShell) :**
```powershell
Remove-Item -Recurse -Force $env:USERPROFILE\.wdm\drivers\chromedriver
```

**Linux/Mac :**
```bash
rm -rf ~/.wdm/drivers/chromedriver
```

Puis relancez le serveur backend. Le ChromeDriver sera automatiquement re-téléchargé.

#### Ports déjà utilisés

Si les ports 3000 ou 8000 sont déjà utilisés :

**Windows :**
```powershell
# Trouver le processus utilisant le port
netstat -ano | findstr :8000
netstat -ano | findstr :3000

# Arrêter le processus (remplacer PID par l'ID trouvé)
taskkill /F /PID <PID>
```

**Linux/Mac :**
```bash
# Trouver et arrêter le processus
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9
```

#### Logs

Les logs de l'application sont disponibles dans :
- Fichier : `logs/app.log` (rotation automatique, max 10 MB)
- Console : sortie standard du serveur backend

## Configuration

Les identifiants Amazon doivent être configurés dans le fichier `.env` à la racine du projet :

```env
AMAZON_EMAIL=votre_email@example.com
AMAZON_PASSWORD=votre_mot_de_passe
DOWNLOAD_PATH=./factures
MAX_INVOICES=100
SELENIUM_HEADLESS=False
SELENIUM_TIMEOUT=30
SELENIUM_BROWSER=chrome
SELENIUM_MANUAL_MODE=False
SELENIUM_KEEP_BROWSER_OPEN=False
# SELENIUM_CHROME_PROFILE_DIR=./browser_profile
# FIREFOX_PROFILE_PATH=
START_SINGLE_WINDOW=true
```

### Options de configuration

- **Période des commandes Amazon** : la période affichée sur Amazon (liste déroulante « Vos commandes ») est dérivée du filtre choisi dans l’interface (année, plage de dates). Pour une plage 2025–2026, le script sélectionne « en 2026 » puis « en 2025 » et agrège les factures.
- `START_SINGLE_WINDOW` : **Lancement dans le terminal courant** (Windows, `start.ps1` uniquement). `true` = tout dans le même terminal (idéal Cursor), `false` = backend et frontend dans des fenêtres séparées. Défaut dans .env.example : `true`.
- `SELENIUM_BROWSER` : Navigateur à utiliser (`chrome` ou `firefox`, par défaut `chrome`)
- `SELENIUM_MANUAL_MODE` : Mode manuel (`True` ou `False`, par défaut `False`)
  - Si `True`, le navigateur reste ouvert et vous pouvez entrer vos identifiants manuellement
  - Le script attendra que vous soyez connecté avant de continuer
- `SELENIUM_KEEP_BROWSER_OPEN` : **Connexion continue** (`True` ou `False`, par défaut `False`)
  - Si `True`, à l'arrêt de l'application le navigateur n'est pas fermé
  - Utile pour garder la session Amazon ouverte ou enchaîner plusieurs lancements
- `SELENIUM_CHROME_PROFILE_DIR` : **Profil Chrome persistant** (optionnel, seulement si `SELENIUM_BROWSER=chrome`)
  - Répertoire où Chrome stocke cookies et session (ex. `./browser_profile`)
  - Au premier lancement vous vous connectez à Amazon ; aux lancements suivants la connexion est conservée
- `FIREFOX_PROFILE_PATH` : **Profil Firefox existant** (optionnel, seulement si `SELENIUM_BROWSER=firefox`)
  - Chemin vers un profil Firefox où vous êtes déjà connecté à Amazon
  - Exemple Windows : `C:\Users\USERNAME\AppData\Roaming\Mozilla\Firefox\Profiles\xxxxxxxx.default`
  - Exemple Linux/Mac : `~/.mozilla/firefox/xxxxxxxx.default`

#### Conserver la connexion dans un profil (Chrome ou Firefox)

**Chrome** — Utiliser un répertoire de profil dédié pour que la session soit sauvegardée entre les lancements :

1. Dans `.env` :
   ```env
   SELENIUM_BROWSER=chrome
   SELENIUM_CHROME_PROFILE_DIR=./browser_profile
   ```
2. Au premier lancement, connectez-vous à Amazon (et 2FA si demandé). Les cookies et la session sont enregistrés dans `browser_profile/`.
3. Aux lancements suivants, la connexion est réutilisée ; vous n'avez en général plus à vous reconnecter.

**Firefox** — Utiliser un profil existant où vous êtes déjà connecté à Amazon :

1. **Trouver le chemin de votre profil Firefox :**
   - Ouvrez Firefox
   - Tapez `about:profiles` dans la barre d'adresse
   - Copiez le chemin du "Dossier racine" du profil par défaut

2. **Configurer dans `.env` :**
   ```env
   SELENIUM_BROWSER=firefox
   FIREFOX_PROFILE_PATH=C:\Users\VotreNom\AppData\Roaming\Mozilla\Firefox\Profiles\xxxxxxxx.default
   ```

3. **Avantages (Chrome et Firefox) :**
   - Pas besoin de se reconnecter à chaque lancement (ou moins souvent)
   - Utilise les cookies et la session du profil
   - Évite les problèmes de 2FA si vous êtes déjà connecté

⚠️ **Important** :
- Ne partagez jamais votre fichier `.env` et ajoutez-le au `.gitignore`
- Le fichier `.env` doit être à la racine du projet, pas dans le dossier `backend`

### Validation de configuration

L'application valide automatiquement votre configuration au démarrage et vous alertera si :
- ✅ L'email ou le mot de passe Amazon ne sont pas configurés
- ✅ Le navigateur spécifié n'est pas valide (doit être `chrome` ou `firefox`)
- ✅ Le timeout est hors limites (doit être entre 10 et 300 secondes)
- ✅ Le nombre maximum de factures est invalide
- ⚠️ Un profil Firefox est configuré mais Chrome est sélectionné

Si une erreur de configuration est détectée, l'application ne démarrera pas et affichera un message d'erreur détaillé.

## Tests

Le projet inclut une suite de tests complète (couverture de 35%) :

**Exécuter tous les tests :**
```bash
pytest tests/ -v
```

**Exécuter avec rapport de couverture :**
```bash
pytest tests/ --cov=backend --cov-report=html
```

**Tests disponibles :**
- ✅ Tests unitaires du service AmazonInvoiceDownloader (8 tests)
- ✅ Tests de l'API FastAPI (6 tests)
- ✅ Tests de validation de configuration
- ✅ Tests de gestion 2FA

Les rapports de couverture HTML sont générés dans `htmlcov/`.

## Sécurité

- Les mots de passe sont stockés de manière sécurisée dans `.env`
- Utilisation de variables d'environnement pour les credentials
- Le fichier `.env` est exclu du contrôle de version
- Validation automatique de la configuration au démarrage
- Détection des valeurs par défaut dangereuses

## 📋 Liens Rapides

### Démarrage Rapide
```powershell
# 1. Copier le fichier de configuration
Copy-Item .env.example .env

# 2. Éditer .env avec vos identifiants Amazon
notepad .env

# 3. Lancer l'application
.\start.ps1
```

### Commandes Utiles
| Commande | Description |
|----------|-------------|
| `.\start.ps1` | Démarrer backend + frontend (Windows ; mode selon `START_SINGLE_WINDOW` dans .env) |
| `.\start.ps1 -SingleWindow` | Forcer tout dans le terminal courant (Windows) |
| `.\stop.ps1` | Arrêter l'application (Windows) |
| `./start.sh` | Démarrer backend + frontend (Linux/Mac) |
| `./stop.sh` | Arrêter l'application (Linux/Mac) |
| `pytest tests/ -v` | Exécuter les tests |
| `pytest tests/ --cov=backend` | Tests avec couverture |
| `npm run build` | Build du frontend |

### URLs de l'Application
- Frontend : http://localhost:3000
- Backend API : http://localhost:8000
- Documentation API : http://localhost:8000/docs
- Endpoint Debug : http://localhost:8000/api/debug

## 📝 Changelog Détaillé

### Version 1.1.0 (2026-02-11)

#### 🔧 Corrections
- **ChromeDriver** : Correction du problème d'initialisation du driver Selenium
  - Optimisation de la recherche de l'exécutable chromedriver.exe
  - Suppression de la recherche récursive coûteuse
  - Ajout de chemins prioritaires pour une résolution rapide
- **Configuration** : Nettoyage du fichier .env
  - Suppression du BOM UTF-8
  - Correction de l'encodage des caractères accentués
  - Suppression des espaces en début de ligne
  - Suppression du fichier .env dupliqué dans backend/
- **FastAPI** : Migration vers les handlers modernes
  - Remplacement de `@app.on_event()` (déprécié)
  - Implémentation de `@asynccontextmanager` avec `lifespan`
- **TypeScript** : Résolution de tous les warnings
  - Ajout des types de retour manquants (`: void`)
  - Suppression de l'interface `OTPRequest` non utilisée
  - Build frontend sans aucun warning

#### ✨ Nouvelles Fonctionnalités
- **Scripts de lancement** : Démarrage automatique simplifié
  - `start.ps1` / `start.sh` : Lance backend + frontend automatiquement
  - `stop.ps1` / `stop.sh` : Arrêt propre de l'application
  - Vérification automatique des prérequis
  - Libération automatique des ports
  - Ouverture automatique du navigateur
- **Validation de configuration** : Contrôles au démarrage
  - Vérification des identifiants Amazon
  - Validation du navigateur sélectionné
  - Contrôle des valeurs de timeout
  - Détection des configurations incohérentes
  - Messages d'erreur détaillés et informatifs

#### 🧪 Tests
- **Test corrigé** : `test_login_success` passe maintenant avec succès
- **9 nouveaux tests** :
  - `test_close_manual_mode` : Vérification du mode manuel
  - `test_is_2fa_required_no_driver` : Test 2FA sans driver
  - `test_is_2fa_required_with_otp_field` : Détection 2FA
  - `test_submit_otp_without_driver` : Soumission OTP
  - `test_navigate_to_orders` : Navigation commandes
  - `test_debug_endpoint` : Endpoint de debug
  - `test_check_2fa_endpoint` : Vérification 2FA
  - `test_download_without_downloader` : Gestion erreur
  - `test_submit_otp_without_downloader` : Gestion erreur OTP
- **Couverture** : Passage de 23% à 35% (+52%)
- **Résultats** : 14/14 tests passent (100%)

#### 📚 Documentation
- Ajout de la section "Améliorations récentes"
- Documentation des scripts de lancement automatique
- Ajout de la section validation de configuration
- Mise à jour des statistiques de tests
- Ajout de liens rapides et commandes utiles
- Documentation du changelog détaillé

#### 📦 Fichiers Modifiés
- `backend/main.py` : Validation config + lifespan handlers
- `backend/services/amazon_downloader.py` : Fix ChromeDriver
- `frontend/src/App.tsx` : Types TypeScript
- `frontend/src/components/DownloadForm.tsx` : Types TypeScript
- `frontend/src/services/api.ts` : Nettoyage interfaces
- `.env` : Encodage et formatage corrigés
- `tests/test_amazon_downloader.py` : Tests améliorés
- `tests/test_api.py` : Nouveaux tests API
- `README.md` : Documentation complète

#### 📦 Fichiers Créés
- `.env.example` : Template de configuration
- `start.ps1` : Script de lancement Windows
- `start.sh` : Script de lancement Linux/Mac
- `stop.ps1` : Script d'arrêt Windows
- `stop.sh` : Script d'arrêt Linux/Mac

#### 📦 Fichiers Supprimés
- `backend/.env` : Fichier dupliqué supprimé

## Licence

MIT

