"""
Point d'entrée principal de l'API FastAPI (Get-Invoices V2 multi-fournisseurs).
"""
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

# Timeout max pour un téléchargement (évite que la requête reste bloquée indéfiniment)
DOWNLOAD_TIMEOUT_SECONDS = 600  # 10 minutes

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from logging.handlers import RotatingFileHandler
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.models.schemas import (
    DownloadRequest,
    DownloadResponse,
    OTPRequest,
    OTPResponse,
    StatusResponse,
    ProviderInfo,
    ProvidersResponse,
)
from backend.providers import PROVIDERS, PROVIDER_LABELS
from backend.providers.amazon import AmazonProvider
from backend.providers.freebox import FreeboxProvider

# Racine du projet (où se trouve .env), quel que soit le répertoire de travail au démarrage
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Configuration de l'application."""
    amazon_email: str
    amazon_password: str
    download_path: str = "./factures"
    max_invoices: int = 100
    selenium_headless: bool = False
    selenium_timeout: int = 30
    selenium_manual_mode: bool = False  # Mode manuel : laisse le navigateur ouvert pour saisie manuelle
    selenium_browser: str = "chrome"  # "chrome" ou "firefox"
    firefox_profile_path: Optional[str] = None  # Chemin vers le profil Firefox existant (session persistante)
    selenium_chrome_profile_dir: Optional[str] = None  # Répertoire de profil Chrome (session persistante, ex: ./browser_profile)
    selenium_keep_browser_open: bool = False  # Connexion continue : ne pas fermer le navigateur à l'arrêt de l'app
    # Freebox (optionnel)
    freebox_login: Optional[str] = None  # Identifiant Freebox (email @free.fr ou login Freebox)
    freebox_password: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    def validate_settings(self) -> None:
        """Valide les paramètres de configuration."""
        errors = []

        # Vérifier que l'email est fourni
        if not self.amazon_email or self.amazon_email == "votre_email@example.com":
            errors.append("AMAZON_EMAIL n'est pas configuré ou utilise la valeur par défaut")

        # Vérifier que le mot de passe est fourni
        if not self.amazon_password or self.amazon_password == "votre_mot_de_passe":
            errors.append("AMAZON_PASSWORD n'est pas configuré ou utilise la valeur par défaut")

        # Vérifier que le navigateur est valide
        if self.selenium_browser not in ["chrome", "firefox"]:
            errors.append(f"SELENIUM_BROWSER doit être 'chrome' ou 'firefox', pas '{self.selenium_browser}'")

        # Vérifier que le timeout est raisonnable
        if self.selenium_timeout < 10 or self.selenium_timeout > 300:
            errors.append(f"SELENIUM_TIMEOUT doit être entre 10 et 300 secondes, pas {self.selenium_timeout}")

        # Vérifier que max_invoices est positif
        if self.max_invoices <= 0:
            errors.append(f"MAX_INVOICES doit être positif, pas {self.max_invoices}")

        if self.firefox_profile_path and self.selenium_browser != "firefox":
            errors.append(
                f"FIREFOX_PROFILE_PATH est défini mais SELENIUM_BROWSER='{self.selenium_browser}'. "
                "Le profil Firefox sera ignoré."
            )
        if self.selenium_chrome_profile_dir and self.selenium_browser != "chrome":
            errors.append(
                f"SELENIUM_CHROME_PROFILE_DIR est défini mais SELENIUM_BROWSER='{self.selenium_browser}'. "
                "Le profil Chrome sera ignoré."
            )

        if errors:
            error_msg = "Erreurs de configuration détectées:\n" + "\n".join(f"  - {err}" for err in errors)
            raise ValueError(error_msg)


# Créer le dossier logs s'il n'existe pas
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Configuration du logging avec fichier et console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        # Handler pour fichier avec rotation
        RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        ),
        # Handler pour console
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Chargement des paramètres
try:
    settings = Settings()
    settings.validate_settings()
    logger.info(
        "Configuration chargée et validée (env_file=%s, email=%s)",
        _ENV_FILE,
        (settings.amazon_email[:3] + "***") if settings.amazon_email else "non défini",
    )
except ValueError as e:
    logger.error(f"Erreur de configuration: {e}")
    logger.error("Veuillez vérifier votre fichier .env à la racine du projet")
    raise
except Exception as e:
    logger.error(f"Erreur lors du chargement de la configuration: {e}")
    logger.error("Assurez-vous que le fichier .env existe à la racine du projet")
    raise

