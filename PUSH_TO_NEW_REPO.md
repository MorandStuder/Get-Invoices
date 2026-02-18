# Pousser Get-Invoices vers son propre dépôt GitHub

1. Crée le dépôt sur GitHub : https://github.com/new  
   - Nom : **Get-Invoices**  
   - Ne pas ajouter de README (dépôt vide).

2. Depuis PowerShell, à la racine du dépôt parent (C:\Users\moran\Dropbox\GitHub) :

```powershell
cd "C:\Users\moran\Dropbox\GitHub"
git push https://github.com/MorandStuder/Get-Invoices.git get-invoices-standalone:main
```

3. Va sur https://github.com/MorandStuder/Get-Invoices : le projet sera là en entier.

Optionnel : pour que le dossier Get-Invoices local pointe vers ce nouveau dépôt (pour les prochains push) :

```powershell
cd "C:\Users\moran\Dropbox\GitHub\Get-Invoices"
git init
git remote add origin https://github.com/MorandStuder/Get-Invoices.git
git fetch ..
# puis lier la branche locale à main (à faire une fois le push ci-dessus effectué)
```

En fait le plus simple : garder le dépôt parent comme il est. Pour pousser les mises à jour de Get-Invoices vers le dépôt séparé plus tard :

```powershell
cd "C:\Users\moran\Dropbox\GitHub"
git subtree split -P Get-Invoices -b get-invoices-standalone
git push https://github.com/MorandStuder/Get-Invoices.git get-invoices-standalone:main
```
