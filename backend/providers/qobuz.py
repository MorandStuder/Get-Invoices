"""
Provider Qobuz — espace client qobuz.com.
Télécharge les factures / reçus de commandes depuis l'historique des achats.
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

PROVIDER_QOBUZ = "qobuz"

QOBUZ_LOGIN_URL = "https://www.qobuz.com/signin"
QOBUZ_INVOICES_URL = "https://www.qobuz.com/profile/invoice"
QOBUZ_ACCOUNT_URL = "https://www.qobuz.com/fr-fr/account"


class QobuzProvider:
    """
    Fournisseur Qobuz (espace client).
    Implémente InvoiceProviderProtocol.
    """

    PROVIDER_ID = PROVIDER_QOBUZ

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
        self.email = login  # stocké sous email pour éviter l'écrasement de la méthode login()
        self._password = password
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout = timeout
        self.browser = browser.lower()
        self.firefox_profile_path = firefox_profile_path
        self.chrome_user_data_dir = chrome_user_data_dir
        self.keep_browser_open = keep_browser_open
        self.driver: Optional[Union[webdriver.Chrome, webdriver.Firefox]] = (
            None
        )
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
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
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
        if (
            self.firefox_profile_path
            and Path(self.firefox_profile_path).exists()
        ):
            opts.profile = FirefoxProfile(self.firefox_profile_path)
        driver_path = GeckoDriverManager().install()
        return webdriver.Firefox(
            service=FirefoxService(driver_path), options=opts
        )

    def _dismiss_consent_banner(self) -> None:
        """Ferme le bandeau cookies/consentement s'il est affiché."""
        if not self.driver:
            return
        try:
            for sel in [
                "button[data-testid='accept-all']",
                "button[id*='accept']",
                "button[class*='accept']",
                "#didomi-notice-agree-button",
                "#onetrust-accept-btn-handler",
            ]:
                try:
                    btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        return
                except NoSuchElementException:
                    continue
            # Fallback : chercher par texte
            for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                if not btn.is_displayed():
                    continue
                t = (btn.text or "").strip().lower()
                if t in (
                    "tout accepter",
                    "accepter",
                    "j'accepte",
                    "ok",
                    "accept all",
                ):
                    btn.click()
                    time.sleep(1)
                    return
        except Exception:
            pass

    def _is_logged_in(self) -> bool:
        """Vérifie si on est connecté sur qobuz.com."""
        if not self.driver:
            return False
        url = (self.driver.current_url or "").lower()
        if "qobuz.com" not in url:
            return False
        # Page de login visible = pas connecté
        if "/login" in url or "/signin" in url:
            return False
        try:
            body = self.driver.page_source.lower()
            # Indicateurs de connexion
            if any(
                k in body
                for k in (
                    "logout",
                    "déconnexion",
                    "mon compte",
                    "my account",
                    "purchases",
                    "achats",
                )
            ):
                return True
            # Champ mot de passe visible = pas connecté
            pwd_fields = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            )
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                return False
            if "/account" in url or "/profile" in url:
                return True
        except Exception:
            pass
        return False

    def _fill_login_form(self) -> bool:
        """Remplit le formulaire de connexion Qobuz."""
        if not self.driver:
            return False
        wait = WebDriverWait(self.driver, self.timeout)
        try:
            # Attendre n'importe quel input visible (SPA peut charger lentement)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input"))
            )
        except TimeoutException:
            logger.warning("Qobuz: aucun champ de formulaire trouvé")
            return False

        login_selectors = [
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "input[id='username']",
            "input[id='email']",
            "input[autocomplete='username']",
            "input[autocomplete='email']",
            "input[type='text']",
        ]
        password_selectors = [
            "input[name='password']",
            "input[type='password']",
            "input[id='password']",
            "input[autocomplete='current-password']",
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
            logger.warning("Qobuz: champ identifiant non trouvé")
            return False
        if not pass_input:
            logger.warning("Qobuz: champ mot de passe non trouvé")
            return False

        try:
            login_input.clear()
            login_input.send_keys(self.email)
            pass_input.clear()
            pass_input.send_keys(self._password)
        except Exception as e:
            logger.warning("Qobuz: erreur saisie formulaire: %s", e)
            return False

        time.sleep(0.5)
        # Soumettre
        for sel in ["button[type='submit']", "input[type='submit']"]:
            try:
                for btn in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if btn.is_displayed():
                        btn.click()
                        return True
            except NoSuchElementException:
                continue
        for btn in self.driver.find_elements(By.TAG_NAME, "button"):
            if btn.is_displayed():
                t = (btn.text or "").lower()
                if any(
                    k in t
                    for k in (
                        "connexion",
                        "connecter",
                        "login",
                        "sign in",
                        "valider",
                    )
                ):
                    btn.click()
                    return True
        try:
            form = login_input.find_element(By.XPATH, "./ancestor::form[1]")
            form.submit()
            return True
        except NoSuchElementException:
            pass
        logger.warning("Qobuz: bouton de connexion non trouvé")
        return False

    async def login(self, otp_code: Optional[str] = None) -> bool:
        """Ouvre la page Qobuz et se connecte."""
        if not self.driver:
            self.driver = self._setup_driver()
        try:
            self.driver.get(QOBUZ_LOGIN_URL)
            time.sleep(3)
            self._dismiss_consent_banner()
            time.sleep(1)
            if self._is_logged_in():
                logger.info("Qobuz: déjà connecté.")
                return True
            logger.info(
                "Qobuz: formulaire de connexion détecté, connexion automatique…"
            )
            if not self._fill_login_form():
                return False
            time.sleep(5)
            if self._is_logged_in():
                logger.info("Qobuz: connexion réussie.")
                return True
            # Réessayer sur la page account
            self.driver.get(QOBUZ_ACCOUNT_URL)
            time.sleep(3)
            if self._is_logged_in():
                logger.info("Qobuz: connexion réussie (après redirection).")
                return True
            logger.warning("Qobuz: connexion peut avoir échoué.")
            return False
        except Exception as e:
            logger.error("Qobuz login: %s", e)
            return False

    async def navigate_to_invoices(self) -> bool:
        """Navigue vers la page des achats/factures Qobuz."""
        if not self.driver:
            return False
        # Essayer d'abord la page invoices connue, puis account
        for url in (QOBUZ_INVOICES_URL, QOBUZ_ACCOUNT_URL):
            try:
                self.driver.get(url)
                time.sleep(3)
                if self._is_logged_in():
                    logger.info(
                        "Qobuz: page factures/achats ouverte (%s)", url
                    )
                    return True
            except Exception:
                continue
        return False

    def _parse_date_from_text(self, text: str) -> Optional[date_type]:
        """Extrait une date du texte (formats FR et ISO)."""
        if not text:
            return None
        # Format ISO : 2024-01-15
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            try:
                return date_type(
                    int(m.group(1)), int(m.group(2)), int(m.group(3))
                )
            except Exception:
                pass
        # Format FR : 15/01/2024 ou 15-01-2024
        m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
        if m:
            try:
                return date_type(
                    int(m.group(3)), int(m.group(2)), int(m.group(1))
                )
            except Exception:
                pass
        return None

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """
        Liste les reçus sur la page courante de /profile/invoice.
        Cherche les liens /profile/receipt/{id} et extrait la date depuis la ligne du tableau.
        """
        out: List[OrderInfo] = []
        if not self.driver:
            return out
        try:
            seen: set = set()
            links = self.driver.find_elements(
                By.CSS_SELECTOR, "a[href*='/profile/receipt/']"
            )
            for a in links:
                href = (a.get_attribute("href") or "").strip()
                if not href or href in seen:
                    continue
                seen.add(href)

                # Extraire l'ID de commande depuis l'URL
                m = re.search(r"/profile/receipt/(\w+)", href)
                receipt_id = (
                    m.group(1) if m else re.sub(r"[^\w]", "_", href)[-20:]
                )
                order_id = f"qobuz_{receipt_id}"

                # Chercher la date dans la ligne parente (tr ou div conteneur)
                inv_date = None
                try:
                    row = a.find_element(By.XPATH, "./ancestor::tr[1]")
                    inv_date = self._parse_date_from_text(row.text)
                except NoSuchElementException:
                    pass
                if inv_date is None:
                    try:
                        parent = a.find_element(
                            By.XPATH,
                            "./ancestor::*[contains(@class,'row') or contains(@class,'item') or contains(@class,'order') or contains(@class,'purchase')][1]",
                        )
                        inv_date = self._parse_date_from_text(parent.text)
                    except Exception:
                        pass

                out.append(
                    OrderInfo(
                        order_id=order_id,
                        invoice_url=href,
                        invoice_date=inv_date,
                        raw_element=a,
                    )
                )
        except Exception as e:
            logger.warning("Qobuz list_orders_or_invoices: %s", e)
        logger.info(
            "Qobuz: %d reçu(s) trouvé(s) sur la page courante", len(out)
        )
        return out

    def _download_pdf_cdp(
        self, url: str, order_id: str, invoice_date: Optional[date_type] = None
    ) -> Optional[str]:
        """
        Navigue vers le reçu HTML Qobuz et l'exporte en PDF via CDP Page.printToPDF.
        Nécessite Chrome (Firefox ne supporte pas CDP printToPDF).
        """
        import base64

        try:
            if not self.driver:
                return None
            if self.browser != "chrome":
                logger.warning(
                    "Qobuz: CDP printToPDF nécessite Chrome (actuel: %s)",
                    self.browser,
                )
                return None

            self.driver.get(url)
            time.sleep(3)

            result = self.driver.execute_cdp_cmd(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "paperWidth": 8.27,  # A4 en pouces
                    "paperHeight": 11.69,
                    "marginTop": 0.4,
                    "marginBottom": 0.4,
                    "marginLeft": 0.4,
                    "marginRight": 0.4,
                    "scale": 0.9,
                },
            )
            pdf_bytes = base64.b64decode(result.get("data", ""))
            if not pdf_bytes:
                logger.warning(
                    "Qobuz: CDP printToPDF données vides pour %s", url
                )
                return None

            if invoice_date:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"qobuz_{invoice_date.isoformat()}_{short_id}.pdf"
            else:
                name = f"qobuz_{order_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(pdf_bytes)
            logger.info("Qobuz: reçu sauvegardé → %s", name)
            return name
        except Exception as e:
            logger.warning("Qobuz CDP printToPDF %s: %s", url[:60], e)
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
            PROVIDER_QOBUZ, oid
        ):
            logger.info("Qobuz: facture déjà présente pour %s, skip", oid)
            return None
        url = None
        if isinstance(order_or_id, OrderInfo) and order_or_id.invoice_url:
            url = order_or_id.invoice_url
        if (
            not url
            and isinstance(order_or_id, str)
            and order_or_id.startswith("http")
        ):
            url = order_or_id
        if not url:
            return None
        filename = self._download_pdf_cdp(url, oid, invoice_date)
        if filename:
            self.registry.add(
                PROVIDER_QOBUZ,
                oid,
                filename,
                invoice_date=(
                    invoice_date.isoformat() if invoice_date else None
                ),
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
        ok = await self.login(otp_code=otp_code)
        if not ok:
            raise Exception("Échec de la connexion à Qobuz")
        if not await self.navigate_to_invoices():
            logger.warning(
                "Qobuz: navigate_to_invoices a échoué, tentative sur page actuelle."
            )

        # Filtre de dates
        date_start_d = None
        date_end_d = None
        if date_start:
            try:
                date_start_d = date_type.fromisoformat(date_start)
            except Exception:
                pass
        if date_end:
            try:
                date_end_d = date_type.fromisoformat(date_end)
            except Exception:
                pass

        # Collecter toutes les commandes avec pagination (/profile/invoice?page=N)
        all_orders: List[OrderInfo] = []
        seen_ids: set = set()
        page = 1
        while True:
            page_url = f"{QOBUZ_INVOICES_URL}?page={page}"
            try:
                self.driver.get(page_url)  # type: ignore[union-attr]
                time.sleep(3)
            except Exception as nav_err:
                logger.warning("Qobuz: navigation page %d: %s", page, nav_err)
                break
            page_orders = self.list_orders_or_invoices()
            if not page_orders:
                logger.info("Qobuz: plus de résultats à la page %d", page)
                break
            new_orders = [o for o in page_orders if o.order_id not in seen_ids]
            if not new_orders:
                logger.info(
                    "Qobuz: page %d sans nouvelles entrées, arrêt", page
                )
                break
            for o in new_orders:
                seen_ids.add(o.order_id)
            all_orders.extend(new_orders)
            logger.info(
                "Qobuz: page %d → %d reçus (total: %d)",
                page,
                len(new_orders),
                len(all_orders),
            )
            # Vérifier s'il y a une page suivante
            try:
                src = self.driver.page_source  # type: ignore[union-attr]
                has_next = (
                    f"page={page + 1}" in src
                    or "suivant" in src.lower()
                    or "next" in src.lower()
                )
                if not has_next:
                    logger.info(
                        "Qobuz: pas de page suivante après page %d", page
                    )
                    break
            except Exception:
                break
            page += 1
            if page > 100:  # garde-fou
                break

        orders = all_orders
        if not orders:
            logger.info("Qobuz: aucune facture trouvée.")
            return {"count": 0, "files": []}

        # Filtrage par date
        has_filter = bool(
            year or month or months or date_start_d or date_end_d
        )
        filtered = []
        for o in orders:
            d = o.invoice_date
            if d is None:
                # Quand un filtre est actif et qu'on ne connaît pas la date,
                # on exclut pour éviter de télécharger tous les achats Qobuz.
                if has_filter:
                    continue
                filtered.append(o)
                continue
            if year and d.year != year:
                continue
            if month and d.month != month:
                continue
            if months and d.month not in months:
                continue
            if date_start_d and d < date_start_d:
                continue
            if date_end_d and d > date_end_d:
                continue
            filtered.append(o)
        if has_filter:
            logger.info(
                "Qobuz filtre date: %d/%d reçus correspondent",
                len(filtered),
                len(orders),
            )

        total = min(len(filtered), max_invoices)
        files: List[str] = []
        count = 0

        for idx, order in enumerate(filtered):
            if count >= max_invoices:
                break
            if on_progress:
                try:
                    cb = on_progress(
                        count,
                        total,
                        f"Téléchargement facture {count + 1}/{total}…",
                    )
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
                        cb = on_progress(
                            count, total, f"{count}/{total} facture(s)"
                        )
                        if hasattr(cb, "__await__"):
                            await cb
                    except Exception:
                        pass
            time.sleep(1)

        logger.info("Qobuz: %s facture(s) téléchargée(s)", count)
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