# Dictionnaire des downloaders par provider (V2 multi-fournisseurs)
downloaders: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Gestionnaire du cycle de vie de l'application.
    Initialise les providers configurés (Amazon par défaut) avec répertoire par fournisseur.
    """
    global downloaders
    downloaders = {}
    base_path = Path(settings.download_path)

    # Amazon : répertoire ./factures/amazon (ou DOWNLOAD_PATH/amazon)
    if AmazonProvider.PROVIDER_ID in PROVIDERS:
        try:
            logger.info("Initialisation du provider Amazon...")
            amazon_path = base_path / "amazon"
            amazon_path.mkdir(parents=True, exist_ok=True)
            downloaders[AmazonProvider.PROVIDER_ID] = AmazonProvider(
                email=settings.amazon_email,
                password=settings.amazon_password,
                download_path=amazon_path,
                headless=settings.selenium_headless,
                timeout=settings.selenium_timeout,
                manual_mode=settings.selenium_manual_mode,
                browser=settings.selenium_browser,
                firefox_profile_path=settings.firefox_profile_path,
                chrome_user_data_dir=settings.selenium_chrome_profile_dir,
                keep_browser_open=settings.selenium_keep_browser_open,
            )
            logger.info("Provider Amazon initialisé avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation du provider Amazon: {str(e)}")
            import traceback
            logger.debug(traceback.format_exc())

    # Freebox (si identifiants présents)
    if FreeboxProvider.PROVIDER_ID in PROVIDERS:
        if settings.freebox_login and settings.freebox_password:
            try:
                logger.info("Initialisation du provider Freebox...")
                freebox_path = base_path / "freebox"
                freebox_path.mkdir(parents=True, exist_ok=True)
                downloaders[FreeboxProvider.PROVIDER_ID] = FreeboxProvider(
                    login=settings.freebox_login,
                    password=settings.freebox_password,
                    download_path=freebox_path,
                    headless=settings.selenium_headless,
                    timeout=settings.selenium_timeout,
                    browser=settings.selenium_browser,
                    firefox_profile_path=settings.firefox_profile_path,
                    chrome_user_data_dir=settings.selenium_chrome_profile_dir,
                    keep_browser_open=settings.selenium_keep_browser_open,
                )
                logger.info("Provider Freebox initialisé avec succès")
            except Exception as e:
                logger.warning("Provider Freebox non initialisé: %s", e)
        else:
            logger.debug("Freebox non configuré (FREEBOX_LOGIN / FREEBOX_PASSWORD absents)")

    yield

    # Shutdown : fermer tous les providers
    for pid, prov in list(downloaders.items()):
        try:
            await prov.close()
            logger.info("Provider %s fermé", pid)
        except Exception as e:
            logger.warning("Fermeture provider %s: %s", pid, e)


# Initialisation de l'application (V2 : multi-fournisseurs)
app = FastAPI(
    title="Get-Invoices API",
    description="API pour télécharger automatiquement les factures (Amazon, FNAC, Free, …)",
    version="2.0.0",
    lifespan=lifespan
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_downloader(provider_id: str | None) -> Any:
    """Retourne le downloader du provider ou None si non disponible."""
    pid = (provider_id or "amazon").strip().lower()
    return downloaders.get(pid)


@app.get("/", response_model=StatusResponse)
async def root() -> StatusResponse:
    """Endpoint de statut de l'API."""
    return StatusResponse(
        status="ok",
        message="API Get-Invoices (V2 multi-fournisseurs) opérationnelle"
    )


