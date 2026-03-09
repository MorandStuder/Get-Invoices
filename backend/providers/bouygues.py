"""
Provider Bouygues Telecom (Espace client).
Mode initial très simple et semi-manuel :
- le provider ouvre une session navigateur authentifiée (via ton profil),
- tu navigues toi-même vers la page de factures,
- le provider ne fait que lister et télécharger les liens PDF visibles.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
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

PROVIDER_BOUYGUES = "bouygues"

BOUYGUES_BASE_URL = "https://www.bouyguestelecom.fr"
# Page directe "Mes factures" (avec profil connecté, on arrive sur la liste des factures)
BOUYGUES_MES_FACTURES_URL = "https://www.bouyguestelecom.fr/mon-compte/mes-factures"


class BouyguesProvider:
    """
    Fournisseur Bouygues Telecom (Espace client).

    Mode semi-manuel :
    - login() ouvre simplement la page d'accueil Bouygues Telecom avec ton profil navigateur ;
    - tu te connectes et navigues vers la page Factures ;
    - download_invoices() lit les liens PDF visibles et les télécharge un par un.
    """

    PROVIDER_ID = PROVIDER_BOUYGUES

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

    @property
    def login_identifier(self) -> str:
        """Exposé uniquement pour les tests (comme Freebox)."""
        return self._login

    def _setup_driver(self) -> Union[webdriver.Chrome, webdriver.Firefox]:
        if self.browser == "firefox":
            return self._setup_firefox()
        return self._setup_chrome()

    def _setup_chrome(self) -> webdriver.Chrome:
        opts = ChromeOptions()
        if self.headless:
            opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        prefs = {
            "download.default_directory": str(self.download_path.absolute()),
            "download.prompt_for_download": False,
        }
        opts.add_experimental_option("prefs", prefs)
        if self.chrome_user_data_dir:
            opts.add_argument(
                f"--user-data-dir={Path(self.chrome_user_data_dir).resolve()}"
            )
        driver_path = ChromeDriverManager().install()
        service = ChromeService(driver_path)
        return webdriver.Chrome(service=service, options=opts)

    def _setup_firefox(self) -> webdriver.Firefox:
        opts = FirefoxOptions()
        if self.headless:
            opts.add_argument("--headless")
        if self.firefox_profile_path and Path(self.firefox_profile_path).exists():
            opts.profile = FirefoxProfile(self.firefox_profile_path)
        driver_path = GeckoDriverManager().install()
        return webdriver.Firefox(service=FirefoxService(driver_path), options=opts)

    def _dismiss_consent_banner(self) -> None:
        """Ferme le bandeau cookies / consentement s'il est affiché."""
        if not self.driver:
            return
        try:
            for text in (
                "tout accepter",
                "accepter",
                "accepter tous",
                "ok",
                "continuer",
                "j'accepte",
            ):
                for tag in ["button", "a", "span", "div"]:
                    try:
                        els = self.driver.find_elements(By.TAG_NAME, tag)
                        for el in els:
                            if not el.is_displayed():
                                continue
                            t = (
                                (el.text or el.get_attribute("aria-label") or "")
                                .strip()
                                .lower()
                            )
                            if text in t and len(t) < 80:
                                el.click()
                                time.sleep(1)
                                return
                            if (
                                el.get_attribute("data-testid")
                                and "accept"
                                in (el.get_attribute("data-testid") or "").lower()
                            ):
                                el.click()
                                time.sleep(1)
                                return
                    except Exception:
                        continue
        except Exception:
            pass

    def _is_logged_in(self) -> bool:
        """Vérifie si on est sur l'espace client connecté (page factures ou mon-compte)."""
        if not self.driver:
            return False
        url = (self.driver.current_url or "").lower()
        if "bouyguestelecom.fr" not in url and "b-and-you.fr" not in url:
            return False
        try:
            body = self.driver.page_source.lower()
            # Indices de connexion : mes factures, mon compte, déconnexion
            if (
                "mes factures" in body
                or "mon compte" in body
                or "déconnexion" in body
                or "personid=" in url
            ):
                return True
            # Formulaire de connexion visible = pas connecté
            pwd_fields = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            )
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                return False
            # URL mes-factures sans formulaire login = probablement connecté
            if "mes-factures" in url or "mon-compte" in url:
                return True
            return False
        except Exception:
            pass
        return False

    def _find_and_fill_login_form(self) -> bool:
        """Remplit le formulaire de connexion (identifiant + mot de passe) et soumet."""
        wait = WebDriverWait(self.driver, self.timeout)
        try:
            # Attendre qu'au moins un champ de formulaire soit présent
            wait.until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "input[type='text'], input[type='email'], input[type='password'], input[name], input[id]",
                    )
                )
            )
        except TimeoutException:
            logger.warning("Bouygues: aucun champ de formulaire trouvé après attente")
            return False

        login_selectors = [
            "input[name='login']",
            "input[name='username']",
            "input[name='email']",
            "input[name='identifiant']",
            "input[id='login']",
            "input[id='username']",
            "input[id='email']",
            "input[id='identifiant']",
            "input[type='email']",
            "input[autocomplete='username']",
            "input[placeholder*='mail']",
            "input[placeholder*='identifiant']",
            "input[placeholder*='e-mail']",
            "input[placeholder*='numéro']",
            "input[type='text']",
        ]
        password_selectors = [
            "input[name='password']",
            "input[name='pass']",
            "input[name='motdepasse']",
            "input[id='password']",
            "input[id='pass']",
            "input[type='password']",
            "input[autocomplete='current-password']",
            "input[autocomplete='off'][type='password']",
        ]
        login_input = None
        pass_input = None
        for sel in login_selectors:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if (
                        el.is_displayed()
                        and el.is_enabled()
                        and el.get_attribute("type") != "hidden"
                    ):
                        login_input = el
                        break
                if login_input:
                    break
            except NoSuchElementException:
                continue
        for sel in password_selectors:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.is_enabled():
                        pass_input = el
                        break
                if pass_input:
                    break
            except NoSuchElementException:
                continue
        if not login_input:
            logger.warning(
                "Bouygues: champ identifiant non trouvé (page peut avoir changé)"
            )
            return False
        if not pass_input:
            logger.warning(
                "Bouygues: champ mot de passe non trouvé (connexion par code SMS ?)"
            )
            return False
        try:
            login_input.clear()
            login_input.send_keys(self._login)
            pass_input.clear()
            pass_input.send_keys(self._password)
        except Exception as e:
            logger.warning("Bouygues: erreur saisie formulaire: %s", e)
            return False
        time.sleep(0.5)
        # Soumission : bouton submit, puis lien/bouton "Se connecter"
        for sel in [
            "button[type='submit']",
            "input[type='submit']",
            "button[data-testid*='submit']",
            "[data-testid*='login-submit']",
            "input[value*='Connecter']",
            "input[value*='connecter']",
            "button[type='button']",
        ]:
            try:
                for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if not btn.is_displayed():
                        continue
                    t = (btn.text or btn.get_attribute("value") or "").lower()
                    if (
                        "submit" in sel
                        or "connecter" in t
                        or "connexion" in t
                        or "valider" in t
                    ):
                        btn.click()
                        return True
            except NoSuchElementException:
                continue
        for btn in self.driver.find_elements(By.TAG_NAME, "button"):
            if btn.is_displayed():
                t = (btn.text or "").lower()
                if (
                    "connecter" in t
                    or "connexion" in t
                    or "valider" in t
                    or "continuer" in t
                ):
                    btn.click()
                    return True
        for inp in self.driver.find_elements(By.CSS_SELECTOR, "input[type='submit']"):
            if inp.is_displayed():
                inp.click()
                return True
        # Dernier recours : soumettre le formulaire parent
        try:
            form = login_input.find_element(By.XPATH, "./ancestor::form[1]")
            form.submit()
            return True
        except NoSuchElementException:
            pass
        logger.warning("Bouygues: bouton de connexion non trouvé")
        return False

    async def login(self, otp_code: Optional[str] = None) -> bool:
        """
        Ouvre la page Mes factures et se connecte automatiquement si un formulaire est affiché.
        """
        if not self.driver:
            self.driver = self._setup_driver()
        try:
            self.driver.get(BOUYGUES_MES_FACTURES_URL)
            time.sleep(4)
            self._dismiss_consent_banner()
            time.sleep(1)
            if self._is_logged_in():
                logger.info("Bouygues: déjà connecté, page Mes factures affichée.")
                return True
            # Sinon on est sur une page de connexion : remplir et soumettre
            logger.info(
                "Bouygues: formulaire de connexion détecté, connexion automatique…"
            )
            if not self._find_and_fill_login_form():
                return False
            time.sleep(5)
            if self._is_logged_in():
                logger.info("Bouygues: connexion réussie.")
                return True
            # Redirection possible : réessayer la page factures
            self.driver.get(BOUYGUES_MES_FACTURES_URL)
            time.sleep(4)
            if self._is_logged_in():
                logger.info("Bouygues: connexion réussie (après redirection).")
                return True
            logger.warning(
                "Bouygues: connexion peut avoir échoué (vérifier identifiants ou captcha)."
            )
            return False
        except Exception as e:
            logger.error("Bouygues login: %s", e)
            return False

    async def navigate_to_invoices(self) -> bool:
        """
        Mode semi-manuel : on considère que tu as déjà navigué vers la page 'Factures'.
        Cette méthode se contente de vérifier que le domaine est bien Bouygues Telecom.
        """
        if not self.driver:
            return False
        current = (self.driver.current_url or "").lower()
        if "bouyguestelecom.fr" in current or "b-and-you.fr" in current:
            return True
        logger.warning(
            "Bouygues: URL actuelle inattendue pour les factures: %s", current
        )
        return False

    def _parse_invoice_date_from_text(self, text: str) -> Optional[date_type]:
        """
        Parsing très basique : essaye de repérer YYYY-MM ou YYYY/MM dans le texte.
        Suffisant pour nommer les fichiers proprement sans garantie forte.
        """
        if not text:
            return None
        match = re.search(r"(\d{4})[-/](\d{1,2})", text)
        if not match:
            return None
        try:
            year = int(match.group(1))
            month = int(match.group(2))
            if 2000 <= year <= 2100 and 1 <= month <= 12:
                return date_type(year, month, 1)
        except Exception:
            return None
        return None

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """
        Liste les liens de téléchargement de factures visibles sur la page courante.
        Hypothèse : tu es déjà sur une page de facturation Bouygues.
        """
        from urllib.parse import urljoin

        out: List[OrderInfo] = []
        if not self.driver:
            return out

        try:
            base_url = self.driver.current_url
            seen: set[str] = set()
            links = self.driver.find_elements(By.TAG_NAME, "a")
            for idx, a in enumerate(links):
                href = (a.get_attribute("href") or "").strip()
                text = (a.text or "").strip().lower()
                title = (a.get_attribute("title") or "").strip().lower()
                if not href or href == "#":
                    continue
                if (
                    ".pdf" not in href
                    and "facture" not in text
                    and "facture" not in title
                ):
                    continue
                full = urljoin(base_url, href) if not href.startswith("http") else href
                if full in seen:
                    continue
                seen.add(full)
                inv_date = self._parse_invoice_date_from_text(title or text or href)
                order_id = f"bouygues_inv_{idx}_{hash(full) % 100000}"
                out.append(
                    OrderInfo(
                        order_id=order_id,
                        invoice_url=full,
                        invoice_date=inv_date,
                        raw_element=a,
                    )
                )
        except Exception as e:
            logger.warning("Bouygues list_orders_or_invoices: %s", e)
        return out

    def _get_browser_session(self) -> Any:
        """Recrée une session HTTP à partir des cookies du navigateur Selenium."""
        import requests

        if not self.driver:
            raise RuntimeError("Bouygues: driver non initialisé")
        session = requests.Session()
        for c in self.driver.get_cookies():
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        # User-Agent pour limiter les comportements suspects côté serveur
        try:
            ua = self.driver.execute_script("return navigator.userAgent;")
            if isinstance(ua, str) and ua:
                session.headers["User-Agent"] = ua
        except Exception:
            pass
        return session

    def _download_pdf(
        self, url: str, order_id: str, invoice_date: Optional[date_type] = None
    ) -> Optional[str]:
        """Télécharge un PDF en réutilisant la session navigateur."""
        try:
            session = self._get_browser_session()
            r = session.get(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code != 200:
                logger.warning("Bouygues: HTTP %s pour %s", r.status_code, url)
                return None
            ct = r.headers.get("content-type", "").lower()
            if "pdf" not in ct and not (
                len(r.content) >= 4 and r.content[:4] == b"%PDF"
            ):
                logger.warning("Bouygues: contenu non PDF pour %s", url)
                return None
            if invoice_date:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"bouygues_{invoice_date.isoformat()}_{short_id}.pdf"
            else:
                name = f"bouygues_{order_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("Bouygues download %s: %s", url[:60], e)
            return None

    async def download_invoice(
        self,
        order_or_id: Any,
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date_type] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        """Télécharge une facture individuelle à partir d'un OrderInfo ou d'une URL brute."""
        oid = order_id or (
            order_or_id.order_id
            if isinstance(order_or_id, OrderInfo)
            else str(order_or_id)
        )
        if not force_redownload and self.registry.is_downloaded(PROVIDER_BOUYGUES, oid):
            logger.info("Bouygues: facture déjà présente pour %s, skip", oid)
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
            self.registry.add(
                PROVIDER_BOUYGUES,
                oid,
                filename,
                invoice_date=invoice_date.isoformat() if invoice_date else None,
            )
        return filename

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
        """
        Télécharge les factures visibles sur la page courante.
        Les filtres de dates ne sont pas encore implémentés pour Bouygues (V1 simple).
        """
        ok = await self.login(otp_code=otp_code)
        if not ok:
            raise Exception("Échec de l'ouverture de session Bouygues Telecom")
        if not await self.navigate_to_invoices():
            # En mode semi-manuel, on ne bloque pas : on tente quand même la liste.
            logger.warning(
                "Bouygues: navigate_to_invoices a échoué, on tente list_orders_or_invoices sur la page actuelle."
            )
        orders = self.list_orders_or_invoices()
        if not orders:
            return {"count": 0, "files": []}
        total = min(len(orders), max_invoices)
        files: List[str] = []
        count = 0
        for idx, order in enumerate(orders):
            if count >= max_invoices:
                break
            if on_progress:
                try:
                    msg = f"Téléchargement facture {count + 1}/{total}…"
                    cb = on_progress(count, total, msg)
                    if hasattr(cb, "__await__"):
                        await cb
                except Exception:
                    pass
            fn = await self.download_invoice(
                order,
                order_index=idx,
                order_id=order.order_id,
                invoice_date=order.invoice_date,
                force_redownload=force_redownload,
            )
            if fn:
                files.append(fn)
                count += 1
                if on_progress:
                    try:
                        msg = f"{count}/{total} facture(s)"
                        cb = on_progress(count, total, msg)
                        if hasattr(cb, "__await__"):
                            await cb
                    except Exception:
                        pass
            time.sleep(1)
        logger.info("Bouygues: %s facture(s) téléchargée(s)", count)
        return {"count": count, "files": files}

    async def close(self) -> None:
        if self.driver and not self.keep_browser_open:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def is_2fa_required(self) -> bool:
        # V1 simple : pas de détection spécifique 2FA, on s'appuie sur le navigateur manuel.
        return False

    async def submit_otp(self, otp_code: str) -> bool:
        # V1 simple : pas de flux OTP automatisé pour Bouygues.
        return False
