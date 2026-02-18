# Changelog

Toutes les modifications notables de ce projet seront documentées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [1.3.0] - 2026-02-12 — V1 Plan d'amélioration

### Ajouté

- **Filtre par date** : les paramètres `year` et `month` filtrent désormais les commandes (parsing de la date "Commandé le …" sur chaque bloc). Les commandes sans date sont ignorées lorsque le filtre est actif.
- **Date dans le nom de fichier** : les factures sont enregistrées au format `amazon_YYYY-MM-DD_<order_id>.pdf` lorsque la date de commande est détectée, sinon `facture_<index>_<timestamp>.pdf`.
- **Registre des factures** : fichier `.invoice_registry.json` dans le dossier de téléchargement pour lister les factures déjà téléchargées (provider, order_id, date, chemin).
- **Téléchargement incrémental** : les factures déjà présentes dans le registre (et dont le fichier existe) sont ignorées sauf si `force_redownload=true`.
- **API** : paramètre `force_redownload` dans la requête de téléchargement pour forcer un nouveau téléchargement.

### Technique

- Nouveau module `backend.services.invoice_registry.InvoiceRegistry` (chargement/sauvegarde JSON).
- Méthodes `_parse_order_date_from_element`, `_get_order_id_from_element`, `_filter_orders_by_date` dans le downloader Amazon.

## [1.2.0] - 2026-02-12

### Ajouté

- **Connexion continue** : option `SELENIUM_KEEP_BROWSER_OPEN` pour laisser le navigateur ouvert à l'arrêt de l'application
- **Pagination des commandes** : téléchargement sur toutes les pages d'historique Amazon (passage automatique à la page suivante)
- Scripts start.ps1 / stop.ps1 convertis en UTF-8 BOM pour éviter les erreurs d'encodage sous PowerShell

### Corrigé

- stop.ps1 : variable `$pid` renommée en `$procId` (conflit avec la variable automatique PowerShell)
- Backend : imports regroupés et nettoyés (suppression de JSONResponse inutilisé)
- Amazon downloader : suppression de l'import `os` redondant, utilisation de `pathlib.Path` pour les chemins ChromeDriver
- Frontend : suppression des `console.log` de debug

### Améliorations

- Code backend et frontend nettoyé pour une base V0 stable
- Documentation et tests alignés sur la version 1.2

## [1.1.0] - 2026-02-11

### Ajouté

- Scripts de lancement automatique (start.ps1, start.sh, stop.ps1, stop.sh)
- Validation automatique de la configuration au démarrage
- 9 nouveaux tests (couverture passée de 23% à 35%)
- Fichier .env.example pour faciliter la configuration
- Documentation enrichie avec changelog et liens rapides

### Corrigé

- ChromeDriver : Problème d'initialisation du driver Selenium résolu
- Configuration : Encodage UTF-8, espaces blancs, BOM supprimés
- FastAPI : Migration de @app.on_event() vers lifespan handlers modernes
- TypeScript : Tous les warnings résolus (types de retour ajoutés)
- Tests : test_login_success corrigé et passe avec succès

### Améliorations

- Tests : 4/5 (80%) → 14/14 (100%) passants
- Couverture : 23% → 35% (+52%)
- Build : 7 warnings → 0 warning
- Expérience utilisateur : Démarrage en une commande

Pour plus de détails, consultez le README.md section "Changelog Détaillé".

## [1.0.0] - Version initiale

- Application de téléchargement de factures Amazon
- Backend FastAPI + Frontend React/TypeScript
- Support Selenium (Chrome/Firefox)
- Authentification Amazon avec 2FA
- Tests unitaires de base
