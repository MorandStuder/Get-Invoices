"""
Provider Decathlon (Espace client — decathlon.fr).
Téléchargement des factures depuis Mon compte > Mes commandes.
Connexion : https://www.decathlon.fr/login puis navigation vers les commandes.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from backend.providers.base import OrderInfo
from backend.services.invoice_registry import InvoiceRegistry

logger = logging.getLogger(__name__)

PROVIDER_DECATHLON = "decathlon"

DECATHLON_BASE_URL = "https://www.decathlon.fr"
DECATHLON_LOGIN_URL = "https://www.decathlon.fr/login"
DECATHLON_ORDERS_URL = "https://www.decathlon.fr/account/myPurchase"

_MOIS_FR = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


class DecathlonProvider:
    """Provider pour télécharger les factures Decathlon."""

    PROVIDER_ID = PROVIDER_DECATHLON

    def __init__(
        self,
        login: str,
        password: str,
        download_path: Union[str, Path],
        headless: bool = False,
        timeout: int = 30,
        browser: str = "chrome",
        firefox_profile_path: Optional[str] = None,
        chrome_user_data_dir: Optional[str] = None,
        keep_browser_open: bool = False,
        manual_mode: bool = False,
    ) -> None:
        self.email = login
        self.password = password
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout = timeout
        self.browser = (browser or "chrome").strip().lower()
        self.firefox_profile_path = firefox_profile_path
        self.chrome_user_data_dir = chrome_user_data_dir
        self.keep_browser_open = keep_browser_open
        self.manual_mode = manual_mode
        self.driver: Optional[Union[webdriver.Chrome, webdriver.Firefox]] = None
        self.registry = InvoiceRegistry(self.download_path)
        self._profile_info: dict = {}  # Cache nom/adresse pour le formulaire magasin

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    def _setup_driver(
        self, use_profile: bool = True
    ) -> Union[webdriver.Chrome, webdriver.Firefox]:
        if self.browser == "firefox":
            return self._setup_firefox()
        return self._setup_chrome(use_profile=use_profile)

    def _setup_chrome(self, use_profile: bool = True) -> webdriver.Chrome:
        opts = ChromeOptions()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        prefs = {
            "download.default_directory": str(self.download_path.absolute()),
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
        }
        opts.add_experimental_option("prefs", prefs)
        profile_path = None
        if use_profile and self.chrome_user_data_dir:
            raw_path = Path(self.chrome_user_data_dir).resolve()
            parent = raw_path.parent
            profile_name = raw_path.name
            known_profile_names = {
                "default",
                "profile 1",
                "profile 2",
                "profile 3",
                "profile 4",
                "profile 5",
            }
            if (
                profile_name.lower() in known_profile_names
                and (parent / "Local State").exists()
            ):
                opts.add_argument(f"--user-data-dir={parent}")
                opts.add_argument(f"--profile-directory={profile_name}")
                profile_path = str(raw_path)
            else:
                profile_path = str(raw_path)
                opts.add_argument(f"--user-data-dir={profile_path}")
        logger.info(
            "Decathlon: lancement Chrome (profil: %s)",
            profile_path or "non (temporaire)",
        )

        raw_driver_path = ChromeDriverManager().install()
        driver_path = Path(raw_driver_path)
        if (
            not driver_path.name.lower().endswith(".exe")
            or "third_party_notices" in driver_path.name.lower()
        ):
            candidate = driver_path.with_name("chromedriver.exe")
            if candidate.exists():
                driver_path = candidate
        service = ChromeService(str(driver_path))
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(60)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
        driver.execute_cdp_cmd(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(self.download_path.absolute()),
            },
        )
        return driver

    def _setup_firefox(self) -> webdriver.Firefox:
        opts = FirefoxOptions()
        if self.headless:
            opts.add_argument("--headless")
        if self.firefox_profile_path and Path(self.firefox_profile_path).exists():
            opts.profile = FirefoxProfile(self.firefox_profile_path)
        else:
            profile = FirefoxProfile()
            profile.set_preference("browser.download.folderList", 2)
            profile.set_preference(
                "browser.download.dir", str(self.download_path.absolute())
            )
            profile.set_preference(
                "browser.helperApps.neverAsk.saveToDisk", "application/pdf"
            )
            opts.profile = profile
        driver_path = GeckoDriverManager().install()
        driver = webdriver.Firefox(service=FirefoxService(driver_path), options=opts)
        driver.set_page_load_timeout(60)
        return driver

    def _is_logged_in(self) -> bool:
        if not self.driver:
            return False
        try:
            url = (self.driver.current_url or "").lower()
        except Exception:
            return False
        if "decathlon.fr" not in url:
            return False
        login_patterns = ["/login", "/connect", "/signin", "/identification"]
        if any(p in url for p in login_patterns):
            return False
        try:
            body = self.driver.page_source.lower()
            pwd_fields = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            )
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                return False
            if any(
                x in body
                for x in [
                    "déconnexion",
                    "se déconnecter",
                    "mon compte",
                    "mes commandes",
                    "logout",
                ]
            ):
                return True
            if "decathlon.fr" in url and not any(p in url for p in login_patterns):
                if "mon-compte" in url or "commandes" in url:
                    return True
        except Exception:
            pass
        return False

    def _parse_invoice_date(self, text: str) -> Optional[date_type]:
        if not text:
            return None
        text_lower = text.lower().strip()
        # Format numérique : 23/02/2026 ou 23-02-2026
        match = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", text_lower)
        if match:
            try:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                    return date_type(y, m, d)
            except (ValueError, TypeError):
                pass
        # Format français : "23 février 2026"
        for mois_name, mois_num in _MOIS_FR.items():
            match = re.search(
                rf"(\d{{1,2}})\s+{re.escape(mois_name)}\s+(\d{{4}})", text_lower
            )
            if match:
                try:
                    d, y = int(match.group(1)), int(match.group(2))
                    if 2000 <= y <= 2100 and 1 <= d <= 31:
                        return date_type(y, mois_num, d)
                except (ValueError, TypeError):
                    pass
        return None

    async def login(self, otp_code: Optional[str] = None) -> bool:
        try:
            if not self.driver:
                logger.info("Decathlon: ouverture du navigateur...")
                try:
                    self.driver = self._setup_driver(use_profile=True)
                except Exception as e:
                    err_msg = str(e).lower()
                    if (
                        "already in use" in err_msg
                        or "user data directory" in err_msg
                        or "profile" in err_msg
                    ):
                        logger.warning(
                            "Decathlon: profil Chrome verrouillé (%s). Relance sans profil.",
                            e,
                        )
                        self.driver = self._setup_driver(use_profile=False)
                    else:
                        raise
                logger.info("Decathlon: navigateur ouvert.")

            if self.manual_mode:
                return await self._manual_login()
            return await self._auto_login()

        except Exception as e:
            logger.error("Decathlon login: %s", e, exc_info=True)
            return False

    async def _auto_login(self) -> bool:
        """Connexion automatique avec email/password."""
        if not self.driver:
            return False
        logger.info("Decathlon: connexion automatique sur %s", DECATHLON_LOGIN_URL)
        try:
            self.driver.get(DECATHLON_LOGIN_URL)
        except Exception as e:
            logger.warning("Decathlon: chargement login interrompu (%s)", e)

        # Accepter les cookies si présents
        time.sleep(2)
        self._accept_cookies()

        # Saisir email
        try:
            wait = WebDriverWait(self.driver, 15)
            email_field = wait.until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "input[type='email'], input[name='email'], input[id*='email']",
                    )
                )
            )
            email_field.clear()
            email_field.send_keys(self.email)
            logger.info("Decathlon: email saisi")
        except Exception as e:
            logger.warning("Decathlon: champ email introuvable (%s)", e)
            return await self._manual_login()

        # Cliquer sur "Continuer" ou "Suivant" si nécessaire
        try:
            for btn_text in ["continuer", "suivant", "next", "continue"]:
                btns = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    if btn_text in (btn.text or "").lower() and btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        break
        except Exception:
            pass

        # Saisir mot de passe
        try:
            wait = WebDriverWait(self.driver, 10)
            pwd_field = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input[type='password']")
                )
            )
            pwd_field.clear()
            pwd_field.send_keys(self.password)
            logger.info("Decathlon: mot de passe saisi")
        except Exception as e:
            logger.warning("Decathlon: champ mot de passe introuvable (%s)", e)
            return await self._manual_login()

        # Cliquer sur "Se connecter"
        try:
            for btn_text in ["se connecter", "connexion", "login", "signin", "valider"]:
                btns = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    if btn_text in (btn.text or "").lower() and btn.is_displayed():
                        btn.click()
                        logger.info("Decathlon: clic bouton connexion")
                        break
        except Exception as e:
            logger.warning("Decathlon: bouton connexion introuvable (%s)", e)

        # Attendre la connexion (max 30s)
        for _ in range(6):
            time.sleep(5)
            if self._is_logged_in():
                logger.info(
                    "Decathlon: connexion détectée (%s)", self.driver.current_url[:80]
                )
                return True
            logger.info("Decathlon: attente connexion...")

        # Vérifier si 2FA demandé
        try:
            body = self.driver.page_source.lower()
            if "code" in body and ("sms" in body or "vérification" in body):
                logger.warning("Decathlon: 2FA détecté, basculement en mode manuel")
                return await self._manual_login()
        except Exception:
            pass

        logger.warning(
            "Decathlon: connexion automatique échouée, basculement en mode manuel"
        )
        return await self._manual_login()

    async def _manual_login(self) -> bool:
        """Connexion manuelle : l'utilisateur se connecte dans le navigateur."""
        if not self.driver:
            return False
        try:
            self.driver.get(DECATHLON_LOGIN_URL)
        except Exception as e:
            logger.warning("Decathlon: navigation login (%s)", e)

        logger.info(
            "Decathlon: en attente de connexion manuelle sur %s", DECATHLON_LOGIN_URL
        )
        logger.info("Decathlon: connectez-vous dans le navigateur (5 minutes max).")

        max_wait = 300
        interval = 5
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(interval)
            elapsed += interval
            if self._is_logged_in():
                logger.info(
                    "Decathlon: connexion détectée (URL: %s)",
                    self.driver.current_url[:80],
                )
                return True
            logger.info("Decathlon: attente connexion... (%ds/%ds)", elapsed, max_wait)

        logger.warning(
            "Decathlon: timeout — connexion non détectée après %ds", max_wait
        )
        return False

    def _accept_cookies(self) -> None:
        """Accepte les cookies si un bandeau est présent."""
        if not self.driver:
            return
        cookie_selectors = [
            "button[id*='accept']",
            "button[class*='accept']",
            "button[data-testid*='accept']",
            "#didomi-notice-agree-button",
            ".didomi-components-button",
            "button[aria-label*='Accepter']",
        ]
        for sel in cookie_selectors:
            try:
                btns = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed():
                        btn.click()
                        logger.info("Decathlon: cookies acceptés (%s)", sel)
                        time.sleep(1)
                        return
            except Exception:
                continue
        # Fallback : chercher par texte
        try:
            for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                txt = (btn.text or "").lower()
                if ("accepter" in txt or "accept" in txt) and btn.is_displayed():
                    btn.click()
                    logger.info("Decathlon: cookies acceptés (texte)")
                    time.sleep(1)
                    return
        except Exception:
            pass

    async def navigate_to_invoices(self) -> bool:
        if not self.driver or not self._is_logged_in():
            return False
        url = (self.driver.current_url or "").lower()
        if "mes-commandes" in url or "commandes" in url:
            logger.info(
                "Decathlon: déjà sur la page des commandes (%s)",
                self.driver.current_url[:80],
            )
            return True
        try:
            self.driver.get(DECATHLON_ORDERS_URL)
            time.sleep(3)
            if self._is_logged_in():
                logger.info(
                    "Decathlon: page commandes chargée (%s)",
                    self.driver.current_url[:80],
                )
                return True
        except Exception as e:
            logger.warning("Decathlon: navigate_to_invoices: %s", e)
        return False

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Liste les commandes depuis la page Mon historique d'achats.

        Cherche les liens "Voir les détails" qui pointent vers les pages de
        détail de commande (/account/orderTracking?transactionId=...).
        """
        if not self.driver:
            return []
        out: List[OrderInfo] = []
        try:
            links = self.driver.find_elements(By.TAG_NAME, "a")
            logger.info("Decathlon: %d liens <a> trouvés", len(links))
            for idx, a in enumerate(links):
                try:
                    href = (a.get_attribute("href") or "").strip()
                    text = (a.text or "").strip()
                    text_lower = text.lower()

                    is_detail_link = (
                        "voir les détails" in text_lower
                        or "voir les details" in text_lower
                        or "ordertracking" in href.lower()
                    )
                    if not is_detail_link:
                        continue

                    m = re.search(r"transactionId=([^&]+)", href)
                    if not m:
                        m = re.search(r"orderId=([^&]+)", href)
                    order_id = m.group(1) if m else f"order_{idx}"

                    # Extraire le texte de la carte parente (date, montant, statut)
                    inv_date = None
                    try:
                        card_text = self.driver.execute_script(
                            "var el = arguments[0];"
                            "var p = el.closest('article, section, li,"
                            " [class*=\"card\"], [class*=\"order\"]');"
                            "return p ? p.innerText : '';",
                            a,
                        )
                        if card_text:
                            card_lower = card_text.lower()
                            # Ignorer les commandes annulées
                            if "annulée" in card_lower or "annulé" in card_lower:
                                logger.info(
                                    "Decathlon: commande annulée ignorée (%s)", href[:60]
                                )
                                continue
                            # Ignorer les commandes à 0,00 € (retours, erreurs)
                            if re.search(r"\b0[,.]00\s*€", card_text):
                                logger.info(
                                    "Decathlon: commande 0,00 € ignorée (%s)", href[:60]
                                )
                                continue
                            inv_date = self._parse_invoice_date(card_text)
                    except Exception:
                        pass

                    logger.info(
                        "Decathlon: commande trouvée: %s | date=%s -> %s",
                        order_id[:40],
                        inv_date,
                        href[:80],
                    )
                    out.append(
                        OrderInfo(
                            order_id=order_id,
                            invoice_url=href,
                            invoice_date=inv_date,
                        )
                    )
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Decathlon list_orders_or_invoices: %s", e)

        logger.info("Decathlon: %d commande(s) trouvée(s)", len(out))
        return out

    def _fetch_profile_info(self) -> None:
        """Récupère nom/adresse depuis le profil Decathlon (appelé une fois).

        Navigue sur la page des adresses pour extraire les champs pré-remplis,
        puis revient sur la page courante. Stocke le résultat dans _profile_info.
        """
        if not self.driver or self._profile_info:
            return
        info: dict = {}
        current_url = self.driver.current_url

        # Nom depuis la page courante (sidebar visible sur toutes les pages auth)
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            for line in body_text.split("\n"):
                line = line.strip()
                m = re.match(
                    r"^([A-ZÀ-Ÿ][a-zà-ÿ]+(?:-[A-ZÀ-Ÿ][a-zà-ÿ]+)*)"
                    r"\s+([A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ\-]+)$",
                    line,
                )
                if m and len(line) < 50:
                    info["firstName"] = m.group(1)
                    info["lastName"] = m.group(2)
                    logger.info(
                        "Decathlon: nom extrait: %s %s",
                        info["firstName"],
                        info["lastName"],
                    )
                    break
        except Exception as e:
            logger.warning("Decathlon: extraction nom: %s", e)

        # Adresse depuis la page des adresses
        try:
            self.driver.get("https://www.decathlon.fr/account/addresses")
            time.sleep(3)
            selectors = {
                "address": "input[name*='address' i], input[id*='address' i],"
                " input[placeholder*='rue' i], input[placeholder*='adresse' i]",
                "postalCode": "input[name*='postal' i], input[name*='zip' i],"
                " input[id*='postal' i]",
                "city": "input[name*='city' i], input[name*='ville' i],"
                " input[id*='city' i]",
                "country": "input[name*='country' i], input[id*='country' i],"
                " select[name*='country' i]",
            }
            for key, sel in selectors.items():
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    val = (el.get_attribute("value") or el.text or "").strip()
                    if val and len(val) > 1:
                        info[key] = val
                        break
        except Exception as e:
            logger.warning("Decathlon: extraction adresse: %s", e)
        finally:
            try:
                self.driver.get(current_url)
                time.sleep(2)
            except Exception:
                pass

        if info:
            logger.info("Decathlon: profil récupéré: %s", list(info.keys()))
        self._profile_info = info

    def _handle_info_modal(self) -> bool:
        """Gère le modal 'Informations client' (achats en magasin).

        Si le profil est disponible, remplit le formulaire et le soumet.
        Sinon, annule le modal. Retourne True si un modal a été détecté.
        """
        if not self.driver:
            return False
        try:
            body = self.driver.page_source.lower()
            if "informations client" not in body and "nom de famille" not in body:
                return False

            logger.info("Decathlon: modal 'Informations client' détecté")

            if self._profile_info:
                form_map = [
                    (
                        ["lastname", "last_name", "nom"],
                        self._profile_info.get("lastName", ""),
                    ),
                    (
                        ["firstname", "first_name", "prenom", "prénom"],
                        self._profile_info.get("firstName", ""),
                    ),
                    (
                        ["address", "adresse"],
                        self._profile_info.get("address", ""),
                    ),
                    (
                        ["postal", "zip", "code"],
                        self._profile_info.get("postalCode", ""),
                    ),
                    (
                        ["city", "ville"],
                        self._profile_info.get("city", ""),
                    ),
                    (
                        ["country", "pays"],
                        self._profile_info.get("country", "France"),
                    ),
                ]
                filled = 0
                for keys, value in form_map:
                    if not value:
                        continue
                    for key in keys:
                        sel = (
                            f"input[name*='{key}' i], input[id*='{key}' i],"
                            f" input[placeholder*='{key}' i]"
                        )
                        for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                            try:
                                if el.is_displayed():
                                    el.clear()
                                    el.send_keys(value)
                                    filled += 1
                                    break
                            except Exception:
                                continue
                        if filled and self._profile_info.get(
                            keys[0].split("_")[0], ""
                        ):
                            break

                if filled >= 3:
                    for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                        txt = (btn.text or "").strip().lower()
                        if txt in ("valider", "confirmer", "ok") and btn.is_displayed():
                            btn.click()
                            logger.info(
                                "Decathlon: formulaire soumis (%d champ(s))", filled
                            )
                            time.sleep(3)
                            return True

            # Fallback : annuler
            for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                if (btn.text or "").strip().lower() == "annuler" and btn.is_displayed():
                    btn.click()
                    logger.warning("Decathlon: modal annulé (profil insuffisant)")
                    time.sleep(1)
                    return True
        except Exception:
            pass
        return False

    def _find_invoice_element(self) -> tuple:
        """Cherche le lien/bouton de téléchargement de facture sur la page courante.

        Priorité :
        1. Texte contenant "télécharger" ET "facture"
        2. Texte contenant seulement "télécharger" (facture implicite)
        3. Texte contenant "facture" avec href download/pdf

        Retourne (element, href_or_None).
        """
        if not self.driver:
            return None, None

        candidates = []
        for tag in ["a", "button"]:
            for el in self.driver.find_elements(By.TAG_NAME, tag):
                try:
                    if not el.is_displayed():
                        continue
                    text = (el.text or "").lower()
                    href = (el.get_attribute("href") or "").strip() if tag == "a" else ""
                    has_dl = "télécharger" in text or "telecharger" in text or "download" in text
                    has_inv = "facture" in text or "invoice" in text or ".pdf" in href.lower()
                    if has_dl and has_inv:
                        candidates.insert(0, (el, href if href not in ("#", "javascript:void(0)") else None))
                    elif has_dl and tag == "a" and href:
                        candidates.append((el, href))
                    elif has_inv and tag == "a" and ".pdf" in href.lower():
                        candidates.append((el, href))
                except Exception:
                    continue

        if candidates:
            el, href = candidates[0]
            logger.info("Decathlon: lien facture trouvé (href=%s)", (href or "clic")[:80])
            return el, href
        return None, None

    def _download_invoice_from_detail_page(
        self,
        detail_url: str,
        order_id: str,
        invoice_date: Optional[date_type] = None,
    ) -> Optional[str]:
        """Navigue vers la page de détail d'une commande et télécharge la facture.

        Cherche le lien de téléchargement de facture et tente :
        1. Téléchargement direct via la session HTTP (si href accessible)
        2. Clic + attente du téléchargement navigateur
        Si un modal "Informations client" s'ouvre, tente de le remplir et soumettre.
        """
        if not self.driver:
            return None
        try:
            self.driver.get(detail_url)
            time.sleep(2)

            existing_pdfs = set(self.download_path.glob("*.pdf"))

            invoice_el, invoice_href = self._find_invoice_element()

            if not invoice_el:
                logger.warning(
                    "Decathlon: lien facture introuvable sur %s",
                    detail_url[:80],
                )
                return None

            # Essai 1 : téléchargement HTTP direct si on a un href
            if invoice_href:
                filename = self._download_pdf_url(invoice_href, order_id, invoice_date)
                if filename:
                    return filename

            # Essai 2 : clic sur le lien et attente
            handles_before = set(self.driver.window_handles)
            invoice_el.click()
            time.sleep(2)

            # Détecter et gérer le modal "Informations client" (achat magasin)
            if self._handle_info_modal():
                # Si modal rempli + soumis, attendre le téléchargement
                # Si modal annulé, pas de fichier
                downloaded = self._wait_for_browser_download(existing_pdfs, max_wait=15)
                if downloaded:
                    return self._rename_browser_download(downloaded, order_id, invoice_date)
                logger.warning(
                    "Decathlon: commande %s — modal traité mais pas de PDF", order_id[:40]
                )
                return None

            time.sleep(1)

            new_handles = set(self.driver.window_handles) - handles_before
            pdf_url = None
            in_new_tab = False

            if new_handles:
                h = list(new_handles)[0]
                self.driver.switch_to.window(h)
                time.sleep(1)
                tab_url = self.driver.current_url
                if tab_url and "about:" not in tab_url.lower():
                    pdf_url = tab_url
                    logger.info("Decathlon: URL nouvel onglet: %s", tab_url[:80])
                in_new_tab = True
            else:
                url_after = self.driver.current_url
                if url_after != detail_url:
                    pdf_url = url_after
                    logger.info("Decathlon: navigation vers %s", url_after[:80])

            filename = None
            if pdf_url and ".pdf" in pdf_url.lower():
                filename = self._download_pdf_url(pdf_url, order_id, invoice_date)

            if not filename:
                downloaded = self._wait_for_browser_download(existing_pdfs, max_wait=30)
                if downloaded:
                    filename = self._rename_browser_download(
                        downloaded, order_id, invoice_date
                    )

            if in_new_tab:
                try:
                    self.driver.close()
                    self.driver.switch_to.window(list(self.driver.window_handles)[0])
                except Exception:
                    pass

            return filename

        except Exception as e:
            logger.warning("Decathlon _download_invoice_from_detail_page: %s", e)
            return None

    def _wait_for_browser_download(
        self, existing_pdfs: set, max_wait: int = 30
    ) -> Optional[Path]:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            time.sleep(2)
            in_progress = list(self.download_path.glob("*.crdownload"))
            new_pdfs = set(self.download_path.glob("*.pdf")) - existing_pdfs
            if new_pdfs and not in_progress:
                return sorted(new_pdfs, key=lambda f: f.stat().st_mtime)[-1]
        new_pdfs = set(self.download_path.glob("*.pdf")) - existing_pdfs
        if new_pdfs:
            return sorted(new_pdfs, key=lambda f: f.stat().st_mtime)[-1]
        return None

    def _rename_browser_download(
        self, path: Path, order_id: str, invoice_date: Optional[date_type] = None
    ) -> str:
        if invoice_date:
            new_name = f"decathlon_{invoice_date.isoformat()}.pdf"
        else:
            short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
            new_name = f"decathlon_{short_id}.pdf"
        new_name = re.sub(r"[^\w\-.]", "_", new_name)[:80]
        new_path = path.parent / new_name
        if path.name != new_name:
            try:
                path.rename(new_path)
            except Exception as e:
                logger.warning(
                    "Decathlon: impossible de renommer %s -> %s : %s",
                    path.name,
                    new_name,
                    e,
                )
                return path.name
        return new_name

    def _get_browser_session(self) -> Any:
        import requests

        session = requests.Session()
        for c in self.driver.get_cookies():  # type: ignore[union-attr]
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        session.headers["User-Agent"] = self.driver.execute_script(  # type: ignore[union-attr]
            "return navigator.userAgent;"
        )
        return session

    def _download_pdf_url(
        self, url: str, order_id: str, invoice_date: Optional[date_type] = None
    ) -> Optional[str]:
        try:
            session = self._get_browser_session()
            r = session.get(url, timeout=30, allow_redirects=True)
            if r.status_code != 200:
                return None
            ct = r.headers.get("content-type", "").lower()
            if "pdf" not in ct and not (
                len(r.content) >= 4 and r.content[:4] == b"%PDF"
            ):
                return None
            if invoice_date:
                name = f"decathlon_{invoice_date.isoformat()}.pdf"
            else:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"decathlon_{short_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("Decathlon _download_pdf_url: %s", e)
            return None

    async def download_invoice(
        self,
        order_or_id: Any,
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date_type] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        oid = order_id or (
            order_or_id.order_id
            if isinstance(order_or_id, OrderInfo)
            else str(order_or_id)
        )
        if not force_redownload and self.registry.is_downloaded(
            PROVIDER_DECATHLON, oid
        ):
            return None
        url = None
        if isinstance(order_or_id, OrderInfo) and order_or_id.invoice_url:
            url = order_or_id.invoice_url
        if not url and isinstance(order_or_id, str) and order_or_id.startswith("http"):
            url = order_or_id
        if not url:
            return None
        filename = self._download_pdf_url(url, oid, invoice_date)
        if filename:
            self.registry.add(
                PROVIDER_DECATHLON,
                oid,
                filename,
                invoice_date=invoice_date.isoformat() if invoice_date else None,
            )
        return filename

    def _get_pagination_urls(self) -> List[str]:
        """Retourne les URLs des pages suivantes depuis la pagination."""
        if not self.driver:
            return []
        seen: set = set()
        urls: List[str] = []
        try:
            for a in self.driver.find_elements(By.TAG_NAME, "a"):
                try:
                    href = (a.get_attribute("href") or "").strip()
                    text = (a.text or "").strip()
                    if not href or href in seen:
                        continue
                    # Lien de pagination : texte = chiffre, href contient myPurchase
                    if (
                        text.isdigit()
                        and int(text) > 1
                        and "mypurchase" in href.lower()
                    ):
                        seen.add(href)
                        urls.append(href)
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Decathlon _get_pagination_urls: %s", e)
        urls.sort(key=lambda u: int(re.search(r"page=(\d+)", u).group(1))
                  if re.search(r"page=(\d+)", u) else 0)
        logger.info("Decathlon: %d page(s) de pagination trouvée(s)", len(urls))
        return urls

    async def _notify_progress(
        self,
        on_progress: Optional[Callable[[int, int, str], Any]],
        current: int,
        total: int,
        msg: str,
    ) -> None:
        if on_progress:
            try:
                await on_progress(current, total, msg)
            except Exception:
                pass

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
        on_progress: Optional[Callable[[int, int, str], Any]] = None,
    ) -> Dict[str, Union[List[str], int]]:
        ok = await self.login(otp_code=otp_code)
        if not ok:
            raise Exception("Échec de la connexion à l'espace Decathlon")
        if not await self.navigate_to_invoices():
            logger.warning(
                "Decathlon: navigate_to_invoices a échoué, tentative sur la page actuelle."
            )

        # Accepter les cookies si besoin (peut apparaître après connexion)
        self._accept_cookies()
        time.sleep(2)

        # Récupérer le profil une fois (nom/adresse pour le formulaire magasin)
        self._fetch_profile_info()

        # Collecter les commandes sur toutes les pages de pagination
        orders: List[OrderInfo] = []
        seen_ids: set = set()

        def _add_orders(new_orders: List[OrderInfo]) -> None:
            for o in new_orders:
                if o.order_id not in seen_ids:
                    seen_ids.add(o.order_id)
                    orders.append(o)

        # Page 1
        page1_orders = self.list_orders_or_invoices()
        if not page1_orders and self.driver:
            logger.info("Decathlon: aucune commande sur la page actuelle, navigation vers %s", DECATHLON_ORDERS_URL)
            try:
                self.driver.get(DECATHLON_ORDERS_URL)
                time.sleep(3)
                page1_orders = self.list_orders_or_invoices()
            except Exception as e:
                logger.warning("Decathlon: navigation commandes: %s", e)
        _add_orders(page1_orders)

        # Pages suivantes (pagination)
        if self.driver and orders:
            pagination_urls = self._get_pagination_urls()
            for page_url in pagination_urls:
                if len(orders) >= max_invoices:
                    break
                try:
                    logger.info("Decathlon: pagination → %s", page_url[:80])
                    self.driver.get(page_url)
                    time.sleep(2)
                    _add_orders(self.list_orders_or_invoices())
                except Exception as e:
                    logger.warning("Decathlon: pagination: %s", e)
                    break

        logger.info("Decathlon: %d commande(s) au total (toutes pages)", len(orders))

        if not orders:
            logger.warning("Decathlon: aucune commande trouvée")
            return {"count": 0, "files": []}

        # Filtre par date
        if any([year, month, months, date_start, date_end]):
            from datetime import datetime

            filtered: List[OrderInfo] = []
            for o in orders:
                if date_start and date_end:
                    try:
                        s = datetime.strptime(date_start, "%Y-%m-%d").date()
                        e_date = datetime.strptime(date_end, "%Y-%m-%d").date()
                        if o.invoice_date and s <= o.invoice_date <= e_date:
                            filtered.append(o)
                    except Exception:
                        filtered.append(o)
                elif year and month:
                    if o.invoice_date is None or (
                        o.invoice_date.year == year
                        and o.invoice_date.month == month
                    ):
                        filtered.append(o)
                elif year:
                    if o.invoice_date is None or o.invoice_date.year == year:
                        filtered.append(o)
                elif months:
                    if o.invoice_date is None or o.invoice_date.month in months:
                        filtered.append(o)
                else:
                    filtered.append(o)
            orders = filtered

        orders = orders[:max_invoices]
        total = len(orders)
        files: List[str] = []
        count = 0

        for i, order in enumerate(orders):
            if count >= max_invoices:
                break
            await self._notify_progress(
                on_progress, count, total, f"Traitement commande {i + 1}/{total}…"
            )

            if not force_redownload and self.registry.is_downloaded(
                PROVIDER_DECATHLON, order.order_id
            ):
                logger.info("Decathlon: %s déjà téléchargé, ignoré", order.order_id)
                continue

            if not order.invoice_url:
                logger.warning("Decathlon: pas d'URL pour %s", order.order_id)
                continue

            # Naviguer vers la page de détail et télécharger la facture
            filename = self._download_invoice_from_detail_page(
                order.invoice_url, order.order_id, order.invoice_date
            )

            if filename:
                self.registry.add(
                    PROVIDER_DECATHLON,
                    order.order_id,
                    filename,
                    invoice_date=(
                        order.invoice_date.isoformat() if order.invoice_date else None
                    ),
                )
                files.append(filename)
                count += 1
                await self._notify_progress(
                    on_progress,
                    count,
                    total,
                    f"{count}/{total} facture(s) téléchargée(s)",
                )
                logger.info("Decathlon: facture téléchargée: %s", filename)
            else:
                logger.warning(
                    "Decathlon: échec téléchargement facture %s", order.order_id
                )

            time.sleep(1)

        logger.info("Decathlon: %d facture(s) téléchargée(s) au total", count)
        return {"count": count, "files": files}

    async def close(self) -> None:
        if self.driver and not self.keep_browser_open:
            try:
                self.driver.quit()
                logger.info("Decathlon: navigateur fermé")
            except Exception:
                pass
            self.driver = None

    def is_2fa_required(self) -> bool:
        return False

    async def submit_otp(self, otp_code: str) -> bool:
        return False
