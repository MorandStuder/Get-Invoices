"""
Interface commune pour les fournisseurs de factures (V2 multi-provider).

Chaque provider (Amazon, FNAC, Free, etc.) expose les mêmes entrées : login,
navigation vers les factures, téléchargement. On utilise un Protocol pour
permettre des implémentations par composition (wrapper) sans héritage forcé.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, Union


@dataclass
class OrderInfo:
    """Information minimale sur une commande/facture (pour list_orders_or_invoices)."""
    order_id: str
    invoice_date: Optional[date] = None
    invoice_url: Optional[str] = None
    raw_element: Any = None  # Élément DOM ou donnée brute selon le provider


class InvoiceProviderProtocol(Protocol):
    """
    Contrat commun pour un fournisseur de factures.

    - login : authentification (credentials injectées au constructeur ou via config).
    - navigate_to_invoices : aller sur la page des commandes/factures.
    - download_invoices : télécharger les factures (filtres optionnels).
    - close : libérer le navigateur / ressources.
    """

    @property
    def provider_id(self) -> str:
        """Identifiant court du provider (ex: 'amazon', 'fnac')."""
        ...

    async def login(self, otp_code: Optional[str] = None) -> bool:
        """Connecte l'utilisateur au compte fournisseur. Retourne True si succès."""
        ...

    async def navigate_to_invoices(self) -> bool:
        """Navigue vers la page des commandes/factures. Retourne True si succès."""
        ...

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """
        Liste les commandes/factures visibles sur la page actuelle.
        Optionnel : certains providers font tout dans download_invoices.
        """
        ...

    async def download_invoice(
        self,
        order_or_id: Union[Any, str],
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        """Télécharge une facture pour une commande. Retourne le nom du fichier ou None."""
        ...

    async def download_invoices(
        self,
        max_invoices: int = 100,
        year: Optional[int] = None,
        month: Optional[int] = None,
        months: Optional[List[int]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        otp_code: Optional[str] = None,
        force_redownload: bool = False,
    ) -> Dict[str, Union[List[str], int]]:
        """
        Télécharge les factures selon les filtres.
        Retourne {"count": int, "files": List[str]}.
        """
        ...

    async def close(self) -> None:
        """Ferme le navigateur et libère les ressources."""
        ...

    def is_2fa_required(self) -> bool:
        """Indique si un code 2FA est actuellement requis."""
        ...

    async def submit_otp(self, otp_code: str) -> bool:
        """Soumet un code OTP pour la 2FA. Retourne True si accepté."""
        ...
