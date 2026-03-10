# Plan d'amélioration — Get-Invoices (post-V0)

Ce document décrit la feuille de route pour faire évoluer le téléchargeur de factures Amazon (V0) vers une solution multi-fournisseurs avec extraction de données et export Excel, en s’inspirant de **GetMyInvoices** et **Jenji**.

---

## Vue d’ensemble des phases

| Phase | Objectif principal | Priorité |
|-------|--------------------|----------|
| **V1** | Filtre par date, nom de fichier avec date, liste des factures déjà téléchargées | Haute |
| **V2** | Multi-fournisseurs (FNAC, Free, Bouygues, Decathlon, Leroy Merlin) | Haute |
| **V3** | Reconnaissance des factures (OCR) et remplissage Excel | Haute |
| **V4** | Fonctionnalités avancées type GetMyInvoices / Jenji | Moyenne |

---

## Phase V1 — Robustesse et déduplication ✅ (réalisée)

### 1.1 Filtre par date ✅

**Implémentation choisie : Option B (scraping)** — chaque provider parse la date depuis la page et filtre dans `download_invoices()`.

**Livrables**

- [x] Option B retenue : parsing de la date dans chaque provider (`_parse_date_from_text`, `_MOIS_FR`…).
- [x] Filtre implémenté dans `download_invoices()` de chaque provider : `year`, `month`, `months`, `date_start`, `date_end`.
- [x] Plage de dates exposée dans l’API (`DownloadRequest`) et le schéma Pydantic.
- [ ] Tests unitaires sur le filtre (mock de listes de commandes avec dates).

---

### 1.2 Date de facture dans le nom de fichier ✅

**Format retenu** : `{provider}_{date_facture}_{order_id}.pdf`
ex. `amazon_2025-01-15_123-4567890-1234567.pdf`
Si la date n’est pas disponible : fallback `{provider}_{order_id}.pdf`.

**Livrables**

- [x] Format de nom défini et implémenté dans chaque provider.
- [x] Date passée jusqu’à la fonction d’écriture du PDF.
- [x] `order_id` conservé pour éviter les doublons.

---

### 1.3 Registre des factures et téléchargement incrémental ✅

**Implémentation** : `InvoiceRegistry` (JSON par provider dans `./factures/{provider}/`) — champs `provider`, `order_id`, `invoice_date`, `file_path`, `downloaded_at`.

**Livrables**

- [x] Registre JSON par provider (`invoice_registry.py`).
- [x] Mise à jour du registre à chaque téléchargement réussi.
- [x] Skip automatique si déjà présent (`is_downloaded(provider, order_id)`).
- [x] Paramètre `force_redownload` dans l’API, le schéma et le frontend (checkbox “Forcer le re-téléchargement”).
- [x] Endpoint `GET /api/last-download-date` → date max du registre pour un provider.
- [x] Frontend : option “Depuis la dernière fois” (mode par défaut) qui lit cette date et l’utilise comme `date_start`.
- [ ] Gestion des conflits : fichier supprimé manuellement mais présent dans le registre (non implémenté).

---

## Phase V2 — Multi-fournisseurs ✅ (largement réalisée)

### 2.1 Architecture cible

- **Un “provider” = un module de scraping** (classe ou module dédié) avec une interface commune, par exemple :
  - `login(credentials) -> bool`
  - `navigate_to_invoices() -> bool`
  - `list_orders_or_invoices() -> List[OrderInfo]`  (avec date, id, lien facture si possible)
  - `download_invoice(order_id / url) -> Optional[Path]`
  - `close() -> None`

- **Répertoires distincts par fournisseur**  
  - Ex. : `./factures/amazon/`, `./factures/fnac/`, `./factures/free/`, `./factures/bouygues/`, `./factures/decathlon/`, `./factures/leroy_merlin/`.  
  - Config (env ou YAML) : `DOWNLOAD_PATH` par défaut + mapping `provider -> path` optionnel.

- **Registre des factures**  
  - Étendre le registre V1 avec un champ `provider` pour chaque entrée (et un registre par provider ou un seul fichier avec `provider` en clé).

### 2.2 Fournisseurs à couvrir

