"""
Provider Free Mobile (Espace abonné mobile — mobile.free.fr).
Téléchargement des factures depuis l'espace client Free Mobile.
Connexion : https://mobile.free.fr/account/v2/login
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

PROVIDER_FREE_MOBILE = "free_mobile"

# Mois FR pour le parsing des titres de facture
_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

FREE_MOBILE_BASE_URL = "https://mobile.free.fr"
FREE_MOBILE_LOGIN_URL = "https://mobile.free.fr/account/v2/login"
# Chemins possibles vers les factures après connexion
FREE_MOBILE_FACTURATION_PATHS = [
    "/account/v2/factures",
    "/account/factures",
    "/account/v2/",
    "/account/",
    "/",
]


class FreeMobileProvider:
    """
    Fournisseur Free Mobile (Espace abonné mobile — mobile.free.fr).
    Implémente InvoiceProviderProtocol.
    """

    PROVIDER_ID = PROVIDER_FREE_MOBILE

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
        if "mobile.free.fr" not in url:
            return False
        try:
            body = self.driver.page_source.lower()
            if "se connecter" in body or "connexion" in body:
                pwd_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if pwd_fields and any(f.is_displayed() for f in pwd_fields):
                    return False
        except Exception:
            pass
        return True

    async def login(self, otp_code: Optional[str] = None) -> bool:
        try:
            if not self.driver:
                self.driver = self._setup_driver()
            if self._is_logged_in():
                logger.info("Free Mobile: déjà connecté")
                return True

            self.driver.get(FREE_MOBILE_LOGIN_URL)
            time.sleep(3)

            login_selectors = [
                "input[name='login']",
                "input[name='identifiant']",
                "input[id='login']",
                "input[id='identifiant']",
                "input[placeholder*='dentifiant']",
                "input[placeholder*='mail']",
                "input[placeholder*='téléphone']",
                "input[autocomplete='username']",
                "input[type='text']:not([type='search'])",
                "input[type='email']",
            ]
            password_selectors = [
                "input[name='pass']",
                "input[name='password']",
                "input[id='pass']",
                "input[id='password']",
                "input[placeholder*='mot de passe']",
                "input[autocomplete='current-password']",
                "input[type='password']",
            ]

            login_input = None
            pass_input = None
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
            if not pass_input:
                try:
                    pass_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                except NoSuchElementException:
                    pass

            if not login_input or not pass_input:
                logger.error("Free Mobile: champs identifiant / mot de passe non trouvés sur %s", FREE_MOBILE_LOGIN_URL)
                return False

            login_input.clear()
            login_input.send_keys(self._login)
            pass_input.clear()
            pass_input.send_keys(self._password)

            submit = None
            for sel in [
                "button[type='submit']",
                "input[type='submit']",
                "button:contains('Se connecter')",
                "[type='submit']",
            ]:
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
                try:
                    submit = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
                except NoSuchElementException:
                    pass
            if submit:
                submit.click()
            else:
                logger.error("Free Mobile: bouton de connexion non trouvé")
                return False
            time.sleep(4)

            if not self._is_logged_in():
                logger.warning("Free Mobile: connexion peut avoir échoué (vérifier identifiants)")
                return False
            logger.info("Free Mobile: connexion réussie")
            return True
        except Exception as e:
            err_msg = str(e).lower()
            if "dns" in err_msg or "neterror" in err_msg or "could not reach" in err_msg or "offline" in err_msg or "impossible de se connecter" in err_msg:
                logger.error(
                    "Free Mobile: problème réseau ou DNS (impossible de joindre mobile.free.fr). "
                    "Vérifiez votre connexion internet, VPN, pare-feu, ou réessayez plus tard."
                )
                raise Exception(
                    "Impossible de joindre mobile.free.fr (réseau ou DNS). "
                    "Vérifiez votre connexion internet et que https://mobile.free.fr s’ouvre dans un navigateur."
                ) from e
            logger.error("Free Mobile login: %s", e)
            return False

    def _expand_mes_lignes_if_needed(self) -> bool:
        """Ouvre la section « MES LIGNES » en cliquant sur son en-tête, puis attend que les lignes soient visibles."""
        if not self.driver:
            return False
        try:
            # Cibler l'en-tête cliquable (petit bloc "MES LIGNES" / "Mes lignes"), pas le conteneur entier
            for xpath in [
                "//button[contains(., 'MES LIGNES') or contains(., 'Mes lignes')]",
                "//*[@role='button'][contains(., 'MES LIGNES') or contains(., 'Mes lignes')]",
                "//a[contains(., 'MES LIGNES') or contains(., 'Mes lignes')]",
                "//*[contains(., 'MES LIGNES') and string-length(normalize-space(.)) < 80]",
            ]:
                try:
                    els = self.driver.find_elements(By.XPATH, xpath)
                    for el in els:
                        if not el.is_displayed():
                            continue
                        try:
                            el.click()
                            time.sleep(2)
                            # Attendre que des liens de lignes (06/07) apparaissent en dessous
                            WebDriverWait(self.driver, 10).until(
                                lambda d: len([
                                    e for e in d.find_elements(By.XPATH, "//*[contains(., '06') or contains(., '07')]")
                                    if e.is_displayed() and 10 < len((e.text or "").strip()) < 80
                                    and re.search(r"0[1-9][\s]?\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}", (e.text or ""))
                                ]) >= 2
                            )
                            logger.info("Free Mobile: section MES LIGNES dépliée, lignes visibles")
                            return True
                        except TimeoutException:
                            pass
                        except Exception:
                            continue
                except Exception:
                    continue
            # Fallback : un seul clic sur un élément contenant MES LIGNES puis attente
            for el in self.driver.find_elements(By.XPATH, "//*[contains(., 'MES LIGNES')]"):
                if not el.is_displayed():
                    continue
                text = (el.text or "").strip()
                if len(text) > 200:
                    continue
                try:
                    el.click()
                    time.sleep(3)
                    break
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.debug("Free Mobile expand Mes lignes: %s", e)
            return False

    def _get_line_entries(self) -> List[Any]:
        """Retourne un élément cliquable par ligne (principale + secondaires), dédupliqué par numéro."""
        if not self.driver:
            return []
        entries: List[Any] = []
        seen_phones: set[str] = set()
        phone_re = re.compile(r"0[1-9][\s]?\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}")
        try:
            # 1) Chercher dans un bloc contenant "MES LIGNES" ou "LIGNE PRINCIPALE" : tout lien/bouton avec un numéro 06/07
            for xpath in [
                "//*[contains(., 'MES LIGNES') or contains(., 'LIGNE PRINCIPALE') or contains(., 'LIGNES SECONDAIRES')]//a[contains(., '06') or contains(., '07')]",
                "//*[contains(., 'MES LIGNES')]//*[self::a or self::button or @role='button'][contains(., '06') or contains(., '07')]",
            ]:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    try:
                        if not el.is_displayed():
                            continue
                        text = (el.text or "").strip()
                        if not text or len(text) > 120:
                            continue
                        if not phone_re.search(text):
                            continue
                        match = phone_re.search(text)
                        phone = re.sub(r"\D", "", match.group(0))[:10] if match else ""
                        if phone and phone not in seen_phones:
                            seen_phones.add(phone)
                            entries.append(el)
                    except Exception:
                        continue
                if entries:
                    break
            # 2) Fallback : tous les liens de la page avec un numéro 06/07 et href compte/ligne (ou relatif)
            if not entries:
                for el in self.driver.find_elements(By.TAG_NAME, "a"):
                    try:
                        if not el.is_displayed():
                            continue
                        text = (el.text or "").strip()
                        if not phone_re.search(text) or len(text) >= 80:
                            continue
                        href = (el.get_attribute("href") or "")
                        if href.startswith("http") and "mobile.free.fr" not in href and "free.fr" not in href:
                            continue
                        match = phone_re.search(text)
                        phone = re.sub(r"\D", "", match.group(0))[:10] if match else ""
                        if phone and phone not in seen_phones:
                            seen_phones.add(phone)
                            entries.append(el)
                    except Exception:
                        continue
            # 3) Fallback : liens avec account/ligne dans l'URL
            if not entries:
                for el in self.driver.find_elements(By.CSS_SELECTOR, "a[href*='account'], a[href*='ligne'], a[href*='line']"):
                    try:
                        if not el.is_displayed():
                            continue
                        text = (el.text or "").strip()
                        if phone_re.search(text):
                            match = phone_re.search(text)
                            phone = re.sub(r"\D", "", match.group(0))[:10] if match else ""
                            if not phone or phone in seen_phones:
                                continue
                            seen_phones.add(phone)
                            entries.append(el)
                    except Exception:
                        continue
            if not entries:
                for el in self.driver.find_elements(By.XPATH, "//a[contains(@href, 'account') or contains(@href, 'line')]"):
                    try:
                        if not el.is_displayed():
                            continue
                        text = (el.text or "").strip()
                        if phone_re.search(text) or "06 " in text or "07 " in text:
                            match = phone_re.search(text)
                            phone = re.sub(r"\D", "", match.group(0))[:10] if match else str(hash(el))[:10]
                            if phone not in seen_phones:
                                seen_phones.add(phone)
                                entries.append(el)
                    except Exception:
                        continue
            logger.info("Free Mobile: %s ligne(s) trouvée(s) (MES LIGNES)", len(entries))
        except Exception as e:
            logger.warning("Free Mobile get line entries: %s", e)
        return entries

    def _save_debug_page(self, prefix: str = "free_mobile_debug") -> None:
        """Sauvegarde le HTML de la page courante dans logs/ pour diagnostic."""
        if not self.driver:
            return
        try:
            log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            path = log_dir / f"{prefix}.html"
            path.write_text(self.driver.page_source, encoding="utf-8", errors="replace")
            logger.info("Free Mobile: page sauvegardée %s", path)
        except Exception as e:
            logger.debug("Free Mobile save debug page: %s", e)

    def _click_conso_et_factures_if_present(self) -> None:
        """Ouvre le bloc « Conso et factures » dans le menu si présent."""
        if not self.driver:
            return
        try:
            try:
                link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Conso et factures")
                if link.is_displayed():
                    link.click()
                    time.sleep(2)
            except NoSuchElementException:
                pass
        except Exception:
            pass

    def _click_mes_factures_tab(self) -> bool:
        """Clique sur l'onglet « Mes factures » et attend que la liste des factures soit visible."""
        if not self.driver:
            return False
        try:
            self._click_conso_et_factures_if_present()
            time.sleep(1)
            # Cliquer sur l'onglet "Mes factures" (élément dont le texte est exactement ça)
            clicked = False
            for xpath in [
                "//*[normalize-space()='Mes factures']",
                "//button[contains(., 'Mes factures')]",
                "//span[contains(., 'Mes factures')]",
                "//a[contains(., 'Mes factures')]",
                "//div[contains(., 'Mes factures')]",
            ]:
                try:
                    for el in self.driver.find_elements(By.XPATH, xpath):
                        if not el.is_displayed():
                            continue
                        t = (el.text or "").strip()
                        if t == "Mes factures" or (t.startswith("Mes factures") and "Ma consommation" not in t):
                            try:
                                el.click()
                                clicked = True
                                break
                            except Exception:
                                pass
                    if clicked:
                        break
                except Exception:
                    continue
            if not clicked:
                try:
                    link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Mes factures")
                    if link.is_displayed() and "Ma consommation" not in (link.text or ""):
                        link.click()
                        clicked = True
                except NoSuchElementException:
                    pass
            if not clicked:
                logger.warning("Free Mobile: onglet Mes factures non trouvé")
                return False
            # Attendre que le contenu "Mes factures" soit chargé (lien de téléchargement facture/PDF)
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//a[contains(@href, 'pdf') or contains(@href, 'facture') or contains(@href, 'document')]")
                    )
                )
            except TimeoutException:
                logger.warning("Free Mobile: timeout en attendant la liste des factures après clic onglet")
            time.sleep(2)
            logger.info("Free Mobile: onglet Mes factures ouvert")
            return True
        except Exception as e:
            logger.warning("Free Mobile click Mes factures tab: %s", e)
            return False

    async def navigate_to_invoices(self) -> bool:
        if not self.driver:
            return False
        if self._is_logged_in() and "mobile.free.fr" in self.driver.current_url:
            # Sur la page compte : toujours ouvrir l’onglet « Mes factures » avant de lister
            if "/account" in self.driver.current_url:
                if not self._click_mes_factures_tab():
                    logger.warning("Free Mobile: impossible d'ouvrir l'onglet Mes factures")
                time.sleep(2)
                already = self.list_orders_or_invoices()
                if already:
                    logger.info("Free Mobile: %s facture(s) sur la page Mes factures", len(already))
                    return True
        for path in FREE_MOBILE_FACTURATION_PATHS:
            url = FREE_MOBILE_BASE_URL.rstrip("/") + path
            self.driver.get(url)
            time.sleep(3)
            if self._is_logged_in():
                already = self.list_orders_or_invoices()
                if not already and "/account" in self.driver.current_url:
                    self._click_mes_factures_tab()
                    already = self.list_orders_or_invoices()
                if already:
                    return True
                try:
                    for link in self.driver.find_elements(By.TAG_NAME, "a"):
                        href = (link.get_attribute("href") or "").lower()
                        text = (link.text or "").lower()
                        if "factur" in text or "factur" in href or "pdf" in href:
                            link.click()
                            time.sleep(3)
                            if self.list_orders_or_invoices():
                                return True
                except Exception:
                    pass
        return self._is_logged_in()

    def list_orders_or_invoices_from_all_lines(self) -> List[OrderInfo]:
        """
        Parcourt les lignes rattachées (MES LIGNES : principale + secondaires),
        ouvre chaque ligne, affiche « Mes factures », et agrège tous les liens de factures.
        """
        from urllib.parse import urljoin
        if not self.driver or not self._is_logged_in():
            return []
        # S’assurer d’être sur la page compte
        if "mobile.free.fr/account" not in self.driver.current_url:
            self.driver.get(FREE_MOBILE_BASE_URL.rstrip("/") + "/account/v2")
            time.sleep(4)
        # Attendre que la sidebar soit rendue (bloc MES LIGNES ou lien avec numéro)
        try:
            WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(., 'MES LIGNES') or contains(., 'LIGNE PRINCIPALE')]"))
            )
        except TimeoutException:
            pass
        self._expand_mes_lignes_if_needed()
        time.sleep(2)
        line_entries = self._get_line_entries()
        if not line_entries:
            logger.warning("Free Mobile: 0 ligne trouvée dans MES LIGNES (page: %s)", self.driver.current_url[:80])
        else:
            logger.info("Free Mobile: parcours de %s ligne(s) rattachée(s) (MES LIGNES)", len(line_entries))
        seen_hrefs: set[str] = set()
        all_orders: List[OrderInfo] = []
        num_lines = len(line_entries)
        for idx in range(num_lines):
            try:
                # Re-récupérer les entrées à chaque tour (éviter stale après driver.back())
                self._expand_mes_lignes_if_needed()
                time.sleep(1)
                current_entries = self._get_line_entries()
                if idx >= len(current_entries):
                    logger.warning("Free Mobile: entrée ligne %s introuvable (total %s)", idx, len(current_entries))
                    continue
                line_el = current_entries[idx]
                line_el.click()
                time.sleep(3)
                self._click_mes_factures_tab()
                time.sleep(2)
                base_url = self.driver.current_url
                for o in self.list_orders_or_invoices():
                    href = (o.invoice_url or "").strip()
                    if not href:
                        continue
                    if not href.startswith("http") and base_url:
                        href = urljoin(base_url, href)
                    norm = self._normalize_invoice_url(href)
                    if not norm or norm in seen_hrefs:
                        continue
                    seen_hrefs.add(norm)
                    order_id = f"free_mobile_inv_{idx}_{hash(norm) % 100000}"
                    all_orders.append(OrderInfo(order_id=order_id, invoice_url=href, invoice_date=o.invoice_date, raw_element=o.raw_element))
                self.driver.back()
                time.sleep(2)
            except Exception as e:
                logger.warning("Free Mobile ligne %s: %s", idx, e)
                try:
                    self.driver.back()
                    time.sleep(2)
                except Exception:
                    pass
        return all_orders

    def _parse_invoice_date_from_title(self, title: str) -> Optional[date_type]:
        if not title:
            return None
        title_lower = title.lower()
        for mois_name, mois_num in _MOIS_FR.items():
            match = re.search(rf"{re.escape(mois_name)}\s+(\d{{4}})", title_lower)
            if match:
                try:
                    year = int(match.group(1))
                    if 2000 <= year <= 2100:
                        return date_type(year, mois_num, 1)
                except (ValueError, TypeError):
                    pass
        match = re.search(r"(\d{4})[-/](\d{1,2})", title)
        if match:
            try:
                y, m = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        # MM/AAAA ou JJ/MM/AAAA
        match = re.search(r"(\d{1,2})/(\d{4})", title)
        if match:
            try:
                m, y = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        return None

    def _parse_invoice_date_from_url(self, href: str) -> Optional[date_type]:
        """Extrait une date depuis l'URL (ex. .../2026/02/..., ...?year=2026&month=2)."""
        if not href:
            return None
        # /2026/02/ ou /2026-02/ ou /facture_2026_02.pdf
        match = re.search(r"[/_\-](\d{4})[/_\-](\d{1,2})(?:[/_\-]|\.)", href)
        if match:
            try:
                y, m = int(match.group(1)), int(match.group(2))
                if 2000 <= y <= 2100 and 1 <= m <= 12:
                    return date_type(y, m, 1)
            except (ValueError, TypeError):
                pass
        match = re.search(r"[?&]year=(\d{4})", href, re.I)
        if match:
            try:
                year = int(match.group(1))
                if 2000 <= year <= 2100:
                    month_match = re.search(r"[?&]month=(\d{1,2})", href, re.I)
                    month = int(month_match.group(1)) if month_match and 1 <= int(month_match.group(1)) <= 12 else 1
                    return date_type(year, month, 1)
            except (ValueError, TypeError):
                pass
        return None

    def _invoice_date_from_title_and_url(self, title: str, href: str) -> Optional[date_type]:
        """Retourne la date de facture depuis le titre du lien, sinon depuis l'URL."""
        return self._parse_invoice_date_from_title(title or "") or self._parse_invoice_date_from_url(href or "")

    def _normalize_invoice_url(self, url: str) -> str:
        """URL canonique pour déduplication (même facture avec paramètres différents)."""
        from urllib.parse import urlparse, urlunparse
        if not url:
            return ""
        p = urlparse(url)
        path = (p.path or "").rstrip("/")
        # Pour les PDF/factures, considérer même path = même document
        if ".pdf" in path.lower() or "facture" in path.lower() or "document" in path.lower():
            return (p.scheme or "https") + "://" + (p.netloc or "") + path
        return url.split("#")[0].split("?")[0]

    def _get_date_from_context(self, el: Any) -> Optional[date_type]:
        """Extrait une date du texte du lien et de son parent (ex. ligne de tableau)."""
        try:
            text_parts = [(el.text or "").strip(), (el.get_attribute("title") or "").strip()]
            parent = el
            for _ in range(3):
                try:
                    parent = parent.find_element(By.XPATH, "..")
                    if parent:
                        text_parts.append((parent.text or "").strip()[:200])
                except Exception:
                    break
            combined = " ".join(text_parts)
            return self._parse_invoice_date_from_title(combined) or self._parse_invoice_date_from_url(
                (el.get_attribute("href") or "")
            )
        except Exception:
            return None

    def _is_invoice_download_link(self, el: Any, href: str, text: str, title: str) -> bool:
        """
        Vrai pour un lien de téléchargement de facture (pas récapitulatif, pas tarifs).
        Le libellé doit contenir "facture" ou "invoice".
        """
        label = f"{text} {title}".lower()
        href_lower = (href or "").lower()
        # Exclure récapitulatifs
        if "récapitulatif" in label or "recapitulatif" in label:
            return False
        if "récapitulatif" in href_lower or "recapitulatif" in href_lower:
            return False
        if re.search(r"\brecap\b", label):
            return False
        # Exclure tarifs (documents de grille tarifaire)
        if "tarif" in label or "tarif" in href_lower:
            return False
        if not href or href == "#" or "logout" in href_lower or "deconnexion" in href_lower:
            return False
        if text.strip() in ("mes factures", "ma consommation", "conso et factures"):
            return False
        # Le libellé doit indiquer une facture
        if "facture" not in label and "invoice" not in label:
            return False
        # L'URL doit pointer vers un document (PDF, facture, etc.)
        href_ok = ".pdf" in href_lower or "facture" in href_lower or "invoice" in href_lower or "document" in href_lower or "download" in href_lower
        if not href_ok:
            return False
        return True

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Liste uniquement les liens de téléchargement de factures (onglet Mes factures)."""
        from urllib.parse import urljoin
        out: List[OrderInfo] = []
        if not self.driver:
            return out
        try:
            base_url = self.driver.current_url
            seen_hrefs: set[str] = set()
            # Chercher d'abord dans le contenu principal (tabpanel ou main) pour éviter le menu
            root_candidates = []
            try:
                for sel in ["[role='tabpanel']", "main", "[role='main']", ".main-content", "#content", ".content"]:
                    els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in els:
                        if el.is_displayed():
                            root_candidates.append(el)
                            break
            except Exception:
                pass
            roots = root_candidates if root_candidates else [self.driver]

            for root in roots:
                for a in root.find_elements(By.TAG_NAME, "a"):
                    href = (a.get_attribute("href") or "").strip()
                    text = (a.text or "").strip()
                    title = (a.get_attribute("title") or "").strip()
                    if not self._is_invoice_download_link(a, href, text, title):
                        continue
                    full_href = urljoin(base_url, href) if not href.startswith("http") else href
                    norm = self._normalize_invoice_url(full_href)
                    if not norm or norm in seen_hrefs:
                        continue
                    seen_hrefs.add(norm)
                    inv_date = self._invoice_date_from_title_and_url(title or text, full_href)
                    if inv_date is None:
                        inv_date = self._get_date_from_context(a)
                    order_id = f"free_mobile_inv_{len(out)}_{hash(norm) % 100000}"
                    out.append(OrderInfo(order_id=order_id, invoice_url=full_href, invoice_date=inv_date, raw_element=a))
                if out:
                    break
            logger.info("Free Mobile list_orders: %s lien(s) facture trouvé(s) sur %s", len(out), base_url[:60])
        except Exception as e:
            logger.warning("Free Mobile list_orders: %s", e)
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
                logger.warning(
                    "Free Mobile download: URL retourne status %s (attendu 200) → %s",
                    r.status_code, url[:80],
                )
                return None
            ct = r.headers.get("content-type", "").lower()
            is_pdf = "pdf" in ct or (len(r.content) >= 4 and r.content[:4] == b"%PDF")
            if not is_pdf:
                preview = repr(r.content[:50]) if len(r.content) >= 50 else repr(r.content)
                logger.warning(
                    "Free Mobile download: contenu non-PDF (content-type=%s, début=%s) → %s",
                    ct or "(vide)", preview, url[:80],
                )
                return None
            if invoice_date:
                short_id = re.sub(r"[^\w\-]", "_", order_id)[:30]
                name = f"free_mobile_{invoice_date.isoformat()}_{short_id}.pdf"
            else:
                name = f"free_mobile_{order_id}.pdf"
            name = re.sub(r"[^\w\-.]", "_", name)[:80]
            (self.download_path / name).write_bytes(r.content)
            return name
        except Exception as e:
            logger.warning("Free Mobile download %s: %s", url[:60], e)
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
        if not force_redownload and self.registry.is_downloaded(PROVIDER_FREE_MOBILE, oid):
            logger.debug("Free Mobile: facture déjà enregistrée, ignorée: %s", oid)
            return None
        url = None
        if isinstance(order_or_id, OrderInfo) and order_or_id.invoice_url:
            url = order_or_id.invoice_url
        if not url and isinstance(order_or_id, str) and order_or_id.startswith("http"):
            url = order_or_id
        if not url:
            logger.warning("Free Mobile download_invoice: pas d'URL pour order %s", oid)
            return None
        filename = self._download_pdf(url, oid, invoice_date)
        if filename:
            self.registry.add(PROVIDER_FREE_MOBILE, oid, filename, invoice_date=invoice_date.isoformat() if invoice_date else None)
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
            raise Exception("Échec de la connexion à l'espace Free Mobile")
        # D’abord tenter de collecter les factures en parcourant chaque ligne rattachée (MES LIGNES)
        orders = self.list_orders_or_invoices_from_all_lines()
        if orders:
            logger.info("Free Mobile: %s facture(s) collectée(s) via MES LIGNES", len(orders))
        if not orders:
            logger.info("Free Mobile: aucune facture via lignes, essai page compte + onglet Mes factures")
            if not await self.navigate_to_invoices():
                raise Exception("Impossible d'accéder à la page des factures Free Mobile")
            orders = self.list_orders_or_invoices()
        if not orders:
            self._save_debug_page("free_mobile_no_links")
            logger.warning(
                "Free Mobile: 0 facture trouvée. Page sauvegardée dans logs/free_mobile_no_links.html pour diagnostic."
            )
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
                "Free Mobile filtre (year=%s month=%s): %s -> %s facture(s)",
                year, month, len(orders), len(filtered),
            )
        with_date = sum(1 for o in orders if o.invoice_date)
        if not filtered and orders:
            logger.warning(
                "Free Mobile: 0 facture après filtre (%s lien(s), %s avec date reconnue)",
                len(orders), with_date,
            )
            # Si aucune date reconnue, télécharger quand même toutes les factures (sans filtre effectif)
            if with_date == 0:
                logger.info("Free Mobile: aucune date reconnue sur les titres → téléchargement de toutes les factures.")
                filtered = orders

        # Déduplication finale par URL canonique (éviter doublons)
        seen_norm: set[str] = set()
        deduped: List[OrderInfo] = []
        for o in filtered:
            norm = self._normalize_invoice_url(o.invoice_url or "")
            if norm and norm not in seen_norm:
                seen_norm.add(norm)
                deduped.append(o)
        if len(deduped) < len(filtered):
            logger.info("Free Mobile: %s doublon(s) supprimé(s)", len(filtered) - len(deduped))
        filtered = deduped

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
        if count == 0:
            self._save_debug_page("free_mobile_zero_downloaded")
            logger.warning(
                "Free Mobile: 0 facture téléchargée au final. Page sauvegardée dans logs/free_mobile_zero_downloaded.html pour diagnostic."
            )
        logger.info("Free Mobile: %s facture(s) téléchargée(s)", count)
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
            logger.warning("Free Mobile submit_otp: %s", e)
            return False
