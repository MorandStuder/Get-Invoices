"""
Registre des factures déjà téléchargées (V1).
Permet de ne télécharger que les factures non encore présentes.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REGISTRY_FILENAME = ".invoice_registry.json"
PROVIDER_AMAZON = "amazon"


class InvoiceRegistry:
    """
    Registre persistant (JSON) des factures téléchargées par provider et order_id.
    """

    def __init__(self, download_path: Path) -> None:
        self.download_path = Path(download_path)
        self._file = self.download_path / REGISTRY_FILENAME
        self._data: Dict[str, List[Dict[str, Any]]] = {}

    def _load(self) -> None:
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Registre invalide ou illisible, reinitialisation: %s", e)
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.download_path.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _entries(self, provider: str) -> List[Dict[str, Any]]:
        if provider not in self._data:
            self._data[provider] = []
        return self._data[provider]

    def is_downloaded(
        self,
        provider: str,
        order_id: str,
        check_file_exists: bool = True,
    ) -> bool:
        """Retourne True si la facture (provider, order_id) est déjà enregistrée (et fichier présent si demandé)."""
        self._load()
        for entry in self._entries(provider):
            if entry.get("order_id") == order_id:
                if check_file_exists:
                    path = self.download_path / entry.get("file_path", "")
                    return path.exists()
                return True
        return False

    def add(
        self,
        provider: str,
        order_id: str,
        file_path: str,
        invoice_date: Optional[str] = None,
    ) -> None:
        """Enregistre une facture téléchargée."""
        self._load()
        # Éviter doublon
        entries = self._entries(provider)
        for e in entries:
            if e.get("order_id") == order_id:
                e["file_path"] = file_path
                e["invoice_date"] = invoice_date
                e["downloaded_at"] = datetime.utcnow().isoformat() + "Z"
                self._save()
                return
        entries.append({
            "order_id": order_id,
            "file_path": file_path,
            "invoice_date": invoice_date,
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
        })
        self._save()

    def list_downloaded(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Liste les factures enregistrées (optionnellement pour un provider)."""
        self._load()
        if provider:
            return list(self._entries(provider))
        result: List[Dict[str, Any]] = []
        for p, entries in self._data.items():
            for e in entries:
                result.append({"provider": p, **e})
        return result
