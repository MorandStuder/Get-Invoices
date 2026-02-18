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

## Phase V1 — Robustesse et déduplication (filtre date + nom fichier + liste)

### 1.1 Filtre par date (actuellement non fonctionnel)

**Problème actuel**  
Les paramètres `year` et `month` sont acceptés par l’API et le service mais ne sont pas utilisés pour filtrer les commandes.

**Pistes d’implémentation**

- **Option A — Côté Amazon (idéal)**  
  - Utiliser les filtres d’historique de commandes Amazon s’ils existent (paramètres d’URL ou filtres de la page).  
  - Documenter l’URL / les paramètres pour “order history” par année ou par période (si disponibles).

- **Option B — Côté scraping**  
  - Après récupération des blocs “commande” sur chaque page, parser la date de commande (texte ou attribut) et ignorer les commandes hors période (`year`, `month` ou plage personnalisée).  
  - Définir un format de date affiché par Amazon (ex. “Commande du 15 janvier 2025”) et un parsing robuste (regex ou petit parseur de dates).

- **Option C — Post-téléchargement**  
  - Télécharger toutes les factures de la page (ou jusqu’à une limite), puis déplacer/supprimer les PDF dont la date extraite (via OCR ou métadonnées) est hors période.  
  - Moins efficace ; à réserver si Amazon ne permet aucun filtre ni parsing de date fiable dans le HTML.

**Livrables**

- [ ] Décider de l’option (A, B ou C) après exploration du HTML des pages “historique commandes” Amazon.
- [ ] Implémenter le filtre dans `download_invoices()` (utilisation effective de `year` / `month`).
- [ ] Exposer éventuellement une plage de dates (date début / date fin) dans l’API et le schéma `DownloadRequest`.
- [ ] Tests unitaires sur le filtre (mock de listes de commandes avec dates).

---

### 1.2 Date de facture dans le nom de fichier

**Objectif**  
Nommer les fichiers avec la date de la facture (et non seulement l’index et l’horodatage de téléchargement) pour un tri et une recherche plus simples.

**Implémentation**

- Parser la date de commande/facture depuis la page (même logique que pour le filtre par date) ou, en V3, depuis l’OCR du PDF.
- Format de nom proposé :  
  `{fournisseur}_{date_facture}_{identifiant_commande}.pdf`  
  ex. `amazon_2025-01-15_123-4567890-1234567.pdf`  
  Si la date n’est pas disponible : fallback sur la date du jour ou horodatage actuel (comportement actuel).
- Adapter `_download_pdf_from_url()` (ou la fonction qui génère le nom) pour accepter une date optionnelle et formater le nom en conséquence.

**Livrables**

- [ ] Définir le format de nom (configurable via config ou constante).
- [ ] Passer la date de commande/facture jusqu’à la fonction d’écriture du PDF.
- [ ] Conserver un identifiant (ex. order_id) pour éviter les doublons de noms.

---

### 1.3 Liste des factures déjà téléchargées et téléchargement incrémental

**Objectif**  
Éviter de retélécharger les factures déjà présentes : garder une liste (ou un registre) des factures téléchargées et ne télécharger que les nouvelles.

**Implémentation**

- **Registre local**  
  - Fichier JSON ou SQLite (ex. `factures_registry.json` ou `get_invoices.db`) à la racine du dossier de téléchargement ou dans un dossier dédié (ex. `./data/`).  
  - Champs utiles : `provider`, `order_id`, `invoice_date`, `file_path`, `downloaded_at`, `file_hash` (optionnel, pour détecter les fichiers modifiés).

- **Logique**  
  - Avant de télécharger une facture pour une commande donnée, vérifier si `(provider, order_id)` (et éventuellement `invoice_date`) est déjà dans le registre et si le fichier existe.  
  - Si oui : skip (et optionnellement log “déjà téléchargé”).  
  - Si non : télécharger, enregistrer le chemin et les métadonnées dans le registre.

- **API**  
  - Possibilité d’un paramètre `force_redownload=true` pour ignorer le registre et tout retélécharger.  
  - Endpoint optionnel `GET /api/downloaded` pour lister les factures déjà enregistrées (pour debug ou affichage dans l’UI).

**Livrables**

- [ ] Modèle de données du registre (schéma du JSON ou schéma SQLite).
- [ ] Création/mise à jour du registre à chaque téléchargement réussi.
- [ ] Intégration dans la boucle de téléchargement (skip si déjà présent).
- [ ] Paramètre `force_redownload` dans l’API et le frontend (optionnel).
- [ ] Gestion des conflits (fichier supprimé manuellement mais présent dans le registre : recréer ou marquer “manquant”).

---

## Phase V2 — Multi-fournisseurs (FNAC, Free, Bouygues, Decathlon, Leroy Merlin)

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

| Fournisseur        | Difficulté estimée | Notes |
|--------------------|--------------------|--------|
| **Amazon**         | Fait (V0)          | Base actuelle. |
| **FNAC**           | Moyenne            | Compte client, historique commandes, téléchargement factures PDF. |
| **Free**           | Moyenne            | Espace client Free, factures / récap. |
| **Bouygues Telecom** | Moyenne          | Espace client, facturation. |
| **Decathlon**      | Moyenne            | Compte client, commandes, factures. |
| **Leroy Merlin**   | Moyenne            | Compte client, historique, factures. |

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

- [ ] Interface commune (classe abstraite ou protocole) pour un provider.
- [ ] Implémentation Amazon refactorisée pour respecter cette interface.
- [ ] Implémentations FNAC, Free, Bouygues, Decathlon, Leroy Merlin (une par une, avec tests manuels puis automatisés).
- [ ] Répertoires distincts et configuration par provider.
- [ ] Registre étendu avec `provider`.
- [ ] Frontend : choix du fournisseur (liste déroulante ou onglets) avant lancement du téléchargement.

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

1. **V1.1** — Filtre par date (option B ou A selon ce que permet Amazon).  
2. **V1.2** — Date dans le nom de fichier.  
3. **V1.3** — Registre des factures + téléchargement incrémental.  
4. **V2** — Un premier autre fournisseur (ex. FNAC) pour valider l’architecture multi-provider, puis les autres.  
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