| Fournisseur        | Statut             | Notes |
|--------------------|--------------------|--------|
| **Amazon**         | ✅ Fait (V0)       | Base actuelle. |
| **FNAC**           | ✅ Fait            | Téléchargement PDF Chrome CDP. |
| **Freebox**        | ✅ Fait            | Espace abonné adsl.free.fr. |
| **Free Mobile**    | ✅ Fait            | Espace abonné mobile.free.fr. |
| **Bouygues Telecom** | ✅ Fait          | Espace client, connexion auto + mode semi-manuel. |
| **Orange**         | ✅ Fait            | Connexion via profil navigateur + URL factures. |
| **Decathlon**      | ✅ Fait            | Pagination 30 pages, gestion commandes magasin/online/marketplace. |
| **Qobuz**          | ✅ Fait            | PDF via CDP printToPDF (Chrome), pagination `/profile/invoice`. |
| **Leroy Merlin**   | ⏳ À faire         | Compte client, historique, factures. |

Pour chaque fournisseur : étude des URLs de login, structure des pages “commandes” / “factures”, sélecteurs CSS/XPath, et gestion de la 2FA si présente.

### 2.3 Configuration et API

- **Credentials**  
  - Soit un fichier de config (ex. `providers.yaml`) avec par provider : `enabled`, `login_url`, `email_key`, `password_key` (noms des variables d’env), `download_path`.  
  - Soit variables d’env préfixées : `AMAZON_EMAIL`, `FNAC_EMAIL`, `FREE_EMAIL`, etc.

- **API**  
  - `POST /api/download` étendu : paramètre `provider` (ex. `amazon`, `fnac`, …).  
  - Ou endpoints dédiés : `POST /api/download/amazon`, `POST /api/download/fnac`, … avec un même schéma de réponse.  
  - Liste des providers disponibles : `GET /api/providers` (noms + statut configuré ou non).

**Livrables V2**

- [x] Interface commune (`InvoiceProviderProtocol` via duck typing) — `backend/providers/base.py`.
- [x] Implémentation Amazon refactorisée.
- [x] Implémentations FNAC, Free Mobile, Freebox, Bouygues, Orange, Decathlon, Qobuz.
- [x] Répertoires distincts par provider (`./factures/{provider}/`).
- [x] Registre des factures (`InvoiceRegistry`) avec champ `provider`.
- [x] Frontend : sélection du fournisseur (liste déroulante, uniquement les providers configurés).
- [ ] Leroy Merlin (non implémenté).
- [ ] Tests automatisés par provider (couverture ~35% actuellement).

---

## Phase V3 — Reconnaissance des factures et export Excel

### 3.1 Reconnaissance du contenu des factures (OCR / extraction)

**Objectif**  
Extraire des champs structurés depuis chaque facture PDF (fournisseur, date, numéro de facture, montant TTC/TVA, etc.) pour alimenter un export Excel et une base locale.

**Options techniques**

- **OCR**  
  - **Tesseract** (open source) sur les PDF rendus en images (par page).  
  - **pdf2image** + **pytesseract** ou **paddleocr** pour une meilleure précision sur tableaux.  
  - Services cloud (Google Vision, AWS Textract, Azure Document Intelligence) si budget et sensibilité des données le permettent.

- **Extraction sans OCR**  
  - Si le PDF contient du texte sélectionnable : **PyMuPDF (fitz)** ou **pdfplumber** pour extraire le texte et les tableaux, puis regex ou modèles légers pour repérer montants, dates, numéros de facture.

- **Modèles dédiés**  
  - Modèles type “document understanding” (layout detection + extraction de champs) pour factures : possibilité d’entraîner un petit modèle sur un jeu de factures annotées (FNAC, Free, etc.) pour améliorer la précision.

**Champs à extraire (prioritaires)**

- Fournisseur (ou déduire du nom de fichier / répertoire).
- Date de facture.
- Numéro de facture.
- Montant TTC.
- Montant TVA (si disponible).
- Devise.
- Adresse / SIRET (optionnel).

**Livrables V3**

- [ ] Choix de la stack (OCR open source vs cloud, extraction texte PDF).
- [ ] Pipeline : PDF → texte / structure → parsing (regex ou modèle) → dictionnaire structuré.
- [ ] Stockage des métadonnées extraites (dans le registre ou une table SQLite dédiée “invoice_metadata”).
- [ ] Gestion des échecs d’extraction (log, marquer “non extrait” dans le registre).

### 3.2 Remplissage d’un Excel

**Objectif**  
Un fichier Excel (ou CSV) listant toutes les factures avec les champs extraits, pour reporting et import dans un tableur ou un logiciel de compta.

**Implémentation**

- **Génération**  
  - Utiliser **openpyxl** (ou **xlsxwriter**) pour créer un classeur : une feuille “Factures” avec colonnes (Fournisseur, Date, N° facture, Montant TTC, TVA, Chemin fichier, etc.).  
  - Une ligne par facture enregistrée dans le registre (ou par entrée “invoice_metadata”).  
  - Option : bouton “Exporter en Excel” dans l’UI qui appelle un endpoint `GET /api/export/excel` (ou `POST` avec filtres date/provider).

