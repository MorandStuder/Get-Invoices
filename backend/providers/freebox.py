"""
Provider Freebox (Espace abonné — adsl.free.fr).
Téléchargement des factures depuis l'espace client Freebox.
"""
from __future__ import annotations

import re
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from backend.providers.base import OrderInfo
from backend.services.invoice_registry import InvoiceRegistry

import logging

logger = logging.getLogger(__name__)

PROVIDER_FREEBOX = "freebox"

# Mois FR pour le parsing des titres de facture Freebox
_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# URLs Espace abonné Freebox (adsl.free.fr et moncompte.free.fr)
FREEBOX_LOGIN_URLS = [
    "https://adsl.free.fr/",
    "https://moncompte.free.fr/",
]
FREEBOX_BASE_URL = "https://adsl.free.fr"
# Chemins possibles pour la facturation après connexion
FREEBOX_FACTURATION_PATHS = [
    "/facturation/",
    "/mes-factures/",
    "/factures/",
    "/home.pl",
    "/",
]


class FreeboxProvider:
    """
    Fournisseur Freebox (Espace abonné — adsl.free.fr).
    Implémente InvoiceProviderProtocol.
    """

    PROVIDER_ID = PROVIDER_FREEBOX

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
            opts.add_argument(f"--user-data-dir={Path(self.chrome_user_data_dir).resolve()}")
        driver_path = ChromeDriverManager().install()
        service = ChromeService(driver_path)
        return webdriver.Chrome(service=service, options=opts)

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
        return webdriver.Firefox(service=FirefoxService(driver_path), options=opts)

    def _is_logged_in(self) -> bool:
        if not self.driver:
            return False
        url = self.driver.current_url
        if "adsl.free.fr" not in url and "moncompte.free.fr" not in url:
            return False
        # Non connecté : page affiche "Session invalide" + formulaire (Identifiant, Mot de passe, Se connecter)
        try:
            body = self.driver.page_source.lower()
            if "session invalide" in body:
                return False
            # Formulaire de login encore visible ?
            pwd_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                if "se connecter" in body:
                    return False
        except Exception:
            pass
        return True

    async def login(self, otp_code: Optional[str] = None) -> bool:
        try:
            if not self.driver:
                self.driver = self._setup_driver()
            if self._is_logged_in():
                logger.info("Freebox: déjà connecté")
                return True

            login_input = None
            pass_input = None
            for login_url in FREEBOX_LOGIN_URLS:
                self.driver.get(login_url)
                time.sleep(3)
                if "home.pl" not in self.driver.current_url and "free.fr" in self.driver.current_url:
                    time.sleep(2)

                # Sélecteurs pour le champ identifiant (adsl.free.fr, moncompte.free.fr)
                login_selectors = [
                    "input[name='login']",
                    "input[name='identifiant']",
                    "input[id='login']",
                    "input[id='identifiant']",
                    "input[placeholder*='dentifiant']",
                    "input[autocomplete='username']",
                    "input[type='text']:not([type='search'])",
                ]
                password_selectors = [
                    "input[name='pass']",
                    "input[name='password']",
                    "input[id='pass']",
                    "input[id='password']",
                    "input[placeholder*='mot de passe']",
                    "input[placeholder*='Password']",
                    "input[autocomplete='current-password']",
                    "input[type='password']",
                ]

                for sel in login_selectors:
                    try:
                        el = self.driver.find_element(By.CSS_SELECTOR, sel)
                        if el.is_displayed() and el.is_enabled():
                            login_input = el
                            break
                    except NoSuchElementException:
                        continue
                if login_input:
                    for sel in password_selectors:
                        try:
                            el = self.driver.find_element(By.CSS_SELECTOR, sel)
                            if el.is_displayed() and el.is_enabled():
                                pass_input = el
                                break
                        except NoSuchElementException:
                            continue
                if login_input and pass_input:
                    break
                # XPath de secours : input précédé d'un label contenant "dentifiant" ou "login"
                if not login_input:
                    try:
                        for el in self.driver.find_elements(By.XPATH, "//input[@type='text' or not(@type)]"):
                            if el.is_displayed() and el.get_attribute("type") != "search":
                                login_input = el
                                break
                    except Exception:
                        pass
                if not pass_input:
                    try:
                        pass_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    except NoSuchElementException:
                        pass
                if login_input and pass_input:
                    break

            if not login_input:
                logger.error(
                    "Freebox: champ identifiant non trouvé (page %s). Essayez moncompte.free.fr ou adsl.free.fr dans le navigateur.",
                    self.driver.current_url[:80],
                )
                return False
            if not pass_input:
                logger.error("Freebox: champ mot de passe non trouvé")
                return False

            login_input.clear()
            login_input.send_keys(self._login)
            pass_input.clear()
            pass_input.send_keys(self._password)

            submit_selectors = [
                "input[type='submit'][value*='connecter']",
                "input[type='submit']",
                "button[type='submit']",
                "button:contains('Se connecter')",
                "a.btn[href*='submit']",
            ]
            submit = None
            for sel in submit_selectors:
                try:
                    if ":contains" in sel:
                        for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                            if "connecter" in (btn.text or "").lower():
                                submit = btn
                                break
                        if submit:
                            break
                    else:
                        submit = self.driver.find_element(By.CSS_SELECTOR, sel)
                        if submit.is_displayed():
                            break
                except NoSuchElementException:
                    continue
            if not submit:
                submit = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
            submit.click()
            time.sleep(4)

            if not self._is_logged_in():
                logger.warning("Freebox: connexion peut avoir échoué (vérifier identifiants ou 2FA)")
                return False
            logger.info("Freebox: connexion réussie")
            return True
        except Exception as e:
            logger.error("Freebox login: %s", e)
            return False

    async def navigate_to_invoices(self) -> bool:
        if not self.driver:
            return False
        # Si déjà connecté et sur free.fr, vérifier si la page actuelle affiche déjà "Mes factures" (ex. home.pl)
        if self._is_logged_in() and "free.fr" in self.driver.current_url:
            already = self.list_orders_or_invoices()
            if already:
                logger.info("Freebox: déjà sur la page des factures (%s lien(s))", len(already))
                return True
        # Sinon naviguer vers une page de facturation
        for path in FREEBOX_FACTURATION_PATHS:
            url = FREEBOX_BASE_URL.rstrip("/") + path
            self.driver.get(url)
            time.sleep(3)
            if self._is_logged_in():
                already = self.list_orders_or_invoices()
                if already:
                    return True
                try:
                    for link in self.driver.find_elements(By.TAG_NAME, "a"):
                        href = (link.get_attribute("href") or "").lower()
                        text = (link.text or "").lower()
                        if "factur" in text or "factur" in href:
                            link.click()
                            time.sleep(3)
                            break
                except Exception:
                    pass
                return True
        return self._is_logged_in()

    def _parse_invoice_date_from_title(self, title: str) -> Optional[date_type]:
        """Parse la date de facture depuis le titre (ex. 'Télécharger... facture de février 2026')."""
        if not title:
            return None
        title_lower = title.lower()
        # "facture de février 2026" ou "février 2026"
        for mois_name, mois_num in _MOIS_FR.items():
            match = re.search(rf"{re.escape(mois_name)}\s+(\d{{4}})", title_lower)
            if match:
                try:
                    year = int(match.group(1))
                    if 2000 <= year <= 2100:
                        return date_type(year, mois_num, 1)
                except (ValueError, TypeError):
                    pass
        # "2026-02" ou "02/2026"
        match = re.search(r"(\d{4})[-/](\d{1,2})", title)
        if match:
            try:
                y, m = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        return None

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Liste les factures visibles (liens facture.pdf.pl ou PDF / téléchargement) avec date parsée."""
        from urllib.parse import urljoin
        out: List[OrderInfo] = []
        if not self.driver:
            return out
        try:
            base_url = self.driver.current_url
            selectors = [
                "a.btn.download[href*='facture']",
                "a[href*='facture.pdf.pl']",
                "a[href*='.pdf']",
                "a[href*='facture']",
                "a[href*='download']",
                "a[href*='telecharger']",
            ]
            seen_hrefs: set[str] = set()
            for selector in selectors:
                links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for i, a in enumerate(links):
                    href = (a.get_attribute("href") or "").strip()
                    if not href or "logout" in href.lower():
                        continue
                    if href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)
                    if not href.startswith("http"):
                        href = urljoin(base_url, href)
                    title = (a.get_attribute("title") or a.text or "").strip()
                    inv_date = self._parse_invoice_date_from_title(title)
                    order_id = f"freebox_inv_{i}_{hash(href) % 100000}"
                    out.append(OrderInfo(order_id=order_id, invoice_url=href, invoice_date=inv_date, raw_element=a))
                if out:
                    break
        except Exception as e:
            logger.debug("Freebox list_orders: %s", e)
        return out

    def _filter_orders_by_date(
        self,
        orders: List[OrderInfo],
        year: Optional[int] = None,
        month: Optional[int] = None,
        months: Optional[List[int]] = None,
        date_start_str: Optional[str] = None,
        date_end_str: Optional[str] = None,
    ) -> List[OrderInfo]:
        """Filtre les factures par année / mois / plage (comme Amazon)."""
        from datetime import datetime
        if not any([year is not None, month is not None, months, date_start_str, date_end_str]):
            return orders
        if date_start_str and date_end_str:
            try:
                start_d = datetime.strptime(date_start_str, "%Y-%m-%d").date()
                end_d = datetime.strptime(date_end_str, "%Y-%m-%d").date()
            except ValueError:
                return orders
            return [o for o in orders if o.invoice_date and start_d <= o.invoice_date <= end_d]
        if year is not None and months:
            return [o for o in orders if o.invoice_date and o.invoice_date.year == year and o.invoice_date.month in months]
        out: List[OrderInfo] = []
        for o in orders:
            if not o.invoice_date:
                continue
            if year is not None and o.invoice_date.year != year:
                continue
            if month is not None and o.invoice_date.month != month:
                continue
            out.append(o)
        return out

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
            if "pdf" not in ct and not (r.content[:4] == b"%PDF"):
                return None
            if invoice_date:
                # Même logique qu'Amazon : date en préfixe (ex. freebox_2026-02-01_inv_0.pdf)
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"freebox_{invoice_date.isoformat()}_{short_id}.pdf"
            else:
                name = f"freebox_{order_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("Freebox download %s: %s", url[:60], e)
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
        if not force_redownload and self.registry.is_downloaded(PROVIDER_FREEBOX, oid):
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
            self.registry.add(PROVIDER_FREEBOX, oid, filename, invoice_date=invoice_date.isoformat() if invoice_date else None)
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
        ok = await self.login(otp_code=otp_code)
        if not ok:
            raise Exception("Échec de la connexion à l'espace Freebox")
        if not await self.navigate_to_invoices():
            raise Exception("Impossible d'accéder à la page des factures Freebox")

        orders = self.list_orders_or_invoices()
        if not orders:
            logger.warning("Freebox: aucune facture trouvée sur la page (vérifier sélecteurs ou URL)")
            return {"count": 0, "files": []}

        filtered = self._filter_orders_by_date(
            orders,
            year=year,
            month=month,
            months=months,
            date_start_str=date_start,
            date_end_str=date_end,
        )
        if year is not None or month is not None or months or date_start or date_end:
            logger.info(
                "Freebox filtre (year=%s month=%s months=%s plage=%s..%s): %s -> %s facture(s)",
                year, month, months, date_start, date_end, len(orders), len(filtered),
            )
        if not filtered and orders:
            with_date = sum(1 for o in orders if o.invoice_date)
            logger.warning(
                "Freebox: 0 facture après filtre alors que %s lien(s) trouvé(s) (%s avec date reconnue). Vérifier le format des titres (ex. « facture de février 2026 »).",
                len(orders), with_date,
            )

        total = min(len(filtered), max_invoices)
        files: List[str] = []
        count = 0
        for i, order in enumerate(filtered):
            if count >= max_invoices:
                break
            if on_progress:
                try:
                    cb = on_progress(count, total, f"Téléchargement facture {count + 1}/{total}…")
                    if hasattr(cb, "__await__"):
                        await cb  # type: ignore[misc]
                except Exception:
                    pass
            fn = await self.download_invoice(
                order,
                order_index=i,
                order_id=order.order_id,
                invoice_date=order.invoice_date,
                force_redownload=force_redownload,
            )
            if fn:
                files.append(fn)
                count += 1
                if on_progress:
                    try:
                        cb = on_progress(count, total, f"{count}/{total} facture(s) téléchargée(s)")
                        if hasattr(cb, "__await__"):
                            await cb  # type: ignore[misc]
                    except Exception:
                        pass
            time.sleep(1)
        logger.info("Freebox: %s facture(s) téléchargée(s)", count)
        return {"count": count, "files": files}

    async def close(self) -> None:
        if self.driver and not self.keep_browser_open:
            self.driver.quit()
            self.driver = None

    def is_2fa_required(self) -> bool:
        if not self.driver:
            return False
        try:
            self.driver.find_element(By.CSS_SELECTOR, "input[name*='otp'], input[name*='code'], input[type='tel'][maxlength='6']")
            return True
        except NoSuchElementException:
            return False

    async def submit_otp(self, otp_code: str) -> bool:
        if not self.driver:
            return False
        try:
            inp = self.driver.find_element(By.CSS_SELECTOR, "input[name*='otp'], input[name*='code'], input[type='tel']")
            inp.clear()
            inp.send_keys(otp_code)
            self.driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']").click()
            time.sleep(4)
            return self._is_logged_in()
        except Exception as e:
            logger.warning("Freebox submit_otp: %s", e)
            return False
