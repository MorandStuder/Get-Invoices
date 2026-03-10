# CLAUDE.md — Get-Invoices

Outil automatisé de téléchargement de factures. Backend FastAPI + Frontend React/TypeScript + Selenium.

## Architecture

```
Get-Invoices/
├── backend/
│   ├── main.py                  # FastAPI app (lifespan handlers, endpoints SSE)
│   ├── models/schemas.py        # Pydantic models (DownloadRequest, OTPRequest…)
│   ├── providers/
│   │   ├── base.py              # InvoiceProviderProtocol + OrderInfo
│   │   ├── __init__.py          # Registre PROVIDERS + PROVIDER_LABELS
│   │   ├── amazon.py            # AmazonProvider
│   │   ├── bouygues.py          # BouyguesProvider
│   │   ├── decathlon.py         # DecathlonProvider
│   │   ├── fnac.py              # FnacProvider
│   │   ├── free_mobile.py       # FreeMobileProvider
│   │   ├── freebox.py           # FreeboxProvider
│   │   ├── orange.py            # OrangeProvider
│   │   └── qobuz.py             # QobuzProvider
│   └── services/
│       ├── amazon_downloader.py # Wrapper legacy Amazon (Selenium)
│       └── invoice_registry.py  # Gestion des providers actifs
├── frontend/src/                # React + TypeScript
├── tests/                       # pytest (couverture ~35%)
├── .env.example                 # Template de config
├── start.ps1 / start.sh         # Lancement auto backend + frontend
└── stop.ps1 / stop.sh           # Arrêt propre
```

## Providers implémentés

| ID | Fournisseur | Variables .env requises |
|----|------------|------------------------|
| `amazon` | Amazon | `AMAZON_EMAIL`, `AMAZON_PASSWORD` |
| `freebox` | Freebox | `FREEBOX_LOGIN`, `FREEBOX_PASSWORD` |
| `free_mobile` | Free Mobile | `FREE_MOBILE_LOGIN`, `FREE_MOBILE_PASSWORD` |
| `fnac` | FNAC | `FNAC_LOGIN`, `FNAC_PASSWORD` |
| `bouygues` | Bouygues Telecom | `BOUYGUES_LOGIN`, `BOUYGUES_PASSWORD` |
| `orange` | Orange | `ORANGE_LOGIN` (informatif), `ORANGE_INVOICES_URL` (URL page factures) |
| `decathlon` | Decathlon | `DECATHLON_LOGIN`, `DECATHLON_PASSWORD` |
| `qobuz` | Qobuz | `QOBUZ_LOGIN`, `QOBUZ_PASSWORD` |

Provider prévu (non implémenté) : `leroy_merlin`.

## Pattern d'un provider

Chaque provider implémente `InvoiceProviderProtocol` (duck typing via `Protocol`) :
- `login(otp_code?)` → bool
- `navigate_to_invoices()` → bool
- `list_orders_or_invoices()` → List[OrderInfo]
- `download_invoice(order, ...)` → str | None
- `download_invoices(max, year, month, date_start, date_end, ...)` → {"count": int, "files": [...]}
- `close()`, `is_2fa_required()`, `submit_otp(code)`

`download_invoices` accepte un callback `on_progress(current, total, message)` pour le streaming SSE.

## Fonctionnalités frontend

- **Sélection du provider** : liste déroulante avec uniquement les providers configurés et implémentés.
- **Filtres de période** (disponibles pour le provider individuel ET "Tous les fournisseurs") :
  - *Depuis la dernière fois* (défaut) — appelle `GET /api/last-download-date` puis envoie `date_start` + `date_end=aujourd'hui`
  - *Toutes les commandes* — pas de filtre
  - *Une année* — filtre `year`
  - *Année + mois* — filtre `year` + `months[]`
  - *Plage de dates* — filtre `date_start` + `date_end`
- **Registre** : skip automatique des factures déjà téléchargées ; option "Forcer le re-téléchargement".
- **Progression en temps réel** via SSE (`event: progress` / `event: done` / `event: error`).
- **Tous les fournisseurs** : section visible dès ≥ 2 providers configurés — exécution séquentielle avec les mêmes options de filtre.

Pour ajouter un provider :
1. Créer `backend/providers/<id>.py` avec `PROVIDER_ID = "<id>"` et les credentials lus depuis `Settings`
2. L'enregistrer dans `backend/providers/__init__.py` dans `PROVIDERS` et `PROVIDER_LABELS`

## Lancement

