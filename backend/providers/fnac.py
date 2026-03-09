"""
Provider FNAC (Espace client — fnac.com).
Téléchargement des factures depuis Mon compte > Mes commandes.
Connexion : https://www.fnac.com/ puis « Me connecter ».
"""
from __future__ import annotations

import re
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile

from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from backend.providers.base import OrderInfo
from backend.services.invoice_registry import InvoiceRegistry

import logging

logger = logging.getLogger(__name__)

PROVIDER_FNAC = "fnac"

_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

FNAC_BASE_URL = "https://www.fnac.com"
FNAC_DIRECT_LOGIN_URL = "https://secure.fnac.com/account/order"
# Pages commandes à essayer après connexion (ordre de priorité)
FNAC_ORDERS_PATHS = [
    "/account/order",
    "/account/orders",
    "/compte/mes-commandes",
    "/mes-commandes",
    "/Mon-compte/mes-commandes",
]


class FnacProvider:
    """
    Fournisseur FNAC (Espace client fnac.com).
    Implémente InvoiceProviderProtocol.
    """

    PROVIDER_ID = PROVIDER_FNAC

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
    ) -> None:
        self._login = login
        self._password = password
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout = timeout
        self.browser = browser.lower()
        self.firefox_profile_path = firefox_profile_path
        self.chrome_user_data_dir = chrome_user_data_dir
        self.keep_browser_open = keep_browser_open
        self.driver: Optional[Union[webdriver.Chrome, webdriver.Firefox]] = None
        self.registry = InvoiceRegistry(self.download_path)

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    def _setup_driver(self, use_profile: bool = True) -> Union[webdriver.Chrome, webdriver.Firefox]:
        if self.browser == "firefox":
            return self._setup_firefox()
        return self._setup_chrome(use_profile=use_profile)

    def _setup_chrome(self, use_profile: bool = True) -> webdriver.Chrome:
        opts = ChromeOptions()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        # Anti-détection bot
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        prefs = {
            "download.default_directory": str(self.download_path.absolute()),
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
        }
        opts.add_experimental_option("prefs", prefs)
        profile_path = None
        if use_profile and self.chrome_user_data_dir:
            raw_path = Path(self.chrome_user_data_dir).resolve()
            # Détecter si le chemin pointe vers un sous-dossier de profil (ex: .../User Data/Profile 1)
            # Dans ce cas, --user-data-dir = parent, --profile-directory = nom du dossier
            parent = raw_path.parent
            profile_name = raw_path.name
            known_profile_names = {"default", "profile 1", "profile 2", "profile 3", "profile 4", "profile 5"}
            if profile_name.lower() in known_profile_names and (parent / "Local State").exists():
                opts.add_argument(f"--user-data-dir={parent}")
                opts.add_argument(f"--profile-directory={profile_name}")
                profile_path = str(raw_path)
            else:
                # Dossier dédié (ex: GetInvoicesChrome) — Chrome crée le profil "Default" dedans
                profile_path = str(raw_path)
                opts.add_argument(f"--user-data-dir={profile_path}")
        logger.info("FNAC: lancement Chrome (profil: %s)", profile_path or "non (temporaire)")

        raw_driver_path = ChromeDriverManager().install()
        driver_path = Path(raw_driver_path)
        # Correction bug WebDriverManager: parfois renvoie THIRD_PARTY_NOTICES.chromedriver au lieu de chromedriver.exe
        if not driver_path.name.lower().endswith(".exe") or "third_party_notices" in driver_path.name.lower():
            candidate = driver_path.with_name("chromedriver.exe")
            if candidate.exists():
                logger.info("FNAC: correction chemin ChromeDriver (%s -> %s)", driver_path, candidate)
                driver_path = candidate
        service = ChromeService(str(driver_path))
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(60)
        # Masquer navigator.webdriver (principal signal de détection bot)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
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
            profile.set_preference("browser.download.dir", str(self.download_path.absolute()))
            profile.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf")
            opts.profile = profile
        driver_path = GeckoDriverManager().install()
        driver = webdriver.Firefox(service=FirefoxService(driver_path), options=opts)
        driver.set_page_load_timeout(60)
        return driver

    def _dismiss_consent_banner(self) -> None:
        """Ferme le bandeau cookies / consentement FNAC s'il est affiché."""
        if not self.driver:
            return
        try:
            # Sélecteurs ciblés plutôt qu'itérer sur tous les éléments de la page
            for sel in [
                "button#didomi-notice-agree-button",
                "button[id*='accept']",
                "button[class*='accept']",
                "button[data-testid*='accept']",
                "#onetrust-accept-btn-handler",
                ".cookie-consent button",
                "[aria-label*='accepter']",
                "[aria-label*='Accepter']",
            ]:
                try:
                    els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in els:
                        if el.is_displayed():
                            el.click()
                            time.sleep(1)
                            return
                except Exception:
                    continue
        except Exception:
            pass

    def _is_logged_in(self) -> bool:
        if not self.driver:
            return False
        try:
            url = (self.driver.current_url or "").lower()
        except Exception:
            return False
        if "fnac.com" not in url:
            return False
        # Pages de l'espace client authentifié (accès uniquement si session active)
        authenticated_paths = ["/account/order", "/account/", "/mon-compte", "/mes-commandes"]
        if any(p in url for p in authenticated_paths) and "connexion" not in url:
            logger.debug("FNAC _is_logged_in: URL espace client -> connecte (%s)", url[:80])
            return True
        try:
            # Formulaire de connexion visible = pas connecté (vérifier en premier)
            pwd_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                return False
            body = self.driver.page_source.lower()
            # Indicateur fort : lien/bouton de déconnexion (absent de la page de login)
            if "déconnexion" in body or "se déconnecter" in body or "logout" in body:
                return True
            # Page de connexion explicite
            if "connexion-identification" in url or "connexion" in url:
                return False
            # "me connecter" visible sans "déconnexion" = pas connecté
            if "me connecter" in body:
                return False
            return False
        except Exception:
            pass
        return False

    async def login(self, otp_code: Optional[str] = None) -> bool:
        try:
            if not self.driver:
                logger.info("FNAC: ouverture du navigateur...")
                try:
                    self.driver = self._setup_driver(use_profile=True)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "already in use" in err_msg or "user data directory" in err_msg or "profile" in err_msg:
                        logger.warning("FNAC: profil Chrome verrouillé (%s). Relance sans profil.", e)
                        self.driver = self._setup_driver(use_profile=False)
                    else:
                        raise
                logger.info("FNAC: navigateur ouvert.")

            # Naviguer vers la page des commandes
            try:
                self.driver.get(FNAC_DIRECT_LOGIN_URL)
            except Exception as e:
                logger.warning("FNAC: chargement %s interrompu (%s)", FNAC_DIRECT_LOGIN_URL, e)

            logger.info("FNAC: en attente de connexion manuelle sur %s", FNAC_DIRECT_LOGIN_URL)
            logger.info("FNAC: connectez-vous dans le navigateur (5 minutes max).")

            max_wait = 300  # 5 minutes
            interval = 5
            elapsed = 0
            while elapsed < max_wait:
                time.sleep(interval)
                elapsed += interval
                if self._is_logged_in():
                    logger.info("FNAC: connexion détectée (URL: %s)", self.driver.current_url[:80])
                    return True
                logger.info("FNAC: attente connexion... (%ds/%ds)", elapsed, max_wait)

            logger.warning("FNAC: timeout — connexion non détectée après %ds", max_wait)
            return False
        except Exception as e:
            logger.error("FNAC login: %s", e, exc_info=True)
            return False

    def _is_orders_page(self) -> bool:
        """Détecte si la page actuelle est la page liste des commandes (pas une page détail)."""
        if not self.driver:
            return False
        url = (self.driver.current_url or "").lower()
        # Exclure les pages détail : /account/order/ID ou /account/orders/ID
        if re.search(r"/account/orders?/[^?#\s]+", url):
            return False
        # Matcher uniquement la page liste (fin de chemin ou paramètre de requête)
        if re.search(r"/account/orders?($|\?|#)", url):
            return True
        # Autres URL de liste commandes (pas /commandes/ID)
        if "commande" in url and not re.search(r"/commandes?/[^?#\s]+", url):
            return True
        try:
            body = self.driver.page_source.lower()
            # Marqueurs présents sur la page liste (plusieurs commandes)
            markers = ["n° de commande", "numéro de commande", "référence commande", "suivi de commande"]
            return sum(1 for m in markers if m in body) >= 2
        except Exception:
            return False

    async def navigate_to_invoices(self) -> bool:
        if not self.driver or not self._is_logged_in():
            return False
        # Si on est déjà sur la page des commandes, ne pas naviguer ailleurs
        if self._is_orders_page():
            logger.info("FNAC: déjà sur la page commandes (%s)", self.driver.current_url[:80])
            return True
        # Essai direct sur les URLs connues
        for path in FNAC_ORDERS_PATHS:
            url = FNAC_BASE_URL.rstrip("/") + path
            self.driver.get(url)
            time.sleep(3)
            if "fnac.com" not in self.driver.current_url:
                continue
            if self._is_orders_page():
                logger.info("FNAC: page commandes trouvée (%s)", self.driver.current_url[:80])
                return True
        # Fallback : chercher un lien "Mes commandes" sur la page actuelle
        try:
            for a in self.driver.find_elements(By.TAG_NAME, "a"):
                text = (a.text or "").strip().lower()
                href = (a.get_attribute("href") or "").lower()
                if ("mes commandes" in text or ("commande" in href and "fnac.com" in href)):
                    a.click()
                    time.sleep(3)
                    if self._is_orders_page():
                        logger.info("FNAC: page commandes atteinte via lien (%s)", self.driver.current_url[:80])
                        return True
                    break
        except Exception:
            pass
        logger.warning("FNAC: impossible d'atteindre la page des commandes. URL: %s", (self.driver.current_url or "")[:80])
        return False

    def _parse_invoice_date(self, text: str) -> Optional[date_type]:
        if not text:
            return None
        text_lower = text.lower()
        # Format DD/MM/YYYY (ex: "08/02/2026", "du 08/02/2026")
        match = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b", text)
        if match:
            try:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                    return date_type(y, m, d)
            except (ValueError, TypeError):
                pass
        # Format "mois année" en français (ex: "janvier 2024")
        for mois_name, mois_num in _MOIS_FR.items():
            match = re.search(rf"{re.escape(mois_name)}\s+(\d{{4}})", text_lower)
            if match:
                try:
                    y = int(match.group(1))
                    if 2000 <= y <= 2100:
                        return date_type(y, mois_num, 1)
                except (ValueError, TypeError):
                    pass
        # Format YYYY-MM ou YYYY/MM
        match = re.search(r"(\d{4})[-/](\d{1,2})", text)
        if match:
            try:
                y, m = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        return None

    def _find_invoice_link_on_page(self) -> Optional[str]:
        """Cherche un lien de téléchargement de facture sur la page détail d'une commande."""
        if not self.driver:
            return None
        from urllib.parse import urljoin
        base_url = self.driver.current_url
        time.sleep(2)  # attendre rendu JS

        # Log diagnostic : tous les liens de la page (debug)
        all_links = self.driver.find_elements(By.TAG_NAME, "a")
        logger.debug(
            "FNAC _find_invoice_link: %d lien(s) sur %s",
            len(all_links), base_url[:80],
        )
        for a in all_links[:40]:
            try:
                href = (a.get_attribute("href") or "")[:100]
                txt = (a.text or "").strip()[:60]
                if href:
                    logger.debug("  lien: %s | texte: %s", href, txt)
            except Exception:
                pass

        # 1. Chercher liens/boutons explicitement liés à la facture
        # Note: utiliser normalize-space(.) pour matcher le texte de tout le sous-arbre (React/SPA)
        for el in self.driver.find_elements(By.XPATH,
            "//*[(self::a or self::button) and ("
            "contains(translate(normalize-space(.),'FACTURÉ','facturé'),'facture') or "
            "contains(translate(normalize-space(.),'TÉLÉCHARGER','télécharger'),'télécharger') or "
            "contains(translate(@title,'FACTURE','facture'),'facture') or "
            "contains(translate(@aria-label,'FACTURÉ','facturé'),'facture') or "
            "contains(translate(@aria-label,'TÉLÉCHARGER','télécharger'),'télécharger'))]"):
            try:
                tag = el.tag_name.lower()
                if not el.is_displayed():
                    continue
                if tag == "a":
                    href = el.get_attribute("href") or ""
                    if href and href != "#":
                        logger.info("FNAC: lien facture trouvé (xpath): %s", href[:80])
                        return urljoin(base_url, href) if not href.startswith("http") else href
                elif tag == "button":
                    logger.info("FNAC: bouton facture trouvé ('%s'), clic...", (el.text or "")[:40])
                    el.click()
                    time.sleep(3)
                    # Après le clic, chercher un lien PDF apparu
                    for a in self.driver.find_elements(By.CSS_SELECTOR,
                            "a[href*='.pdf'], a[href*='facture'], a[href*='invoice'], a[href*='download']"):
                        href = a.get_attribute("href") or ""
                        if href:
                            logger.info("FNAC: lien PDF après clic bouton: %s", href[:80])
                            return href
            except Exception:
                continue

        # 2. Chercher liens PDF ou "télécharger" sans restriction de domaine
        for a in self.driver.find_elements(By.TAG_NAME, "a"):
            try:
                href = (a.get_attribute("href") or "").strip()
                if not href or href in ("#", "javascript:void(0)"):
                    continue
                href_lower = href.lower()
                text_lower = (a.text or "").lower()
                title_lower = (a.get_attribute("title") or "").lower()
                combined = href_lower + text_lower + title_lower
                if (
                    ".pdf" in href_lower
                    or "facture" in combined
                    or "invoice" in combined
                    or ("télécharger" in combined and "commande" in combined)
                    or ("download" in href_lower and any(
                        x in href_lower for x in ["order", "commande", "invoice", "facture"]
                    ))
                ):
                    logger.info("FNAC: lien facture trouvé (scan): %s | texte: %s", href[:80], text_lower[:40])
                    return href
            except Exception:
                continue

        logger.info("FNAC: aucun lien facture trouvé sur %s", base_url[:80])
        return None

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Liste les liens vers les commandes (pages détail) ou factures directes."""
        from urllib.parse import urljoin
        out: List[OrderInfo] = []
        if not self.driver:
            return out
        try:
            base_url = self.driver.current_url
            seen: set[str] = set()

            for a in self.driver.find_elements(By.TAG_NAME, "a"):
                try:
                    href = (a.get_attribute("href") or "").strip()
                    if not href or href == "#" or not a.is_displayed():
                        continue
                    href_lower = href.lower()
                    text = (a.text or "").strip().lower()
                    title = (a.get_attribute("title") or "").strip().lower()

                    # Exclure les liens de navigation globaux et les sous-pages de compte non-commandes
                    if any(x in href_lower for x in ["logout", "deconnexion", "déconnexion", "javascript:", "mailto:"]):
                        continue
                    if re.search(r"/account/order/(resale|return|wishlist|sav)", href_lower):
                        continue
                    if any(x in href_lower for x in [
                        "/account/dashboard", "/account/wishlist", "/account/consents",
                        "/account/synchro", "/account/personal-information", "/account/sav",
                        "/membership", "/membershiphistory",
                    ]):
                        continue

                    is_invoice_link = (
                        ".pdf" in href_lower
                        or "facture" in href_lower
                        or ("telecharger" in href_lower and "fnac" in href_lower)
                        or "facture" in text or "facture" in title
                    )
                    is_order_link = (
                        re.search(r"/commande[s]?/", href_lower)
                        or re.search(r"/order[s]?/", href_lower)
                        or re.search(r"/detail[s]?/", href_lower)
                        or ("commande" in href_lower and re.search(r"\d{5,}", href))
                        or "voir les détails" in text or "détail" in text
                    )

                    if not (is_invoice_link or is_order_link):
                        continue

                    full = urljoin(base_url, href) if not href.startswith("http") else href
                    if full in seen:
                        continue
                    seen.add(full)

                    # Extraire le contexte de la commande (bloc parent) pour trouver la date et l'ID
                    ctx_text = title or text
                    order_num = None
                    try:
                        # Remonter jusqu'à 5 niveaux pour trouver le bloc commande
                        for level in range(1, 6):
                            ancestor_xpath = "/".join([".."] * level)
                            try:
                                parent = a.find_element(By.XPATH, ancestor_xpath)
                                ptext = (parent.text or "")[:400]
                                if ptext and len(ptext) > len(ctx_text):
                                    ctx_text = ptext
                                    # Chercher le numéro de commande FNAC (alphanum, ex: 94S5GVLVJAUZW)
                                    m_num = re.search(r"[Nn]°?\s*([A-Z0-9]{8,})", ptext)
                                    if m_num:
                                        order_num = m_num.group(1)
                                if order_num and self._parse_invoice_date(ctx_text):
                                    break
                            except Exception:
                                break
                    except Exception:
                        pass
                    inv_date = self._parse_invoice_date(ctx_text)

                    # Extraire l'ID de commande : numéro FNAC alphanum ou ID numérique dans l'URL
                    if not order_num:
                        m_url = re.search(r"[/\-_]([A-Z0-9]{6,})", href)
                        order_num = m_url.group(1) if m_url else None
                    order_id = f"fnac_{order_num}" if order_num else f"fnac_ord_{len(out)}_{hash(full) % 100000}"

                    out.append(OrderInfo(order_id=order_id, invoice_url=full, invoice_date=inv_date, raw_element=a))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("FNAC list_orders: %s", e)
        logger.info("FNAC: %d lien(s) commande/facture trouvé(s) sur la page", len(out))
        return out

    def _get_next_page_url(self) -> Optional[str]:
        """Retourne l'URL de la page suivante de commandes, ou None si dernière page."""
        if not self.driver:
            return None
        from urllib.parse import urljoin
        base = self.driver.current_url
        try:
            # 1. Lien <a rel="next"> ou lien avec texte "suivant" / ">"
            for a in self.driver.find_elements(By.TAG_NAME, "a"):
                try:
                    rel = (a.get_attribute("rel") or "").lower()
                    text = (a.text or "").strip().lower()
                    href = (a.get_attribute("href") or "").strip()
                    aria = (a.get_attribute("aria-label") or "").lower()
                    if not href or href == "#":
                        continue
                    if (
                        rel == "next"
                        or "suivant" in text or "suivant" in aria
                        or text in (">", "›", "»", "next")
                        or "page suivante" in text or "page suivante" in aria
                    ):
                        full = urljoin(base, href) if not href.startswith("http") else href
                        logger.info("FNAC: page suivante trouvée via lien: %s", full[:80])
                        return full
                except Exception:
                    continue
            # 2. Pattern URL ?page=N — incrémenter le numéro de page
            import re as _re
            m = _re.search(r"[?&]page=(\d+)", base)
            if m:
                current_page = int(m.group(1))
                next_url = base.replace(f"page={current_page}", f"page={current_page + 1}")
                return next_url
        except Exception:
            pass
        return None

    def _collect_all_orders(self, max_pages: int = 20) -> List[OrderInfo]:
        """Collecte les commandes sur toutes les pages (avec pagination)."""
        all_orders: List[OrderInfo] = []
        seen_ids: set[str] = set()
        page_num = 1
        while page_num <= max_pages:
            page_orders = self.list_orders_or_invoices()
            new = [o for o in page_orders if o.order_id not in seen_ids]
            if not new:
                logger.info("FNAC: pagination — page %d : aucune nouvelle commande, arrêt", page_num)
                break
            for o in new:
                seen_ids.add(o.order_id)
            all_orders.extend(new)
            logger.info("FNAC: pagination — page %d : %d commande(s) ajoutée(s), total: %d", page_num, len(new), len(all_orders))
            next_url = self._get_next_page_url()
            if not next_url or next_url == self.driver.current_url:
                break
            try:
                self.driver.get(next_url)
                time.sleep(3)
            except Exception as e:
                logger.warning("FNAC: pagination — erreur chargement page %d: %s", page_num + 1, e)
                break
            page_num += 1
        logger.info("FNAC: %d commande(s) collectée(s) au total (%d page(s))", len(all_orders), page_num)
        return all_orders

    def _filter_orders_by_date(
        self,
        orders: List[OrderInfo],
        year: Optional[int] = None,
        month: Optional[int] = None,
        months: Optional[List[int]] = None,
        date_start_str: Optional[str] = None,
        date_end_str: Optional[str] = None,
    ) -> List[OrderInfo]:
        from datetime import datetime
        if not any([year, month, months, date_start_str, date_end_str]):
            return orders
        if date_start_str and date_end_str:
            try:
                start_d = datetime.strptime(date_start_str, "%Y-%m-%d").date()
                end_d = datetime.strptime(date_end_str, "%Y-%m-%d").date()
                return [o for o in orders if o.invoice_date and start_d <= o.invoice_date <= end_d]
            except ValueError:
                return orders
        out: List[OrderInfo] = []
        no_date_count = 0
        for o in orders:
            if not o.invoice_date:
                # Inclure les commandes sans date si seule l'année est filtrée (date non parsée)
                if year is not None and month is None and not months:
                    no_date_count += 1
                    out.append(o)
                continue
            if year is not None and o.invoice_date.year != year:
                continue
            if month is not None and o.invoice_date.month != month:
                continue
            if months and o.invoice_date.month not in months:
                continue
            out.append(o)
        if no_date_count:
            logger.warning(
                "FNAC: %d commande(s) sans date incluse(s) (date non parsée) — elles seront toutes téléchargées",
                no_date_count,
            )
        return out

    def _wait_for_browser_download(self, existing_pdfs: set, max_wait: int = 30) -> Optional[Path]:
        """Attend qu'un nouveau PDF apparaisse dans download_path (hors .crdownload). Retourne le Path ou None."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            time.sleep(2)
            # Vérifier qu'aucun .crdownload n'est encore en cours
            in_progress = list(self.download_path.glob("*.crdownload"))
            new_pdfs = set(self.download_path.glob("*.pdf")) - existing_pdfs
            if new_pdfs and not in_progress:
                return sorted(new_pdfs, key=lambda f: f.stat().st_mtime)[-1]
        # Dernière chance : nouveau PDF même si .crdownload encore là
        new_pdfs = set(self.download_path.glob("*.pdf")) - existing_pdfs
        if new_pdfs:
            return sorted(new_pdfs, key=lambda f: f.stat().st_mtime)[-1]
        return None

    def _rename_browser_download(self, path: Path, order_id: str, invoice_date: Optional[date_type] = None) -> str:
        """Renomme un PDF téléchargé par le navigateur en suivant la convention fnac_{date}_{id}.pdf."""
        short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
        if invoice_date:
            new_name = f"fnac_{invoice_date.isoformat()}_{short_id}.pdf"
        else:
            new_name = f"fnac_{short_id}.pdf"
        new_name = re.sub(r"[^\w\-.]", "_", new_name)[:80]
        new_path = path.parent / new_name
        if path.name != new_name:
            try:
                path.rename(new_path)
            except Exception as e:
                logger.warning("FNAC: impossible de renommer %s -> %s : %s", path.name, new_name, e)
                return path.name
        return new_name

    def _get_browser_session(self) -> Any:
        import requests
        session = requests.Session()
        for c in self.driver.get_cookies():
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        session.headers["User-Agent"] = self.driver.execute_script("return navigator.userAgent;")
        return session

    def _download_pdf(self, url: str, order_id: str, invoice_date: Optional[date_type] = None) -> Optional[str]:
        try:
            session = self._get_browser_session()
            r = session.get(url, timeout=30, allow_redirects=True)
            if r.status_code != 200:
                return None
            ct = r.headers.get("content-type", "").lower()
            if "pdf" not in ct and not (len(r.content) >= 4 and r.content[:4] == b"%PDF"):
                return None
            if invoice_date:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"fnac_{invoice_date.isoformat()}_{short_id}.pdf"
            else:
                name = f"fnac_{order_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("FNAC download %s: %s", url[:60], e)
            return None

    async def download_invoice(
        self,
        order_or_id: Any,
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date_type] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        oid = order_id or (order_or_id.order_id if isinstance(order_or_id, OrderInfo) else str(order_or_id))
        if not force_redownload and self.registry.is_downloaded(PROVIDER_FNAC, oid):
            return None
        url = None
        if isinstance(order_or_id, OrderInfo) and order_or_id.invoice_url:
            url = order_or_id.invoice_url
        if not url and isinstance(order_or_id, str) and order_or_id.startswith("http"):
            url = order_or_id
        if not url:
            return None
        filename = self._download_pdf(url, oid, invoice_date)
        if filename:
            self.registry.add(PROVIDER_FNAC, oid, filename, invoice_date=invoice_date.isoformat() if invoice_date else None)
        return filename

    async def _notify_progress(
        self,
        on_progress: Optional[Callable[[int, int, str], Any]],
        current: int,
        total: int,
        msg: str,
    ) -> None:
        if not on_progress:
            return
        try:
            cb = on_progress(current, total, msg)
            if hasattr(cb, "__await__"):
                await cb
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
            raise Exception("Échec de la connexion à l'espace FNAC")
        if not await self.navigate_to_invoices():
            raise Exception("Impossible d'accéder à Mes commandes FNAC")

        # Collecter les liens depuis toutes les pages de commandes (pagination)
        orders_page_url = self.driver.current_url  # type: ignore[union-attr]
        orders = self._collect_all_orders(max_pages=20)
        if not orders:
            logger.warning("FNAC: aucune commande trouvée sur %s", orders_page_url[:80])
            return {"count": 0, "files": []}

        filtered = self._filter_orders_by_date(
            orders, year=year, month=month, months=months,
            date_start_str=date_start, date_end_str=date_end,
        )
        filtered = filtered[:max_invoices]
        total = len(filtered)
        files: List[str] = []
        count = 0

        for i, order in enumerate(filtered):
            if count >= max_invoices:
                break
            await self._notify_progress(on_progress, count, total, f"Analyse commande {i + 1}/{total}…")

            if not force_redownload and self.registry.is_downloaded(PROVIDER_FNAC, order.order_id):
                logger.info("FNAC: %s déjà téléchargé, ignoré", order.order_id)
                continue

            url = order.invoice_url
            if not url:
                continue

            url_lower = url.lower()
            invoice_pdf_url: Optional[str] = None
            downloaded_directly = False

            if ".pdf" in url_lower:
                # Cas 1 : URL directe PDF
                invoice_pdf_url = url
            else:
                # Cas 2 : essayer les URLs d'invoice directes connues de FNAC
                base_order_url = url.rstrip("/")
                for suffix in ["/invoice", "/facture", "/invoice/download"]:
                    candidate = base_order_url + suffix
                    direct = self._download_pdf(candidate, order.order_id, order.invoice_date)
                    if direct:
                        self.registry.add(
                            PROVIDER_FNAC, order.order_id, direct,
                            invoice_date=order.invoice_date.isoformat() if order.invoice_date else None,
                        )
                        files.append(direct)
                        count += 1
                        await self._notify_progress(on_progress, count, total, f"{count}/{total} facture(s) téléchargée(s)")
                        logger.info("FNAC: facture via URL directe %s ->%s", suffix, direct)
                        downloaded_directly = True
                        break

                if downloaded_directly:
                    time.sleep(1)
                    continue

                # Cas 3 : téléchargement direct de l'URL commande (parfois PDF)
                direct = self._download_pdf(url, order.order_id, order.invoice_date)
                if direct:
                    self.registry.add(
                        PROVIDER_FNAC, order.order_id, direct,
                        invoice_date=order.invoice_date.isoformat() if order.invoice_date else None,
                    )
                    files.append(direct)
                    count += 1
                    await self._notify_progress(on_progress, count, total, f"{count}/{total} facture(s) téléchargée(s)")
                    logger.info("FNAC: facture téléchargée directement ->%s", direct)
                    time.sleep(1)
                    continue

                # Cas 4 : naviguer sur la page de détail et chercher le lien
                logger.info("FNAC: navigation vers %s", url[:80])
                existing_pdfs = set(self.download_path.glob("*.pdf"))
                try:
                    self.driver.get(url)  # type: ignore[union-attr]
                    time.sleep(4)
                    invoice_pdf_url = self._find_invoice_link_on_page()

                    # Cas 4b : le clic sur bouton a déclenché un download navigateur direct
                    if not invoice_pdf_url:
                        downloaded_path = self._wait_for_browser_download(existing_pdfs, max_wait=30)
                        if downloaded_path:
                            fname = self._rename_browser_download(downloaded_path, order.order_id, order.invoice_date)
                            self.registry.add(
                                PROVIDER_FNAC, order.order_id, fname,
                                invoice_date=order.invoice_date.isoformat() if order.invoice_date else None,
                            )
                            files.append(fname)
                            count += 1
                            await self._notify_progress(on_progress, count, total, f"{count}/{total} facture(s) téléchargée(s)")
                            logger.info("FNAC: facture download navigateur ->%s", fname)
                            time.sleep(1)
                            continue
                        logger.info("FNAC: aucun lien facture sur %s", url[:80])
                        continue
                except Exception as e:
                    logger.warning("FNAC: erreur navigation %s: %s", url[:60], e)
                    continue

            await self._notify_progress(on_progress, count, total, f"Téléchargement facture {count + 1}/{total}...")
            filename = self._download_pdf(invoice_pdf_url, order.order_id, order.invoice_date)
            if not filename:
                # Fallback : laisser le navigateur télécharger (gère les tokens JS/auth React)
                logger.info("FNAC: _download_pdf échoué, fallback navigateur pour %s", invoice_pdf_url[:80])
                existing_before_browser = set(self.download_path.glob("*.pdf"))
                try:
                    self.driver.get(invoice_pdf_url)  # type: ignore[union-attr]
                    downloaded_path = self._wait_for_browser_download(existing_before_browser, max_wait=30)
                    if downloaded_path:
                        filename = self._rename_browser_download(downloaded_path, order.order_id, order.invoice_date)
                        logger.info("FNAC: facture via browser download: %s", filename)
                except Exception as e:
                    logger.warning("FNAC: browser download fallback: %s", e)
            if filename:
                self.registry.add(
                    PROVIDER_FNAC, order.order_id, filename,
                    invoice_date=order.invoice_date.isoformat() if order.invoice_date else None,
                )
                files.append(filename)
                count += 1
                await self._notify_progress(on_progress, count, total, f"{count}/{total} facture(s) téléchargée(s)")
                logger.info("FNAC: facture téléchargée: %s", filename)
            else:
                logger.warning("FNAC: echec téléchargement %s", invoice_pdf_url[:60])

            time.sleep(1)

        logger.info("FNAC: %s facture(s) téléchargée(s) au total", count)
        return {"count": count, "files": files}

    async def close(self) -> None:
        if self.driver and not self.keep_browser_open:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def is_2fa_required(self) -> bool:
        return False

    async def submit_otp(self, otp_code: str) -> bool:
        return False
