"""
Provider Orange (Espace client — espace-client.orange.fr).
Téléchargement des factures depuis Historique des factures.
Mode manuel : le navigateur s'ouvre sur l'URL configurée, l'utilisateur se connecte,
le provider détecte la connexion et télécharge les PDFs visibles.
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

PROVIDER_ORANGE = "orange"

ORANGE_BASE_URL = "https://espace-client.orange.fr"
# URL par défaut si non configurée (sans numéro de contrat)
ORANGE_INVOICES_DEFAULT_URL = "https://espace-client.orange.fr/facture-paiement"


class OrangeProvider:
    """
    Fournisseur Orange (Espace client orange.fr).
    Mode manuel : ouvre le navigateur sur la page historique des factures
    et attend que l'utilisateur se connecte.
    """

    PROVIDER_ID = PROVIDER_ORANGE

    def __init__(
        self,
        login: str,
        download_path: Union[str, Path],
        invoices_url: str = ORANGE_INVOICES_DEFAULT_URL,
        headless: bool = False,
        timeout: int = 30,
        browser: str = "chrome",
        firefox_profile_path: Optional[str] = None,
        chrome_user_data_dir: Optional[str] = None,
        keep_browser_open: bool = False,
    ) -> None:
        self._login = login
        self.invoices_url = invoices_url
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
            parent = raw_path.parent
            profile_name = raw_path.name
            known_profile_names = {"default", "profile 1", "profile 2", "profile 3", "profile 4", "profile 5"}
            if profile_name.lower() in known_profile_names and (parent / "Local State").exists():
                opts.add_argument(f"--user-data-dir={parent}")
                opts.add_argument(f"--profile-directory={profile_name}")
                profile_path = str(raw_path)
            else:
                profile_path = str(raw_path)
                opts.add_argument(f"--user-data-dir={profile_path}")
        logger.info("Orange: lancement Chrome (profil: %s)", profile_path or "non (temporaire)")

        raw_driver_path = ChromeDriverManager().install()
        driver_path = Path(raw_driver_path)
        if not driver_path.name.lower().endswith(".exe") or "third_party_notices" in driver_path.name.lower():
            candidate = driver_path.with_name("chromedriver.exe")
            if candidate.exists():
                driver_path = candidate
        service = ChromeService(str(driver_path))
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(60)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        # Forcer le répertoire de téléchargement via CDP (override les prefs du profil existant)
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(self.download_path.absolute()),
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

    def _is_logged_in(self) -> bool:
        if not self.driver:
            return False
        try:
            url = (self.driver.current_url or "").lower()
        except Exception:
            return False
        if "orange.fr" not in url:
            return False
        # Pages de login Orange : /auth/, /oauth/, /espace-client/login
        login_patterns = ["/auth/", "/oauth/", "/login", "/connexion", "signin", "sso.orange"]
        if any(p in url for p in login_patterns):
            return False
        try:
            body = self.driver.page_source.lower()
            # Formulaire de connexion visible = pas connecté
            pwd_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                return False
            # Indicateurs de session active Orange
            if any(x in body for x in ["déconnexion", "se déconnecter", "mon compte", "historique"]):
                return True
            # URL espace client sans login
            if "espace-client.orange.fr" in url and not any(p in url for p in login_patterns):
                if "facture" in url or "historique" in url or "paiement" in url:
                    return True
        except Exception:
            pass
        return False

    def _parse_invoice_date(self, text: str) -> Optional[date_type]:
        if not text:
            return None
        text_lower = text.lower()
        # DD/MM/YYYY ou DD-MM-YYYY
        match = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b", text)
        if match:
            try:
                d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                    return date_type(y, m, d)
            except (ValueError, TypeError):
                pass
        # Mois français
        mois_fr = {
            "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
            "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
            "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
        }
        for mois_name, mois_num in mois_fr.items():
            # "23 février 2026" (jour + mois + année)
            match = re.search(rf"(\d{{1,2}})\s+{re.escape(mois_name)}\s+(\d{{4}})", text_lower)
            if match:
                try:
                    d, y = int(match.group(1)), int(match.group(2))
                    if 2000 <= y <= 2100 and 1 <= d <= 31:
                        return date_type(y, mois_num, d)
                except (ValueError, TypeError):
                    pass
            # "février 2026" (mois + année seulement)
            match = re.search(rf"{re.escape(mois_name)}\s+(\d{{4}})", text_lower)
            if match:
                try:
                    y = int(match.group(1))
                    if 2000 <= y <= 2100:
                        return date_type(y, mois_num, 1)
                except (ValueError, TypeError):
                    pass
        # YYYY-MM ou YYYY/MM
        match = re.search(r"(\d{4})[-/](\d{1,2})", text)
        if match:
            try:
                y, m = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        return None

    async def login(self, otp_code: Optional[str] = None) -> bool:
        try:
            if not self.driver:
                logger.info("Orange: ouverture du navigateur...")
                try:
                    self.driver = self._setup_driver(use_profile=True)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "already in use" in err_msg or "user data directory" in err_msg or "profile" in err_msg:
                        logger.warning("Orange: profil Chrome verrouillé (%s). Relance sans profil.", e)
                        self.driver = self._setup_driver(use_profile=False)
                    else:
                        raise
                logger.info("Orange: navigateur ouvert.")

            # Naviguer vers la page des factures
            try:
                self.driver.get(self.invoices_url)
            except Exception as e:
                logger.warning("Orange: chargement %s interrompu (%s)", self.invoices_url[:80], e)

            logger.info("Orange: en attente de connexion manuelle sur %s", self.invoices_url[:80])
            logger.info("Orange: connectez-vous dans le navigateur (5 minutes max).")

            max_wait = 300  # 5 minutes
            interval = 5
            elapsed = 0
            while elapsed < max_wait:
                time.sleep(interval)
                elapsed += interval
                if self._is_logged_in():
                    logger.info("Orange: connexion détectée (URL: %s)", self.driver.current_url[:80])
                    return True
                logger.info("Orange: attente connexion... (%ds/%ds)", elapsed, max_wait)

            logger.warning("Orange: timeout — connexion non détectée après %ds", max_wait)
            return False
        except Exception as e:
            logger.error("Orange login: %s", e, exc_info=True)
            return False

    async def navigate_to_invoices(self) -> bool:
        if not self.driver or not self._is_logged_in():
            return False
        url = (self.driver.current_url or "").lower()
        # Déjà sur la page historique
        if "historique" in url:
            logger.info("Orange: déjà sur la page des factures (%s)", self.driver.current_url[:80])
            return True
        # Naviguer vers l'URL configurée
        try:
            self.driver.get(self.invoices_url)
            time.sleep(3)
            if self._is_logged_in():
                logger.info("Orange: page factures chargée (%s)", self.driver.current_url[:80])
                return True
        except Exception as e:
            logger.warning("Orange: navigate_to_invoices: %s", e)
        return False

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Liste les liens de téléchargement de factures visibles sur la page courante."""
        from urllib.parse import urljoin

        out: List[OrderInfo] = []
        if not self.driver:
            return out
        try:
            base_url = self.driver.current_url
            logger.info("Orange: analyse de %s", base_url[:100])
            all_links = self.driver.find_elements(By.TAG_NAME, "a")
            logger.info("Orange: %d liens <a> trouvés", len(all_links))

            for idx, a in enumerate(all_links):
                try:
                    href = (a.get_attribute("href") or "").strip()
                    text = (a.text or "").strip()
                    text_lower = text.lower()

                    # Liens sans URL (href vide) : téléchargement via clic JavaScript
                    # Ex: "Voir la facture du 23 février 2026 au format PDF"
                    if not href or href == "#" or href.startswith("javascript:"):
                        if "facture" in text_lower and ("pdf" in text_lower or "format" in text_lower):
                            inv_date = self._parse_invoice_date(text)
                            date_str = inv_date.isoformat() if inv_date else f"idx{idx}"
                            order_id = date_str
                            logger.info("Orange: lien clic trouvé: %s | date=%s", text[:80], inv_date)
                            # raw_element stocke le texte du lien pour le retrouver plus tard
                            out.append(OrderInfo(order_id=order_id, invoice_url=None, invoice_date=inv_date, raw_element=text))
                        continue

                    # Liens avec URL directe vers un PDF
                    href_lower = href.lower()
                    if ".pdf" in href_lower or "telecharger" in href_lower or "download" in href_lower:
                        full = urljoin(base_url, href) if not href.startswith("http") else href
                        inv_date = self._parse_invoice_date(text)
                        order_id = f"orange_url_{idx}_{hash(full) % 100000}"
                        logger.info("Orange: lien URL directe: %s | date=%s", full[:80], inv_date)
                        out.append(OrderInfo(order_id=order_id, invoice_url=full, invoice_date=inv_date))
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Orange list_orders_or_invoices: %s", e)
        logger.info("Orange: %d lien(s) facture trouvé(s)", len(out))
        return out

    def _wait_for_browser_download(self, existing_pdfs: set, max_wait: int = 30) -> Optional[Path]:
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

    def _get_browser_session(self) -> Any:
        import requests
        session = requests.Session()
        for c in self.driver.get_cookies():
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        session.headers["User-Agent"] = self.driver.execute_script("return navigator.userAgent;")
        return session

    def _rename_browser_download(self, path: Path, order_id: str, invoice_date: Optional[date_type] = None) -> str:
        if invoice_date:
            new_name = f"orange_{invoice_date.isoformat()}.pdf"
        else:
            short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
            new_name = f"orange_{short_id}.pdf"
        new_name = re.sub(r"[^\w\-.]", "_", new_name)[:80]
        new_path = path.parent / new_name
        if path.name != new_name:
            try:
                path.rename(new_path)
            except Exception as e:
                logger.warning("Orange: impossible de renommer %s -> %s : %s", path.name, new_name, e)
                return path.name
        return new_name

    def _click_download_button_and_wait(self, existing_pdfs: set, wait_secs: int = 8) -> Optional[Path]:
        """Sur la page afficher-la-facture, clique sur 'Télécharger le PDF' et attend le fichier."""
        if not self.driver:
            return None
        time.sleep(wait_secs)
        # Chercher un bouton ou lien contenant "Télécharger" (bouton rouge en haut à droite)
        download_keywords = ["télécharger", "telecharger", "download"]
        target = None
        for selector in ["button", "a"]:
            for el in self.driver.find_elements(By.TAG_NAME, selector):  # type: ignore[union-attr]
                try:
                    text = (el.text or "").strip().lower()
                    if any(k in text for k in download_keywords) and el.is_displayed():
                        target = el
                        logger.info("Orange: bouton téléchargement trouvé: '%s'", el.text.strip()[:60])
                        break
                except Exception:
                    continue
            if target:
                break
        if not target:
            logger.warning("Orange: bouton 'Télécharger le PDF' introuvable sur la page")
            return None
        try:
            target.click()
            logger.info("Orange: clic sur 'Télécharger le PDF'")
            return self._wait_for_browser_download(existing_pdfs, max_wait=30)
        except Exception as e:
            logger.warning("Orange: clic bouton téléchargement: %s", e)
            return None

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
                name = f"orange_{invoice_date.isoformat()}.pdf"
            else:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"orange_{short_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("Orange download %s: %s", url[:60], e)
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
        if not force_redownload and self.registry.is_downloaded(PROVIDER_ORANGE, oid):
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
            self.registry.add(PROVIDER_ORANGE, oid, filename, invoice_date=invoice_date.isoformat() if invoice_date else None)
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
            raise Exception("Échec de la connexion à l'espace Orange")
        if not await self.navigate_to_invoices():
            logger.warning("Orange: navigate_to_invoices a échoué, tentative sur la page actuelle.")

        orders = self.list_orders_or_invoices()
        if not orders:
            logger.warning("Orange: aucune facture trouvée sur %s", self.driver.current_url[:80])  # type: ignore[union-attr]
            return {"count": 0, "files": []}

        # Filtre par date si demandé
        if any([year, month, months, date_start, date_end]):
            from datetime import datetime
            filtered: List[OrderInfo] = []
            for o in orders:
                if date_start and date_end:
                    try:
                        s = datetime.strptime(date_start, "%Y-%m-%d").date()
                        e = datetime.strptime(date_end, "%Y-%m-%d").date()
                        if o.invoice_date and s <= o.invoice_date <= e:
                            filtered.append(o)
                    except ValueError:
                        filtered.append(o)
                    continue
                if o.invoice_date:
                    if year and o.invoice_date.year != year:
                        continue
                    if month and o.invoice_date.month != month:
                        continue
                    if months and o.invoice_date.month not in months:
                        continue
                filtered.append(o)
            orders = filtered

        orders = orders[:max_invoices]
        total = len(orders)
        files: List[str] = []
        count = 0
        # Mémoriser l'URL de la page historique pour y revenir après chaque clic
        historique_url = self.driver.current_url  # type: ignore[union-attr]

        for i, order in enumerate(orders):
            if count >= max_invoices:
                break
            await self._notify_progress(on_progress, count, total, f"Téléchargement {i + 1}/{total}…")

            if not force_redownload and self.registry.is_downloaded(PROVIDER_ORANGE, order.order_id):
                logger.info("Orange: %s déjà téléchargé, ignoré", order.order_id)
                continue

            filename: Optional[str] = None
            existing_pdfs = set(self.download_path.glob("*.pdf"))

            if not order.invoice_url:
                # Téléchargement par clic (lien JavaScript sans href)
                link_text = order.raw_element
                logger.info("Orange: clic sur '%s'", (link_text or "")[:80])
                try:
                    # Revenir sur historique si nécessaire (attente suffisante pour le chargement)
                    if self.driver.current_url != historique_url:  # type: ignore[union-attr]
                        logger.info("Orange: retour sur historique avant clic")
                        self.driver.get(historique_url)  # type: ignore[union-attr]
                        time.sleep(4)

                    links = self.driver.find_elements(By.TAG_NAME, "a")  # type: ignore[union-attr]
                    target = None
                    for link in links:
                        if (link.text or "").strip() == link_text:
                            target = link
                            break

                    if target:
                        url_before = self.driver.current_url  # type: ignore[union-attr]
                        existing_handles = set(self.driver.window_handles)  # type: ignore[union-attr]
                        target.click()
                        time.sleep(2)

                        # Cas 1 : nouvel onglet ouvert par le clic
                        new_handles = set(self.driver.window_handles) - existing_handles  # type: ignore[union-attr]
                        pdf_url: Optional[str] = None
                        in_new_tab = False
                        if new_handles:
                            h = list(new_handles)[0]
                            self.driver.switch_to.window(h)  # type: ignore[union-attr]
                            time.sleep(1)
                            tab_url = self.driver.current_url  # type: ignore[union-attr]
                            if tab_url and "about:" not in tab_url.lower():
                                pdf_url = tab_url
                                logger.info("Orange: URL dans nouvel onglet: %s", tab_url[:80])
                            in_new_tab = True
                        else:
                            # Cas 2 : navigation dans l'onglet courant
                            url_after = self.driver.current_url  # type: ignore[union-attr]
                            if url_after != url_before:
                                pdf_url = url_after
                                logger.info("Orange: navigation vers %s", url_after[:80])

                        # Télécharger via l'URL capturée
                        if pdf_url:
                            if ".pdf" in pdf_url.lower():
                                # URL directe vers un PDF
                                filename = self._download_pdf(pdf_url, order.order_id, order.invoice_date)
                                if filename:
                                    logger.info("Orange: facture via URL directe: %s", filename)
                            else:
                                # Page intermédiaire (ex: afficher-la-facture) : cliquer sur le bouton de téléchargement
                                downloaded_path = self._click_download_button_and_wait(existing_pdfs, wait_secs=8)
                                if downloaded_path:
                                    filename = self._rename_browser_download(
                                        downloaded_path, order.order_id, order.invoice_date
                                    )
                                    logger.info("Orange: facture via bouton téléchargement: %s", filename)

                        # Fallback : attendre un téléchargement navigateur déjà en cours
                        if not filename:
                            downloaded_path = self._wait_for_browser_download(existing_pdfs, max_wait=10)
                            if downloaded_path:
                                filename = self._rename_browser_download(
                                    downloaded_path, order.order_id, order.invoice_date
                                )
                                logger.info("Orange: facture via browser download: %s", filename)
                            else:
                                logger.warning(
                                    "Orange: aucun PDF après clic sur '%s'", (link_text or "")[:60]
                                )

                        # Fermer le nouvel onglet si ouvert
                        if in_new_tab:
                            try:
                                self.driver.close()  # type: ignore[union-attr]
                                self.driver.switch_to.window(  # type: ignore[union-attr]
                                    list(self.driver.window_handles)[0]  # type: ignore[union-attr]
                                )
                            except Exception:
                                pass

                        # Revenir sur historique pour le prochain clic
                        if self.driver.current_url != historique_url:  # type: ignore[union-attr]
                            try:
                                self.driver.get(historique_url)  # type: ignore[union-attr]
                                time.sleep(3)
                            except Exception:
                                pass
                    else:
                        logger.warning("Orange: lien introuvable pour '%s'", (link_text or "")[:60])
                except Exception as e:
                    logger.warning("Orange: clic download: %s", e)
                    # Tentative de retour sur historique en cas d'erreur
                    try:
                        if self.driver.current_url != historique_url:  # type: ignore[union-attr]
                            self.driver.get(historique_url)  # type: ignore[union-attr]
                            time.sleep(3)
                    except Exception:
                        pass
            else:
                url = order.invoice_url
                filename = self._download_pdf(url, order.order_id, order.invoice_date)
                if not filename:
                    logger.info("Orange: fallback navigateur pour %s", url[:80])
                    try:
                        self.driver.get(url)  # type: ignore[union-attr]
                        downloaded_path = self._wait_for_browser_download(existing_pdfs, max_wait=30)
                        if downloaded_path:
                            filename = self._rename_browser_download(downloaded_path, order.order_id, order.invoice_date)
                            logger.info("Orange: facture via browser download: %s", filename)
                    except Exception as e:
                        logger.warning("Orange: browser download fallback: %s", e)

            if filename:
                self.registry.add(
                    PROVIDER_ORANGE, order.order_id, filename,
                    invoice_date=order.invoice_date.isoformat() if order.invoice_date else None,
                )
                files.append(filename)
                count += 1
                await self._notify_progress(on_progress, count, total, f"{count}/{total} facture(s) téléchargée(s)")
                logger.info("Orange: facture téléchargée: %s", filename)
            else:
                logger.warning("Orange: échec téléchargement facture %s", order.order_id)

            time.sleep(1)

        logger.info("Orange: %d facture(s) téléchargée(s) au total", count)
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
