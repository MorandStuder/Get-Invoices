# Pousser Get-Invoices vers son propre dépôt GitHub

Ce dossier est maintenant un **dépôt Git indépendant** (son propre `.git`).

## 1. Créer le dépôt sur GitHub

- Va sur https://github.com/new
- Nom du dépôt : **Get-Invoices**
- Ne coche pas "Add a README" (dépôt vide)
- Crée le dépôt

## 2. Lier et pousser

Dans PowerShell, depuis ce dossier (`Get-Invoices`) :

```powershell
cd "C:\Users\moran\Dropbox\GitHub\Get-Invoices"
git remote add origin https://github.com/MorandStuder/Get-Invoices.git
git push -u origin main
```

(Remplace `MorandStuder` par ton identifiant GitHub si besoin.)

Après ça, les prochains `git push` iront vers ce dépôt.
