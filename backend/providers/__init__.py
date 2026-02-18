"""
Providers de factures (V2 multi-fournisseurs).

Chaque module dans ce package implémente InvoiceProviderProtocol.
Le registre PROVIDERS liste les providers disponibles (implémentés + à venir).
"""
from backend.providers.base import InvoiceProviderProtocol, OrderInfo
from backend.providers.amazon import AmazonProvider
from backend.providers.freebox import FreeboxProvider

# Registre des providers implémentés : id -> classe
PROVIDERS = {
    AmazonProvider.PROVIDER_ID: AmazonProvider,
    FreeboxProvider.PROVIDER_ID: FreeboxProvider,
}

# Providers prévus (affichage frontend) : id -> libellé
PROVIDER_LABELS: dict[str, str] = {
    "amazon": "Amazon",
    "fnac": "FNAC",
    "freebox": "Freebox",
    "bouygues": "Bouygues Telecom",
    "decathlon": "Decathlon",
    "leroy_merlin": "Leroy Merlin",
}

__all__ = [
    "InvoiceProviderProtocol",
    "OrderInfo",
    "AmazonProvider",
    "FreeboxProvider",
    "PROVIDERS",
    "PROVIDER_LABELS",
]
