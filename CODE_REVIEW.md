# Code Review — Get-Invoices (V2)

_Dernière mise à jour : mars 2026_

## Vue d'ensemble

Outil de téléchargement automatisé de factures fournisseurs via Selenium.
Stack : **FastAPI** + **React/TypeScript** + **Selenium WebDriver**.

**Providers implémentés** : Amazon, Bouygues, Decathlon, FNAC, Free Mobile, Freebox, Orange, Qobuz (8 total).

---

## Architecture globale

```
backend/
├── main.py                  # FastAPI app, endpoints SSE, lifespan handlers
├── models/schemas.py        # Pydantic v2 models (ConfigDict)
├── providers/
│   ├── base.py              # InvoiceProviderProtocol (Protocol duck-typing)
│   ├── __init__.py          # Registre PROVIDERS + PROVIDER_LABELS
│   └── <provider>.py        # Un fichier par fournisseur
└── services/
    ├── amazon_downloader.py # Wrapper legacy Amazon (Selenium)
    └── invoice_registry.py  # Registre JSON persistant (anti-doublon)

frontend/src/
├── App.tsx                  # Composant principal, gestion état global
├── components/
│   ├── DownloadForm.tsx     # Formulaire de téléchargement
│   └── StatusDisplay.tsx    # Affichage progression SSE
└── services/
    └── api.ts               # Client SSE + appels REST
```

---

## Points positifs

### Backend

- **Protocol duck-typing** (`base.py`) : les providers n'héritent pas d'une classe abstraite — ajout d'un nouveau provider = créer un fichier + l'enregistrer dans `__init__.py`.
- **SSE streaming** (`main.py`) : progression temps réel via `StreamingResponse` + `asyncio.Queue`, évite les timeouts sur longues opérations (timeout 600 s).
- **InvoiceRegistry** (`invoice_registry.py`) : registre JSON persistant par provider dans `.invoice_registry.json`. Déduplication par `order_id` et par URL (`is_downloaded_by_url`).
- **`order_id` déterministe** : tous les providers utilisent `hashlib.md5(url.encode()).hexdigest()[:12]` — stable entre sessions, évite les re-téléchargements causés par `hash()` aléatoire.
- **Profil Chrome par provider** : `_chrome_dir(provider_id)` crée un sous-dossier isolé (`GetInvoicesChrome/qobuz/`, etc.) — pas de conflit de lockfile entre providers successifs.
- **Logs rotatifs** : `logs/app.log` via `RotatingFileHandler` (10 MB max, 5 backups).
- **pydantic-settings** : configuration centralisée via `.env`, validée au démarrage (`validate_settings`).
- **`keep_browser_open`** : session browser préservable entre appels — utile pour les providers avec session longue.

### Frontend

- **SSE natif** : `fetch` + `ReadableStream`, plus léger qu'un WebSocket.
- **Filtre de période unifié** : même formulaire (Depuis la dernière fois / Toutes / Année / Mois / Plage de dates) pour téléchargement unitaire **et** multi-fournisseurs.
- **`AbortController`** : annulation propre du téléchargement en cours.
- **TypeScript strict** : interfaces typées pour toutes les réponses API.
- **Guard `canLaunch`** : bouton désactivé si les filtres sélectionnés sont incomplets (plage sans dates, mois sans année…).

---

## Corrections appliquées (historique)

### ✅ `hash()` non déterministe → `hashlib.md5`

`hash()` Python est aléatoire par session (`PYTHONHASHSEED`) : les `order_id` changeaient à chaque redémarrage, le registre ne reconnaissait jamais les doublons → re-téléchargement systématique.

Corrigé dans : `bouygues.py`, `fnac.py`, `freebox.py`, `free_mobile.py`, `orange.py`.

```python
# Avant
order_id = f"bouygues_{hash(full) % 100000}"
# Après
order_id = f"bouygues_{hashlib.md5(full.encode()).hexdigest()[:12]}"
```

### ✅ Bouygues : double vérification registre

Ajout de `is_downloaded_by_url()` avant téléchargement + sauvegarde de `invoice_url` dans le registre → déduplication par URL en plus de l'`order_id`.

### ✅ FNAC : suppression auto-login (détection robot)

`_try_auto_login()` remplissait le formulaire et déclenchait l'anti-bot FNAC. Supprimé. `login()` attend désormais une connexion manuelle (profil persistant recommandé).

### ✅ React 18 : `onKeyPress` → `onKeyDown`

`onKeyPress` déprécié dans React 18, remplacé par `onKeyDown` dans `App.tsx`.

### ✅ Pydantic v2 : `class Config` → `model_config = ConfigDict(...)`

`schemas.py` migré vers la syntaxe Pydantic v2.

---

## Points d'amélioration restants

### Backend

1. **`hash(el)` sur élément Selenium** (`free_mobile.py:460`) : utilisé pour déduplication de lignes téléphoniques (pas des URLs). Pas critique (le hash de l'objet Selenium est stable dans la même session), mais fragile. Préférable d'extraire le numéro de téléphone comme clé stable.

2. **État global des providers** (`main.py`) : les instances sont dans un `dict` global. Pas thread-safe si deux requêtes simultanées touchent le même provider. Acceptable pour usage mono-utilisateur local.

3. **Pas de retry** : une erreur Selenium en milieu de téléchargement remonte directement. Un retry 1-2 fois sur les erreurs transitoires (`StaleElementReferenceException`, timeout réseau) améliorerait la robustesse.

4. **Couverture de tests : ~16%** — centrée sur Amazon et Freebox. Les providers Bouygues, Decathlon, FNAC, Free Mobile, Orange ne sont pas testés. Difficile à tester sans mock Selenium.

5. **`amazon_downloader.py`** : wrapper legacy (>1000 lignes) qui duplique une partie de la logique provider. Candidat à une refactorisation pour suivre `InvoiceProviderProtocol`, mais non prioritaire.

6. **Validation `AMAZON_EMAIL`/`AMAZON_PASSWORD` obligatoires** (`validate_settings`) : le backend refuse de démarrer si Amazon n'est pas configuré, même si on n'utilise qu'Orange. Les credentials Amazon devraient être optionnels comme les autres.

### Frontend

7. **Pas de persistence UI** : le formulaire se réinitialise à chaque rechargement de page. Un `localStorage` pour le provider sélectionné et le type de filtre serait utile.

8. **Gestion d'erreur réseau générique** : si le backend est arrêté, l'erreur affichée est peu explicite. Un message contextuel ("Le backend est-il démarré sur le port 8001 ?") aiderait.

9. **`DownloadForm.tsx:57`** : `useEffect` avec dépendance manquante (`provider`) — warning ESLint `react-hooks/exhaustive-deps`. Sans impact fonctionnel mais à corriger.

---

## Sécurité

- Credentials dans `.env` (non versionné) : correct.
- CORS restreint à `localhost:3000` : correct pour usage local.
- Aucune authentification sur l'API : normal pour outil local, à noter si jamais exposé sur réseau.
- Validation stricte des paramètres Pydantic (`ge`, `le`, types) : pas d'injection possible via l'API.

---

## Conventions respectées

- **Black + isort** : formatage standardisé, vérifié en CI.
- **Prettier** : formatage TypeScript/CSS vérifié en CI.
- **Python 3.10+** avec annotations modernes (`X | Y`, `from __future__ import annotations`).
- Logs structurés avec niveaux (`DEBUG` / `INFO` / `WARNING` / `ERROR`).
- `Optional[X]` avec `Field(default=None)` pour tous les champs optionnels des schemas.
