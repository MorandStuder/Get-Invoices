# Revue de code — Get-Invoices (v1.2)

**Périmètre :** backend (FastAPI, amazon_downloader), frontend (React/TS), modèles, tests.  
**Objectif :** qualité, maintenabilité, robustesse.

---

## 1. Structure et design

**Points positifs**
- Séparation claire : `backend/` (API + services), `frontend/` (React), `tests/`.
- Logique métier dans `AmazonInvoiceDownloader`, API dans `main.py`.
- Schémas Pydantic centralisés dans `models/schemas.py`.

**À améliorer**
- **Major —** `amazon_downloader.py` est très long (~1390 lignes). À terme, découper en modules (ex. `driver_setup.py`, `login_flow.py`, `orders_pagination.py`, `invoice_download.py`) pour faciliter les tests et la maintenance.
- **Minor —** Les paramètres `year` et `month` de `download_invoices()` sont acceptés par l’API et le service mais **jamais utilisés** pour filtrer les commandes. Soit implémenter le filtre (côté Amazon ou post-téléchargement), soit les retirer / documenter comme “réservés”.

---

## 2. Logique et robustesse

**Blocker**
- **Code mort dans `amazon_downloader.login()` (l.744–746)** : un `time.sleep(5)` et un commentaire sont placés après `raise Exception(...)`. Ils ne sont jamais exécutés. À supprimer pour éviter toute confusion.

**Major**
- **`_download_pdf_from_url`** : `response.content[:4] == b'%PDF'` est correct ; si `content` est vide, `[:4]` reste sûr. En revanche, en cas de très grosse réponse, tout est chargé en mémoire. Pour des factures PDF, c’est acceptable ; à garder en tête si on augmente les volumes.
- **Pagination** : si `_go_to_next_orders_page()` échoue (ex. timeout), la boucle s’arrête sans distinguer “plus de pages” et “erreur réseau”. Un log plus explicite (ex. “Échec navigation page suivante”) aiderait le diagnostic.

**Minor**
- **ChromeDriver** : la détection de l’exécutable suppose `.exe` et des chemins Windows. Sur Linux/macOS, les `possible_paths` utilisent `chromedriver.exe` et ne matcheront pas. À adapter selon l’OS (ex. `chromedriver` sans extension sur Unix) pour éviter des échecs silencieux en CI ou sur d’autres machines.
- **`download_invoices`** : en cas d’exception dans la boucle de pagination (après la première page), l’exception est propagée et les fichiers déjà téléchargés ne sont pas retournés. Option possible : retourner un résultat partiel (count + files déjà récupérés) et indiquer une erreur (ex. champ `partial_error`).

---

## 3. Style et lisibilité

**Points positifs**
- Docstrings présentes sur les endpoints et les méthodes publiques.
- Noms de variables et fonctions en général clairs.
- Pas d’erreurs de lint signalées.

**À corriger**
- **Pydantic (schemas.py)** : `class Config:` avec `json_schema_extra` est l’ancienne API Pydantic v1. En v2, utiliser `model_config = ConfigDict(json_schema_extra={...})` pour éviter les warnings et rester aligné avec la doc.
- **Frontend** : `onKeyPress` est déprécié en React 18. Préférer `onKeyDown` pour “Enter” (comportement équivalent pour cette utilisation).
- **Backend** : quelques `logger.info` très verbeux (ex. logs de login étape par étape). En production, envisager de passer une partie en `logger.debug` et de garder `info` pour les étapes principales (connexion, début/fin téléchargement, erreurs).

---

## 4. Tests

**Points positifs**
- 18 tests, couvrant racine, status, debug, 2FA, download/OTP quand le downloader est indisponible.
- Tests downloader : init, close (normal / manual / keep_browser_open), 2FA, pagination (sans driver / pas de “next”), navigation commandes.
- Utilisation de mocks (driver, WebDriverWait, sleep) pour éviter Selenium réel.

**À améliorer**
- **Couverture** : beaucoup de chemins dans `amazon_downloader` (login, 2FA, popover, pagination) ne sont pas exercés par les tests (couverture ~27 %). Priorité : au moins un test qui mocke `download_invoices` de bout en bout (login + navigate_to_orders + une liste d’orders mockée + `download_invoice` mocké) pour valider la structure et la pagination.
- **Tests API** : pas de test où `downloader` est initialisé et où l’on envoie une requête POST `/api/download` avec un body valide (même si le téléchargement réel est mocké). Un test avec `patch` sur `downloader.download_invoices` retournant `{"count": 0, "files": []}` renforcerait la confiance dans l’endpoint.
- **Edge cases** : pas de test pour `DownloadRequest` avec `year`/`month` invalides (Pydantic les rejette déjà ; un test explicite documenterait le comportement). Idem pour `OTPRequest` (code trop court / trop long).
- **test_amazon_downloader** : `except Exception` dans `wait_until_side_effect` (l.80) est trop large ; préférer capturer une exception précise ou au moins logger/re-raise pour ne pas masquer des régressions.

---

## 5. Sécurité, performance, accessibilité

**Sécurité**
- Les identifiants Amazon viennent de l’env (`.env`), pas du code : bon.
- `.env` est dans `.gitignore` : bon.
- L’endpoint `/api/debug` expose `has_email` / `has_password` (booléens). Pas de fuite de valeurs, mais en production on peut le désactiver ou le restreindre (ex. `if settings.debug`).
- CORS limité à `localhost:3000` / `127.0.0.1:3000` : adapté à un usage local ; à revoir si déploiement public.

**Performance**
- `time.sleep` utilisé à plusieurs endroits (attente page, entre clics). C’est courant avec Selenium ; à garder raisonnable pour ne pas allonger inutilement les runs.
- Pas de limite côté API sur la durée d’un téléchargement : une requête peut rester ouverte longtemps. Option : timeout global uvicorn ou middleware de timeout pour éviter des requêtes “fantômes”.

**Accessibilité (frontend)**
- Formulaires avec `<label htmlFor=...>` : bon.
- Messages d’erreur et statut affichés en texte : bon.
- Vérifier que les couleurs (erreur, succès) ne sont pas les seuls indicateurs (déjà du texte en plus).

---

## 6. Synthèse des actions recommandées

| Sévérité  | Action |
|-----------|--------|
| **Blocker** | Supprimer le code mort après `raise` dans `amazon_downloader.login()` (l.744–746). |
| **Major**   | Implémenter le filtre `year`/`month` dans `download_invoices` ou les retirer/documenter. |
| **Major**   | Adapter la détection ChromeDriver pour Linux/macOS (sans `.exe`). |
| **Major**   | Ajouter au moins un test d’intégration API avec `download_invoices` mocké. |
| **Minor**   | Remplacer `class Config` par `model_config = ConfigDict(...)` dans les schémas Pydantic. |
| **Minor**   | Remplacer `onKeyPress` par `onKeyDown` dans le formulaire OTP (App.tsx). |
| **Minor**   | Réduire la verbosité des logs (passer une partie en `debug`). |
| **Minor**   | Envisager un timeout global ou middleware pour les requêtes longues. |

---

*Revue effectuée sur la base du code de la branche actuelle (V0 / v1.2).*