```powershell
# Windows (recommandé)
.\start.ps1           # mode selon START_SINGLE_WINDOW dans .env
.\start.ps1 -SingleWindow   # forcer terminal unique

# Manuel
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
cd frontend && npm start
```

- Backend : http://localhost:8001 | Docs : http://localhost:8001/docs
- Frontend : http://localhost:3000

## Configuration (.env clés)

```env
SELENIUM_BROWSER=firefox          # chrome ou firefox
SELENIUM_HEADLESS=false
SELENIUM_MANUAL_MODE=false        # true = attendre connexion manuelle
SELENIUM_KEEP_BROWSER_OPEN=false  # true = session conservée à l'arrêt
FIREFOX_PROFILE_PATH=             # profil Firefox persistant (recommandé)
SELENIUM_CHROME_PROFILE_DIR=      # profil Chrome persistant
DOWNLOAD_PATH=./factures
MAX_INVOICES=100
START_SINGLE_WINDOW=true
```

## Tests

```bash
pytest tests/ -v
pytest tests/ --cov=backend --cov-report=html
```

## Notes FNAC (comportements connus)

- **Connexion** : uniquement manuelle — pas de remplissage de formulaire (détection anti-robot). Le navigateur est ouvert, l'utilisateur se connecte dans les 2 minutes ; si un profil persistant est déjà connecté, la session est réutilisée directement.
- **Détection de connexion** : `_is_logged_in()` vérifie l'URL (`/account/order`) et l'absence de formulaire de mot de passe.

## Notes Bouygues (comportements connus)

- **`order_id` stable** : calculé via `hashlib.md5(url)[:12]` pour être reproductible entre sessions (évite la re-détection des doublons causée par `hash()` aléatoire en Python).
- **Registre** : `invoice_url` sauvegardée + vérification par URL (`is_downloaded_by_url`) en plus de l'`order_id` — double sécurité anti-doublon.
- **Connexion** : automatique si un formulaire est présent, sinon le profil persistant est utilisé.

## Notes Qobuz (comportements connus)

- **URL factures** : `https://www.qobuz.com/profile/invoice` (pagination via `?page=N`)
- **Flux** : liste des reçus → `/profile/receipt/{id}` → export PDF via CDP `Page.printToPDF`
- **Chrome requis** pour le téléchargement (CDP `printToPDF` non disponible sous Firefox)
- **Filtre date** : si `invoice_date` est `None` et qu'un filtre est actif, la commande est **exclue** (comportement inverse de Decathlon, pour éviter de tout télécharger)
- **`self.login` → `self.email`** : même convention que Decathlon, paramètre `login` stocké sous `self.email`

## Notes Decathlon (comportements connus)

- **URL commandes** : `https://www.decathlon.fr/account/myPurchase`
- **Flux** : liste → "Voir les détails" (`/account/orderTracking?transactionId=...` ou `?orderId=...`) → "Télécharger ma facture"
- **Types de commandes** :
  - `transactionId=...&type=store` → achat en magasin → modal "Informations client" (Nom/Prénom/Adresse requis pour générer la facture). Le formulaire est rempli automatiquement depuis le profil Decathlon si possible, sinon la commande est ignorée.
  - `orderId=...&type=oneomp` → marketplace/tiers → pas de "Télécharger ma facture", lien cherché sous d'autres variantes ("télécharger", "facture", "invoice").
  - `orderId=...` sans type → commande en ligne standard → "Télécharger ma facture" présent.
- **Pagination** : jusqu'à 30 pages sur `/account/myPurchase` — toutes parcourues automatiquement
- **Session** : `keep_browser_open=True` forcé dans `main.py` pour Decathlon ; profil Chrome persistant via `SELENIUM_CHROME_PROFILE_DIR`
- **`self.login` → `self.email`** : dans `__init__`, le paramètre `login` est stocké sous `self.email` pour éviter l'écrasement de la méthode `login()`
- **Filtre date** : si `invoice_date` est `None` (date non extraite), la commande passe le filtre year/month (on ne peut pas savoir si elle correspond)

## Conventions

- Formatage : **Black** + **isort** (exécuter avant commit)
- Python 3.10+, FastAPI, pydantic-settings, Selenium avec webdriver-manager
- Frontend : React 18, TypeScript strict, `npm install --legacy-peer-deps`
- Logs : `logs/app.log` (RotatingFileHandler, 10 MB max)
- Timeout download : 600 s (`DOWNLOAD_TIMEOUT_SECONDS`)
