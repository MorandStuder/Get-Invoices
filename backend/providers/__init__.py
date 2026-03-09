"""
Providers de factures (V2 multi-fournisseurs).

Chaque module dans ce package implémente InvoiceProviderProtocol.
Le registre PROVIDERS liste les providers disponibles (implémentés + à venir).
"""
from backend.providers.base import InvoiceProviderProtocol, OrderInfo
from backend.providers.amazon import AmazonProvider
from backend.providers.freebox import FreeboxProvider
from backend.providers.free_mobile import FreeMobileProvider
from backend.providers.fnac import FnacProvider
from backend.providers.bouygues import BouyguesProvider
from backend.providers.orange import OrangeProvider

# Registre des providers implémentés : id -> classe
PROVIDERS = {
    AmazonProvider.PROVIDER_ID: AmazonProvider,
    FreeboxProvider.PROVIDER_ID: FreeboxProvider,
    FreeMobileProvider.PROVIDER_ID: FreeMobileProvider,
    FnacProvider.PROVIDER_ID: FnacProvider,
    BouyguesProvider.PROVIDER_ID: BouyguesProvider,
    OrangeProvider.PROVIDER_ID: OrangeProvider,
}

# Providers prévus (affichage frontend) : id -> libellé
PROVIDER_LABELS: dict[str, str] = {
    "amazon": "Amazon",
    "fnac": "FNAC",
    "freebox": "Freebox",
    "free_mobile": "Free Mobile",
    "bouygues": "Bouygues Telecom",
    "orange": "Orange",
    "decathlon": "Decathlon",
    "leroy_merlin": "Leroy Merlin",
}

__all__ = [
    "InvoiceProviderProtocol",
    "OrderInfo",
    "AmazonProvider",
    "FreeboxProvider",
    "FreeMobileProvider",
    "FnacProvider",
    "BouyguesProvider",
    "OrangeProvider",
    "PROVIDERS",
    "PROVIDER_LABELS",
]