@app.get("/api/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    """Liste les fournisseurs disponibles et leur statut (configuré, implémenté)."""
    providers_list = []
    for pid, name in PROVIDER_LABELS.items():
        implemented = pid in PROVIDERS
        configured = False
        if pid == "amazon":
            configured = (
                bool(settings.amazon_email)
                and settings.amazon_email != "votre_email@example.com"
                and bool(settings.amazon_password)
                and settings.amazon_password != "votre_mot_de_passe"
            )
        elif pid == "freebox":
            configured = bool(settings.freebox_login) and bool(settings.freebox_password)
        if implemented:
            configured = configured or pid in downloaders
        providers_list.append(
            ProviderInfo(id=pid, name=name, configured=configured, implemented=implemented)
        )
    return ProvidersResponse(providers=providers_list)


@app.get("/api/debug")
async def debug_info() -> dict:
    """Endpoint de debug pour diagnostiquer les problèmes."""
    amazon = _get_downloader("amazon")
    debug_info = {
        "downloaders": list(downloaders.keys()),
        "settings_loaded": settings is not None,
        "has_email": bool(settings.amazon_email) if settings else False,
        "has_password": bool(settings.amazon_password) if settings else False,
    }
    if amazon:
        try:
            debug_info["driver_initialized"] = amazon._downloader.driver is not None
            debug_info["2fa_required"] = amazon.is_2fa_required()
        except Exception as e:
            debug_info["driver_error"] = str(e)
    return debug_info


@app.post("/api/download")
async def download_invoices(
    request: DownloadRequest,
    otp_code: Optional[str] = None
) -> StreamingResponse:
    """
    Télécharge les factures du fournisseur demandé (Amazon, Freebox, etc.).
    Retourne un flux SSE : événements progress (progression) puis done (résultat) ou error.
    """
    provider_id = (request.provider or "amazon").strip().lower()
    downloader = _get_downloader(provider_id)
    if not downloader:
        if provider_id in PROVIDER_LABELS and provider_id not in PROVIDERS:
            raise HTTPException(
                status_code=501,
                detail=f"Le fournisseur '{provider_id}' n'est pas encore implémenté"
            )
        raise HTTPException(
            status_code=503,
            detail=f"Le fournisseur '{provider_id}' n'est pas configuré ou initialisé"
        )

    progress_queue: asyncio.Queue[tuple[str, Any, Any, Any]] = asyncio.Queue()

    async def on_progress(current: int, total: int, message: str) -> None:
        await progress_queue.put(("progress", current, total, message))

    async def run_download() -> None:
        try:
            result = await asyncio.wait_for(
                downloader.download_invoices(
                    max_invoices=request.max_invoices or settings.max_invoices,
                    year=request.year,
                    month=request.month,
                    months=request.months,
                    date_start=request.date_start,
                    date_end=request.date_end,
                    otp_code=otp_code,
                    force_redownload=request.force_redownload or False,
                    on_progress=on_progress,
                ),
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
            await progress_queue.put(("done", result, None, None))
        except asyncio.TimeoutError:
            await progress_queue.put(("error", "timeout", None, None))
        except Exception as e:
            import traceback
            logger.error("Erreur lors du téléchargement: %s", e)
            logger.debug("Traceback: %s", traceback.format_exc())
            await progress_queue.put(("error", str(e), None, None))

    logger.info(
        "Démarrage téléchargement provider=%s max_invoices=%s year=%s month=%s otp=%s",
        provider_id, request.max_invoices, request.year, request.month, "fourni" if otp_code else "non fourni"
    )
    task = asyncio.create_task(run_download())

    async def event_stream() -> AsyncIterator[str]:
        while True:
            item = await progress_queue.get()
            kind = item[0]
            if kind == "progress":
                _, current, total, message = item
                payload = json.dumps({"current": current, "total": total, "message": message or ""})
                yield f"event: progress\ndata: {payload}\n\n"
            elif kind == "done":
                _, result, _, _ = item
                data = {
                    "success": True,
                    "message": f"{result['count']} facture(s) téléchargée(s)",
                    "count": result["count"],
                    "files": result.get("files", []),
                }
                yield f"event: done\ndata: {json.dumps(data)}\n\n"
                break
            elif kind == "error":
                _, err_msg, _, _ = item
                is_2fa = "Code 2FA requis" in (err_msg or "") or (downloader.is_2fa_required() if downloader else False)
                payload = json.dumps({"detail": err_msg or "Erreur", "requires_otp": is_2fa})
                yield f"event: error\ndata: {payload}\n\n"
                break
        await task  # consommer la tâche pour éviter warning

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Retourne le statut du téléchargeur (Amazon par défaut)."""
    downloader = _get_downloader("amazon")
    if not downloader:
        return StatusResponse(
            status="error",
            message="Le téléchargeur Amazon n'est pas initialisé"
        )
    try:
        if downloader.is_2fa_required():
            return StatusResponse(
                status="otp_required",
                message="Code 2FA requis - veuillez fournir le code OTP"
            )
        return StatusResponse(
            status="ready",
            message="Le téléchargeur est prêt"
        )
    except Exception as e:
        logger.error("Erreur lors de la vérification du statut: %s", e)
        return StatusResponse(
            status="error",
            message=f"Erreur lors de la vérification du statut: {str(e)}"
        )


@app.post("/api/submit-otp", response_model=OTPResponse)
async def submit_otp(request: OTPRequest) -> OTPResponse:
    """
    Soumet un code OTP pour l'authentification à deux facteurs (Amazon).
    """
    downloader = _get_downloader("amazon")
    if not downloader:
        raise HTTPException(
            status_code=503,
            detail="Le téléchargeur n'est pas initialisé"
        )
    try:
        logger.info("Soumission du code OTP...")
        success = await downloader.submit_otp(request.otp_code)
        
        if success:
            # Vérifier si la connexion est maintenant réussie
            still_requires = downloader.is_2fa_required()
            return OTPResponse(
                success=True,
                message="Code OTP accepté" if not still_requires else "Code OTP accepté, mais 2FA toujours requis",
                requires_otp=still_requires
            )
        else:
            return OTPResponse(
                success=False,
                message="Code OTP incorrect ou expiré",
                requires_otp=True
            )
    
    except Exception as e:
        logger.error(f"Erreur lors de la soumission du code OTP: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la soumission du code OTP: {str(e)}"
        )


@app.get("/api/check-2fa", response_model=OTPResponse)
async def check_2fa() -> OTPResponse:
    """Vérifie si un code 2FA est requis (Amazon)."""
    downloader = _get_downloader("amazon")
    if not downloader:
        raise HTTPException(
            status_code=503,
            detail="Le téléchargeur n'est pas initialisé"
        )
    requires_otp = downloader.is_2fa_required()
    
    return OTPResponse(
        success=not requires_otp,
        message="Code 2FA requis" if requires_otp else "Aucun code 2FA requis",
        requires_otp=requires_otp
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

