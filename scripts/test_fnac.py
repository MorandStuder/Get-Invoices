#!/usr/bin/env python3
"""
Script de test manuel du provider FNAC.
Lance un téléchargement FNAC via l'API (backend doit être démarré).
Usage: python scripts/test_fnac.py [--max 5] [--base-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("Installez requests: pip install requests")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test manuel du provider FNAC")
    parser.add_argument("--max", type=int, default=3, help="Nombre max de factures (défaut: 3)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="URL de l'API")
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/api/download"
    payload = {"provider": "fnac", "max_invoices": args.max}

    print(f"Appel POST {url} avec {json.dumps(payload)}")
    print("(Le backend doit être démarré et FNAC_LOGIN/FNAC_PASSWORD configurés dans .env)\n")

    try:
        r = requests.post(url, json=payload, stream=True, timeout=120)
        if r.status_code != 200:
            print(f"Erreur {r.status_code}: {r.text[:500]}")
            return 1
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if "message" in data:
                print(data["message"])
            if "count" in data:
                print(f"\nTerminé: {data.get('count', 0)} facture(s) téléchargée(s)")
                if data.get("files"):
                    for f in data["files"]:
                        print(f"  - {f}")
            if "error" in data:
                print(f"Erreur: {data.get('error', data)}")
                return 1
        return 0
    except requests.exceptions.ConnectionError:
        print("Impossible de se connecter. Démarrez le backend (ex: ./start.ps1) puis réessayez.")
        return 1
    except Exception as e:
        print(f"Erreur: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