- **Mise à jour**  
  - À chaque nouveau téléchargement + extraction : ajouter les lignes correspondantes au fichier Excel (ou régénérer le fichier à partir du registre / SQLite).  
  - Ou export “à la demande” : générer l’Excel à partir des métadonnées actuelles à chaque appel.

**Livrables V3 (suite)**

- [ ] Schéma de l’Excel (colonnes fixes ou configurables).
- [ ] Endpoint d’export Excel (et optionnel CSV).
- [ ] Lien dans le frontend : “Télécharger le récapitulatif Excel”.
- [ ] Option de filtre (date, fournisseur) pour l’export.

---

## Phase V4 — Fonctionnalités inspirées GetMyInvoices / Jenji

### 4.1 GetMyInvoices

- **Multi-sources**  
  - Déjà prévu en V2 (multi-fournisseurs).  
  - À plus long terme : import depuis une boîte mail (IMAP) pour récupérer les factures en pièce jointe, avec extraction automatique (OCR en V3).

- **Recherche et archivage**  
  - Recherche en texte intégral sur le contenu extrait (SQLite FTS ou Elasticsearch).  
  - Archivage long terme (rétention, compression) et conformité (ex. GoBD si besoin).

- **Export comptabilité**  
  - Export vers des formats utilisés par la compta (DATEV, CSV préformaté, etc.) en plus de l’Excel.

- **API**  
  - API REST complète (CRUD factures, liste, filtres, déclenchement de téléchargement) pour intégrations externes.

### 4.2 Jenji

- **Détection de doublons**  
  - Comparer nouvelle facture (hash ou métadonnées) avec le registre avant d’ajouter ; alerter si doublon potentiel.

- **TVA et catégories**  
  - Champs TVA et éventuellement catégorie de dépense dans l’Excel et le registre.  
  - Règles simples (par fournisseur ou par montant) pour pré-remplir la catégorie.

- **Tableau de bord**  
  - Statistiques : nombre de factures par fournisseur, par mois, montant total ; graphiques simples (frontend ou export).

- **Alertes**  
  - Notification (email ou log) si échec de connexion à un provider ou si aucune nouvelle facture depuis X jours (optionnel).

---

## Ordre de réalisation recommandé

1. ~~**V1.1** — Filtre par date.~~ ✅ Implémenté (year/month/months/date_start/date_end).
2. ~~**V1.2** — Date dans le nom de fichier.~~ ✅ Implémenté (format `{provider}_{date}_{id}.pdf`).
3. ~~**V1.3** — Registre des factures + téléchargement incrémental.~~ ✅ `InvoiceRegistry` + `force_redownload`.
4. ~~**V2** — Multi-fournisseurs.~~ ✅ Amazon, FNAC, Freebox, Free Mobile, Bouygues, Orange, Decathlon, Qobuz. Reste : Leroy Merlin.
5. **V3** — Extraction (PDF texte ou OCR) puis export Excel.
6. **V4** — Par thème (recherche, export compta, doublons, dashboard) selon priorité métier.

---

## Stack technique suggérée (résumé)

| Besoin              | Technologie suggérée                    |
|---------------------|-----------------------------------------|
| Scraping            | Selenium (déjà en place)                |
| Registre / métadonnées | SQLite ou JSON                      |
| OCR                 | PyMuPDF + pdfplumber en priorité ; Tesseract ou PaddleOCR si besoin |
| Excel               | openpyxl                               |
| Config providers    | Fichier YAML ou variables d’env         |
| API                 | FastAPI (déjà en place)                 |
| Frontend            | React (déjà en place), choix provider + options export |

---

## Fichiers et dossiers à prévoir

- `backend/providers/` — Modules par fournisseur (amazon.py, fnac.py, …) et interface commune.
- `backend/services/invoice_registry.py` — Gestion du registre (écriture, lecture, vérification “déjà téléchargé”).
- `backend/services/extraction.py` — Pipeline OCR / extraction PDF.
- `backend/services/excel_export.py` — Génération du fichier Excel.
- `backend/models/provider_config.py` — Config et schémas par provider.
- `data/` ou `./factures/.registry/` — Registre (SQLite ou JSON) et éventuellement cache.
- Configuration : `config/providers.yaml` ou équivalent + `.env` par provider.

Ce plan peut servir de base pour des tickets (issues) ou des tâches dans un outil de suivi de projet.
