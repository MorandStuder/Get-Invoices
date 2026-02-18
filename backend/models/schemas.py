"""
Schémas Pydantic pour les requêtes et réponses de l'API.
"""
from pydantic import BaseModel, Field
from typing import Annotated, List, Optional


class DownloadRequest(BaseModel):
    """Requête pour télécharger des factures."""
    provider: Optional[str] = Field(
        default="amazon",
        description="Fournisseur (amazon, fnac, free, …). Défaut: amazon"
    )
    max_invoices: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description="Nombre maximum de factures à télécharger"
    )
    year: Optional[int] = Field(
        default=None,
        ge=2020,
        le=2030,
        description="Année des factures à télécharger"
    )
    month: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Mois des factures à télécharger (un seul, si months non fourni)"
    )
    months: Optional[List[Annotated[int, Field(ge=1, le=12)]]] = Field(
        default=None,
        description="Plusieurs mois (1-12) pour l'année donnée ; prioritaire sur month si fourni"
    )
    date_start: Optional[str] = Field(
        default=None,
        description="Début de plage au format YYYY-MM-DD (prioritaire sur year/month si avec date_end)"
    )
    date_end: Optional[str] = Field(
        default=None,
        description="Fin de plage au format YYYY-MM-DD"
    )
    force_redownload: Optional[bool] = Field(
        default=False,
        description="Si True, retélécharge les factures déjà présentes dans le registre"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "max_invoices": 50,
                "year": 2024,
                "month": 1,
                "force_redownload": False
            }
        }


class DownloadResponse(BaseModel):
    """Réponse après téléchargement de factures."""
    success: bool
    message: str
    count: int
    files: List[str] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """Réponse de statut de l'API."""
    status: str
    message: str


class OTPRequest(BaseModel):
    """Requête pour soumettre un code OTP."""
    otp_code: str = Field(
        ...,
        min_length=4,
        max_length=10,
        description="Code OTP reçu (SMS, email ou application)"
    )


class OTPResponse(BaseModel):
    """Réponse après soumission d'un code OTP."""
    success: bool
    message: str
    requires_otp: bool = Field(
        default=False,
        description="Indique si un code OTP est toujours requis"
    )


class ProviderInfo(BaseModel):
    """Information sur un fournisseur (liste /api/providers)."""
    id: str
    name: str
    configured: bool = Field(description="True si identifiants/config disponibles")
    implemented: bool = Field(description="True si le provider est implémenté")


class ProvidersResponse(BaseModel):
    """Réponse de la liste des fournisseurs."""
    providers: List[ProviderInfo]
