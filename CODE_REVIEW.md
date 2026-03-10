# Code Review — Get-Invoices (V2)

## Vue d'ensemble

Outil de téléchargement automatisé de factures fournisseurs via Selenium.
Stack : **FastAPI** + **React/TypeScript** + **Selenium WebDriver**.

**Providers implémentés** : Amazon, Bouygues, Decathlon, FNAC, Free Mobile, Freebox, Orange, Qobuz (8 total).

---

## Architecture globale

```
backend/
├── main.py                  # FastAPI app, endpoints SSE, lifespan handlers
├── models/schemas.py        # Pydantic v2 models
├── providers/
│   ├── base.py              # InvoiceProviderProtocol (Protocol duck-typing)
│   ├── __init__.py          # Registre PROVIDERS + PROVIDER_LABELS
│   └── <provider>.py        # Un fichier par fournisseur
└── services/
    ├── amazon_downloader.py # Wrapper legacy Amazon
    └── invoice_registry.py  # Registre JSON persistant (anti-redoublon)

frontend/src/
├── App.tsx                  # Composant principal, gestion état global
├── components/
│   └── DownloadForm.tsx     # Formulaire de téléchargement
└── services/
    └── api.ts               # Client SSE + appels REST
```

---

## Points positifs

### Backend

- **Protocol duck-typing** (`base.py`) : les providers n'ont pas à hériter d'une classe abstraite, ce qui facilite l'ajout de nouveaux fournisseurs.
- **SSE streaming** (`main.py`) : progression temps réel via `StreamingResponse` + `yield`, évite les timeouts sur les longues opérations.
- **InvoiceRegistry** (`invoice_registry.py`) : registre JSON persistant par provider, évite les re-téléchargements. Supporte la déduplication par `order_id` et par URL (`is_downloaded_by_url`).
- **Timeout 600 s** (`DOWNLOAD_TIMEOUT_SECONDS`) : évite les requêtes bloquées indéfiniment.
- **Logs rotatifs** : `logs/app.log` avec `RotatingFileHandler` (10 MB max), évite la croissance infinie.
- **pydantic-settings** : configuration centralisée via `.env`, validée au démarrage.
- **`keep_browser_open`** : session browser préservable entre les appels — utile pour les providers avec 2FA ou session longue.

### Frontend

- **SSE natif** : `fetch` + `ReadableStream` pour la progression, plus léger qu'un WebSocket.
- **Filtre de période unifié** : même formulaire (Depuis la dernière fois / Année / Mois / Plage) pour téléchargement unitaire et multi-fournisseurs.
- **TypeScript strict** : interfaces bien typées pour les réponses API.
- **AbortController** : annulation propre du téléchargement en cours.

---

## Problèmes identifiés et corrections apportées

### ✅ Corrigé — `hash()` non déterministe dans les providers

**Problème** : Python's `hash()` est aléatoire à chaque session (`PYTHONHASHSEED`). Les `order_id` générés depuis des URLs changeaient à chaque redémarrage → le registre ne reconnaissait jamais les factures déjà téléchargées → re-téléchargement systématique.

**Fichiers concernés** : `bouygues.py`, `fnac.py`, `freebox.py`, `free_mobile.py`, `orange.py`

**Correction appliquée** :
```python
# Avant (non déterministe)
order_id = f"bouygues_{hash(full) % 100000}"

# Après (stable entre sessions)
order_id = f"bouygues_{hashlib.md5(full.encode()).hexdigest()[:12]}"
```

### ✅ Corrigé — Bouygues : double vérification registre

Ajout de `is_downloaded_by_url()` avant téléchargement + sauvegarde de `invoice_url` dans le registre pour déduplication URL-based.

### ✅ Corrigé — FNAC : détection robot

Suppression de `_try_auto_login()` qui remplissait le formulaire et déclenchait la détection anti-bot.
`login()` attend désormais une connexion manuelle (profil persistant recommandé).

### ✅ Corrigé — `onKeyPress` déprécié (React 18)

`onKeyPress` → `onKeyDown` dans `App.tsx` (input OTP).

### ✅ Corrigé — Pydantic v2 : `class Config` → `model_config`

`schemas.py` : `class Config: json_schema_extra = {...}` → `model_config = ConfigDict(json_schema_extra={...})`.

---

## Points d'amélioration restants

### Backend

1. **`hash(el)` sur élément Selenium** (`free_mobile.py`) : utilisé pour déduplication de lignes téléphoniques (pas des URLs). Acceptable mais fragile — un ID stable serait préférable (numéro de téléphone extrait).

2. **Gestion d'état provider globale** (`main.py`) : les instances de provider sont des variables globales. Pas thread-safe si plusieurs requêtes simultanées. Acceptable pour usage mono-utilisateur.

3. **Pas de retry automatique** : si Selenium plante en milieu de téléchargement, l'erreur remonte directement. Un mécanisme de retry (1-2 fois) sur les erreurs transitoires améliorerait la robustesse.

4. **Tests** : couverture ~35%, centrée sur amazon_downloader. Les providers Bouygues, Decathlon, FNAC, Free Mobile, Freebox, Orange ne sont pas testés.

5. **`amazon_downloader.py`** : wrapper legacy qui duplique une partie de la logique de provider. Candidat à la refactorisation pour suivre `InvoiceProviderProtocol`.

### Frontend

6. **Pas de persistence des paramètres** : le formulaire se réinitialise à chaque rechargement. Un `localStorage` pour le provider sélectionné et le type de filtre serait utile.

7. **Gestion d'erreur réseau** : les erreurs de connexion au backend (backend off, CORS) affichent une erreur générique. Un message d'aide ("Le backend est-il démarré ?") aiderait.

---

## Sécurité

- Credentials dans `.env` (non versionné) : correct.
- CORS configuré uniquement sur `localhost:3000` : correct pour usage local.
- Aucune authentification sur l'API — normal pour un outil local, mais à noter si exposé sur réseau.
- Pas d'injection possible dans les paramètres Pydantic (types stricts, validation `ge`/`le`).

---

## Conventions respectées

- Black + isort : formatage standardisé.
- Python 3.10+, annotations `from __future__ import annotations`.
- Logs structurés avec niveaux (DEBUG/INFO/WARNING/ERROR).
- `Optional[X]` avec `Field(default=None)` pour tous les champs optionnels.
