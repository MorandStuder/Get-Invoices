"""
Service pour télécharger automatiquement les factures Amazon.
"""
import re
import time
import logging
from datetime import datetime, date as date_type
from typing import Any, Optional, Dict, List, Union, Callable, Awaitable, Tuple
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from backend.services.invoice_registry import InvoiceRegistry, PROVIDER_AMAZON

logger = logging.getLogger(__name__)

# Mois FR pour le parsing des dates Amazon
_MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "janv": 1, "févr": 2, "fevr": 2, "avr": 4, "juil": 7, "sept": 9,
    "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}


class AmazonInvoiceDownloader:
    """
    Classe pour automatiser le téléchargement de factures Amazon.
    """
    
    AMAZON_BASE_URL = "https://www.amazon.fr"
    AMAZON_LOGIN_URL = "https://www.amazon.fr/ap/signin"
    AMAZON_ORDERS_URL = "https://www.amazon.fr/gp/css/order-history"
    
    def __init__(
        self,
        email: str,
        password: str,
        download_path: str = "./factures",
        headless: bool = False,
        timeout: int = 30,
        otp_callback: Optional[Callable[[], Awaitable[str]]] = None,
        manual_mode: bool = False,
        browser: str = "chrome",  # "chrome" ou "firefox"
        firefox_profile_path: Optional[str] = None,  # Chemin vers le profil Firefox existant (session persistante)
        chrome_user_data_dir: Optional[str] = None,  # Répertoire de profil Chrome (session persistante)
        keep_browser_open: bool = False,  # Ne pas fermer le navigateur à la fin (connexion continue)
    ) -> None:
        """
        Initialise le téléchargeur Amazon.
        
        Args:
            email: Email du compte Amazon
            password: Mot de passe du compte Amazon
            download_path: Chemin où sauvegarder les factures
            headless: Mode headless pour le navigateur
            timeout: Timeout en secondes pour les opérations
            otp_callback: Fonction async pour obtenir le code OTP (optionnel)
        """
        self.email = email
        self.password = password
        self.download_path = Path(download_path)
        self.headless = headless
        self.timeout = timeout
        self.manual_mode = manual_mode
        self.browser = browser.lower()
        self.firefox_profile_path = firefox_profile_path
        self.chrome_user_data_dir = chrome_user_data_dir
        self.keep_browser_open = keep_browser_open
        self.driver: Optional[Union[webdriver.Chrome, webdriver.Firefox]] = None
        self.otp_callback = otp_callback
        self.pending_otp: Optional[str] = None
        
        # Créer le dossier de téléchargement
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.registry = InvoiceRegistry(self.download_path)

        logger.info(f"AmazonInvoiceDownloader initialisé avec chemin: {self.download_path}")
        logger.info(f"Configuration: browser={self.browser}, headless={self.headless}, manual_mode={self.manual_mode}, timeout={self.timeout}")
    
    def _setup_driver(self) -> Union[webdriver.Chrome, webdriver.Firefox]:
        """
        Configure et retourne une instance de WebDriver (Chrome ou Firefox).
        
        Returns:
            Instance de WebDriver configurée
        
        Raises:
            Exception: Si le driver ne peut pas être créé
        """
        if self.browser == "firefox":
            return self._setup_firefox_driver()
        else:
            return self._setup_chrome_driver()
    
    def _setup_chrome_driver(self) -> webdriver.Chrome:
        """
        Configure et retourne une instance de WebDriver Chrome.
        
        Returns:
            Instance de WebDriver Chrome configurée
        
        Raises:
            Exception: Si le driver ne peut pas être créé
        """
        try:
            logger.info("Configuration du driver Chrome...")
            chrome_options = ChromeOptions()
            
            if self.headless:
                chrome_options.add_argument("--headless")
            
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-gpu")  # Éviter les crashes GPU
            chrome_options.add_argument("--disable-software-rasterizer")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")
            chrome_options.add_argument("--disable-renderer-backgrounding")
            chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
            chrome_options.add_argument("--remote-debugging-port=9222")  # Pour éviter les crashes
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # Profil persistant : cookies et session Amazon conservés entre les lancements
            if self.chrome_user_data_dir:
                profile_path = Path(self.chrome_user_data_dir).resolve()
                profile_path.mkdir(parents=True, exist_ok=True)
                chrome_options.add_argument(f"--user-data-dir={profile_path}")
                logger.info("Profil Chrome persistant: %s", profile_path)
            
            # Configuration du téléchargement
            prefs = {
                "download.default_directory": str(self.download_path.absolute()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            logger.info("Installation/téléchargement de ChromeDriver...")
            driver_path = ChromeDriverManager().install()
            logger.info(f"Chemin ChromeDriver retourné: {driver_path}")

            # Vérifier que c'est bien l'exécutable
            if not Path(driver_path).exists() or not str(driver_path).endswith('.exe'):
                driver_dir = Path(driver_path).parent

                # Liste des chemins possibles (ordre de priorité)
                driver_path_str = str(driver_path)
                possible_paths = [
                    driver_path_str.replace('THIRD_PARTY_NOTICES.chromedriver', 'chromedriver.exe'),
                    str(driver_dir / 'chromedriver.exe'),
                    str(driver_dir / 'chromedriver-win32' / 'chromedriver.exe'),
                    str(driver_dir.parent / 'chromedriver.exe'),
                ]

                found = False
                for path in possible_paths:
                    p = Path(path)
                    if p.exists() and p.is_file():
                        # Vérifier que c'est un exécutable (pas un fichier texte)
                        try:
                            with open(path, 'rb') as f:
                                header = f.read(2)
                                # Les exécutables Windows commencent par 'MZ'
                                if header == b'MZ':
                                    driver_path = path  # str
                                    logger.info("ChromeDriver exécutable trouvé: %s", driver_path)
                                    found = True
                                    break
                        except Exception:
                            continue

                if not found:
                    raise Exception(
                        f"ChromeDriver exécutable non trouvé. "
                        f"Chemin retourné: {driver_path}. "
                        f"Chemins testés: {possible_paths}. "
                        f"Veuillez nettoyer le cache avec: Remove-Item -Recurse -Force $env:USERPROFILE\\.wdm\\drivers\\chromedriver"
                    )
            
            service = ChromeService(driver_path)
            logger.info("Création de l'instance WebDriver...")
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Désactiver la détection WebDriver
            driver.execute_cdp_cmd(
                'Page.addScriptToEvaluateOnNewDocument',
                {'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'}
            )
            
            logger.info("Driver Chrome créé avec succès")
            return driver
        except Exception as e:
            logger.error(f"Erreur lors de la création du driver Chrome: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Impossible de créer le driver Chrome: {str(e)}") from e
    
    def _setup_firefox_driver(self) -> webdriver.Firefox:
        """
        Configure et retourne une instance de WebDriver Firefox.
        Utilise un profil existant si spécifié.
        
        Returns:
            Instance de WebDriver Firefox configurée
        
        Raises:
            Exception: Si le driver ne peut pas être créé
        """
        try:
            logger.info("Configuration du driver Firefox...")
            firefox_options = FirefoxOptions()
            
            if self.headless:
                firefox_options.add_argument("--headless")
            
            # Si un profil Firefox est spécifié, l'utiliser
            if self.firefox_profile_path:
                profile_path = Path(self.firefox_profile_path)
                if profile_path.exists():
                    logger.info(f"Utilisation du profil Firefox: {profile_path}")
                    # Vérifier si le profil est verrouillé (Firefox déjà ouvert)
                    lock_file = profile_path / "lock"
                    if lock_file.exists():
                        logger.warning("Le profil Firefox semble être verrouillé (Firefox peut être déjà ouvert)")
                        logger.warning("Fermez Firefox ou utilisez un autre profil")
                        # Essayer quand même, mais avec un timeout plus court
                    firefox_profile = FirefoxProfile(str(profile_path))
                    firefox_options.profile = firefox_profile
                else:
                    logger.warning(f"Profil Firefox non trouvé: {profile_path}, utilisation du profil par défaut")
            else:
                # Créer un profil temporaire avec les préférences de téléchargement
                logger.info("Création d'un profil Firefox temporaire...")
                firefox_profile = FirefoxProfile()
                firefox_profile.set_preference("browser.download.folderList", 2)
                firefox_profile.set_preference("browser.download.dir", str(self.download_path.absolute()))
                firefox_profile.set_preference("browser.download.useDownloadDir", True)
                firefox_profile.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf")
                firefox_options.profile = firefox_profile
            
            logger.info("Installation/téléchargement de GeckoDriver...")
            driver_path = GeckoDriverManager().install()
            logger.info(f"Chemin GeckoDriver: {driver_path}")
            
            service = FirefoxService(driver_path)
            logger.info("Création de l'instance WebDriver Firefox...")
            # Ajouter un timeout pour éviter que ça bloque trop longtemps
            import socket
            socket.setdefaulttimeout(10)  # 10 secondes de timeout
            try:
                driver = webdriver.Firefox(service=service, options=firefox_options)
                logger.info("Driver Firefox créé avec succès")
                return driver
            finally:
                socket.setdefaulttimeout(None)  # Réinitialiser le timeout
        except Exception as e:
            logger.error(f"Erreur lors de la création du driver Firefox: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Message d'erreur plus explicite
            error_msg = str(e)
            if "WinError 10061" in error_msg or "refused" in error_msg.lower():
                error_msg = "Impossible de se connecter à Firefox. Assurez-vous que Firefox n'est pas déjà ouvert avec ce profil, ou fermez Firefox et réessayez."
            raise Exception(f"Impossible de créer le driver Firefox: {error_msg}") from e
    
    def _is_2fa_required(self) -> bool:
        """
        Vérifie si Amazon demande un code 2FA.
        
        Returns:
            True si un code 2FA est requis, False sinon
        """
        try:
            if not self.driver:
                logger.debug("Driver non initialisé, 2FA non requis")
                return False
            
            # Vérifier différents sélecteurs possibles pour la page 2FA
            selectors_2fa = [
                "input[name='otpCode']",
                "input[name='code']",
                "input[id='auth-code']",
                "input[id='totpCode']",
                "input[placeholder*='code']",
                "input[placeholder*='Code']",
                "input[aria-label*='code']",
                "input[aria-label*='Code']",
            ]
            
            for selector in selectors_2fa:
                try:
                    self.driver.find_element(By.CSS_SELECTOR, selector)
                    logger.info("Code 2FA détecté sur la page")
                    return True
                except NoSuchElementException:
                    continue
            
            # Vérifier aussi par le texte de la page
            page_text = self.driver.page_source.lower()
            if any(keyword in page_text for keyword in [
                "code de vérification",
                "verification code",
                "code à 6 chiffres",
                "6-digit code",
                "entrez le code",
                "enter the code",
                "authentification à deux facteurs",
                "two-factor authentication"
            ]):
                logger.info("Code 2FA détecté via texte de la page")
                return True
            
            return False
        
        except Exception as e:
            logger.warning(f"Erreur lors de la détection 2FA: {str(e)}")
            return False
    
    async def _handle_2fa(self, otp_code: Optional[str] = None) -> bool:
        """
        Gère l'authentification à deux facteurs.
        
        Args:
            otp_code: Code OTP fourni (si None, utilise pending_otp ou callback)
        
        Returns:
            True si le code est accepté, False sinon
        """
        try:
            if not self.driver:
                return False
            
            wait = WebDriverWait(self.driver, self.timeout)
            
            # Obtenir le code OTP
            code_to_use = otp_code or self.pending_otp
            
            if not code_to_use and self.otp_callback:
                logger.info("Demande du code OTP via callback...")
                code_to_use = await self.otp_callback()
            
            if not code_to_use:
                logger.error("Aucun code OTP disponible")
                return False
            
            logger.info("Saisie du code 2FA...")

            # Attendre un peu pour que la page charge complètement
            time.sleep(2)

            # Trouver le champ de saisie du code - essayer plusieurs sélecteurs
            otp_selectors = [
                "input[name='otpCode']",
                "input[name='code']",
                "input[id='auth-code']",
                "input[id='auth-mfa-otpcode']",  # Amazon France
                "input[id='auth-mfa-remember-device']",
                "input[id='totpCode']",
                "input[type='tel']",  # Amazon utilise parfois type='tel' pour OTP
                "input[type='text'][maxlength='6']",
                "input[type='number'][maxlength='6']",
            ]

            otp_input = None
            for selector in otp_selectors:
                try:
                    logger.info(f"Tentative avec sélecteur: {selector}")
                    otp_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    logger.info(f"Champ OTP trouvé avec: {selector}")
                    break
                except NoSuchElementException:
                    continue

            if not otp_input:
                # Essayer de trouver par placeholder ou aria-label
                try:
                    logger.info("Tentative avec XPath placeholder/aria-label...")
                    otp_input = wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//input[@type='text' and (contains(@placeholder, 'code') or contains(@aria-label, 'code') or contains(@id, 'otp') or contains(@name, 'otp'))]")
                        )
                    )
                    logger.info("Champ OTP trouvé avec XPath")
                except TimeoutException:
                    pass

            if not otp_input:
                # Dernière tentative : chercher tous les inputs visibles de type text/tel/number
                try:
                    logger.info("Dernière tentative : recherche de tous les inputs visibles...")
                    all_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='tel'], input[type='number']")
                    for inp in all_inputs:
                        if inp.is_displayed():
                            logger.info(f"Input trouvé - id: {inp.get_attribute('id')}, name: {inp.get_attribute('name')}, type: {inp.get_attribute('type')}")
                            otp_input = inp
                            break
                except Exception as e:
                    logger.error(f"Erreur lors de la recherche de tous les inputs: {str(e)}")

            if not otp_input:
                logger.error("Champ de saisie du code OTP introuvable après toutes les tentatives")
                logger.error(f"URL actuelle: {self.driver.current_url}")
                logger.error(f"Titre de la page: {self.driver.title}")
                return False
            
            # Saisir le code
            otp_input.clear()
            otp_input.send_keys(code_to_use)
            time.sleep(1)
            
            # Trouver et cliquer sur le bouton de soumission
            submit_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button[id*='continue']",
                "button[id*='submit']",
                "input[id*='continue']",
                "input[id*='submit']",
            ]
            
            submit_button = None
            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    # Préférer les boutons contenant "continue" ou "submit" dans le texte
                    for btn in buttons:
                        btn_text = btn.text.lower()
                        if any(keyword in btn_text for keyword in ["continuer", "continue", "soumettre", "submit"]):
                            submit_button = btn
                            break
                    if submit_button:
                        break
                    if buttons:
                        submit_button = buttons[0]
                        break
                except NoSuchElementException:
                    continue
            
            if submit_button:
                submit_button.click()
            else:
                # Fallback: appuyer sur Enter dans le champ
                from selenium.webdriver.common.keys import Keys
                otp_input.send_keys(Keys.RETURN)
            
            # Attendre la validation
            time.sleep(5)
            
            # Vérifier si la connexion a réussi
            if not self._is_2fa_required():
                logger.info("Code 2FA accepté")
                self.pending_otp = None
                return True
            else:
                logger.warning("Le code 2FA semble incorrect ou expiré")
                return False
        
        except Exception as e:
            logger.error(f"Erreur lors de la gestion 2FA: {str(e)}")
            return False
    
    def _is_logged_in(self) -> bool:
        """Verifie si on est deja connecte a Amazon (session existante)."""
        try:
            if not self.driver:
                return False
            current_url = self.driver.current_url
            # Si on est sur une page de login, on n'est pas connecte
            if "/ap/signin" in current_url or "/ap/cvf/" in current_url:
                return False
            # Verifier la presence d'elements de navigation Amazon
            try:
                self.driver.find_element(By.ID, "nav-link-accountList")
                return True
            except NoSuchElementException:
                pass
            try:
                self.driver.find_element(By.ID, "nav-orders")
                return True
            except NoSuchElementException:
                pass
            # Si on est sur amazon.fr mais pas sur une page de login
            if "amazon.fr" in current_url and "/ap/" not in current_url:
                return True
            return False
        except Exception:
            return False

    async def login(self, otp_code: Optional[str] = None) -> bool:
        """
        Connecte l'utilisateur à Amazon.

        Args:
            otp_code: Code OTP pour la 2FA (optionnel, peut être fourni plus tard)

        Returns:
            True si la connexion réussit, False sinon
        """
        try:
            logger.info(f"=== DEBUT LOGIN === manual_mode={self.manual_mode}, otp_code={'fourni' if otp_code else 'non fourni'}")

            if not self.driver:
                logger.info("Driver non initialise, creation du driver...")
                self.driver = self._setup_driver()
                logger.info(f"Driver cree avec succes: {type(self.driver).__name__}")
            else:
                # Verifier si on est deja connecte (session existante)
                if self._is_logged_in():
                    logger.info("Session existante detectee, pas besoin de se reconnecter")
                    return True

            logger.info(f"Connexion a Amazon...")
            
            # Si on utilise Firefox avec un profil existant, on peut être déjà connecté
            if self.browser == "firefox" and self.firefox_profile_path:
                logger.info("Utilisation d'un profil Firefox existant - vérification de la connexion...")
                # Aller directement sur Amazon pour vérifier si on est connecté
                self.driver.get(self.AMAZON_BASE_URL)
                time.sleep(3)
                
                # Vérifier si on est déjà connecté
                try:
                    # Chercher des éléments qui indiquent qu'on est connecté
                    account_elements = [
                        (By.ID, "nav-link-accountList"),
                        (By.ID, "nav-orders"),
                    ]
                    
                    connected = False
                    for by, selector in account_elements:
                        try:
                            element = self.driver.find_element(by, selector)
                            if element:
                                # Vérifier le texte pour s'assurer qu'on n'est pas sur "Se connecter"
                                element_text = element.text.lower() if hasattr(element, 'text') else ""
                                if "connecter" not in element_text and "sign in" not in element_text:
                                    logger.info("Connexion détectée via profil Firefox existant !")
                                    connected = True
                                    break
                        except NoSuchElementException:
                            continue
                    
                    if connected:
                        logger.info("Déjà connecté à Amazon via le profil Firefox")
                        return True
                    else:
                        logger.info("Non connecté, redirection vers la page de connexion...")
                        self.driver.get(self.AMAZON_LOGIN_URL)
                        time.sleep(2)
                except Exception as e:
                    logger.warning(f"Erreur lors de la vérification de connexion: {str(e)}")
                    self.driver.get(self.AMAZON_LOGIN_URL)
                    time.sleep(2)
            else:
                # Essayer d'abord l'URL directe de connexion
                logger.info(f"Chargement de l'URL de connexion Amazon: {self.AMAZON_LOGIN_URL}")
                self.driver.get(self.AMAZON_LOGIN_URL)
                time.sleep(2)
                logger.info("Page de connexion chargée")

            # En mode manuel, skip toute la logique complexe et laisser l'utilisateur se connecter
            logger.info(f"=== VÉRIFICATION MODE MANUEL: manual_mode={self.manual_mode} ===")
            if self.manual_mode:
                logger.info("=== MODE MANUEL ACTIVÉ ===")
                logger.info("Une fenêtre Chrome s'est ouverte sur Amazon")
                logger.info("Veuillez vous connecter manuellement dans le navigateur")
                logger.info("Le script attendra jusqu'à 5 minutes que vous soyez connecté")
                logger.info("=========================")

                # Attendre que l'utilisateur soit connecté
                max_wait_time = 300  # 5 minutes
                wait_interval = 5
                elapsed_time = 0

                while elapsed_time < max_wait_time:
                    time.sleep(wait_interval)
                    elapsed_time += wait_interval

                    current_url = self.driver.current_url
                    # Vérifier si on est connecté (pas sur la page de login)
                    if "/ap/signin" not in current_url and "/ap/cvf/request" not in current_url:
                        # Vérifier si on a les éléments de navigation
                        try:
                            self.driver.find_element(By.ID, "nav-link-accountList")
                            logger.info("Connexion detectee!")
                            return True
                        except NoSuchElementException:
                            # Peut-être qu'on est sur une autre page, continuer à attendre
                            pass

                    logger.info(f"Attente de connexion manuelle... ({elapsed_time}s/{max_wait_time}s)")

                logger.warning("Timeout en mode manuel - connexion non détectée après 5 minutes")
                return False

            # Vérifier si on est sur une page d'erreur ou si on doit naviguer différemment
            current_url = self.driver.current_url
            page_title = self.driver.title.lower()
            page_source = self.driver.page_source.lower()

            logger.info(f"URL après chargement: {current_url}")
            logger.info(f"Titre de la page: {self.driver.title}")
            
            # Si on est sur une page d'erreur ou la page d'accueil, essayer de naviguer vers la connexion
            if "recherchez quelque chose" in page_source or "page d'accueil" in page_title or ("amazon.fr" in current_url and "/ap/signin" not in current_url and "/gp/" not in current_url):
                logger.info("Page d'erreur ou page d'accueil détectée, navigation vers la connexion...")
                # Essayer d'abord directement l'URL de connexion avec paramètres complets
                logger.info("Tentative avec URL de connexion directe...")
                direct_login_url = f"{self.AMAZON_BASE_URL}/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.fr%2F%3Fref_%3Dnav_signin&prevRID=&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=frflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&pageId=frflex&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
                self.driver.get(direct_login_url)
                time.sleep(3)
                
                # Vérifier si on a maintenant le champ email
                email_found = False
                try:
                    self.driver.find_element(By.ID, "ap_email")
                    logger.info("Page de connexion chargée directement avec succès")
                    email_found = True
                except NoSuchElementException:
                    logger.info("URL directe n'a pas fonctionné, tentative via page d'accueil...")
                    # Si ça ne fonctionne pas, essayer via la page d'accueil
                    self.driver.get(self.AMAZON_BASE_URL)
                    time.sleep(2)
                
                # Si l'email n'a pas été trouvé, essayer de cliquer sur le lien
                if not email_found:
                    # Chercher le lien "Se connecter" ou "Compte et listes"
                    try:
                        # Essayer plusieurs sélecteurs pour le lien de connexion
                        sign_in_selectors = [
                            "a[href*='/ap/signin']",
                            "a#nav-link-accountList",
                            "a[data-nav-role='signin']",
                            "//a[contains(text(), 'Se connecter')]",
                            "//a[contains(text(), 'Compte et listes')]",
                            "//span[contains(text(), 'Bonjour')]/parent::a",
                        ]
                        
                        sign_in_link = None
                        for selector in sign_in_selectors:
                            try:
                                if selector.startswith("//"):
                                    sign_in_link = self.driver.find_element(By.XPATH, selector)
                                else:
                                    sign_in_link = self.driver.find_element(By.CSS_SELECTOR, selector)
                                if sign_in_link:
                                    logger.info(f"Lien de connexion trouvé avec: {selector}")
                                    # Essayer de cliquer normalement
                                    try:
                                        sign_in_link.click()
                                    except Exception:
                                        # Si le clic normal échoue, utiliser JavaScript
                                        logger.info("Clic normal échoué, utilisation de JavaScript...")
                                        self.driver.execute_script("arguments[0].click();", sign_in_link)
                                    time.sleep(3)
                                    break
                            except NoSuchElementException:
                                continue
                            except Exception as e:
                                logger.warning(f"Erreur avec le sélecteur {selector}: {str(e)}")
                                continue
                        
                        if not sign_in_link:
                            # Essayer directement l'URL de connexion avec des paramètres
                            logger.info("Lien de connexion non trouvé, tentative avec URL directe...")
                            # Essayer plusieurs variantes d'URL de connexion
                            login_urls = [
                                f"{self.AMAZON_BASE_URL}/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.fr%2F%3Fref_%3Dnav_signin&prevRID=&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=frflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&pageId=frflex&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0",
                                f"{self.AMAZON_BASE_URL}/ap/signin",
                                f"{self.AMAZON_BASE_URL}/gp/navigation-country/select-country.html?language=fr_FR&ref_=nav_em_hdr_signin",
                            ]
                            
                            for url in login_urls:
                                try:
                                    logger.info(f"Tentative avec URL: {url}")
                                    self.driver.get(url)
                                    time.sleep(3)
                                    # Vérifier si on a le champ email maintenant
                                    try:
                                        self.driver.find_element(By.ID, "ap_email")
                                        logger.info("Page de connexion chargée avec succès")
                                        break
                                    except NoSuchElementException:
                                        continue
                                except Exception as e:
                                    logger.warning(f"Erreur avec URL {url}: {str(e)}")
                                    continue
                    except Exception as e:
                        logger.warning(f"Erreur lors de la navigation vers la connexion: {str(e)}")
                        # Essayer quand même l'URL de connexion standard
                        self.driver.get(self.AMAZON_LOGIN_URL)
                        time.sleep(3)

            # Mode automatique : remplir les champs automatiquement
            # Attendre et remplir l'email
            logger.info("Recherche du champ email...")
            wait = WebDriverWait(self.driver, self.timeout)
            try:
                email_input = wait.until(
                    EC.presence_of_element_located((By.ID, "ap_email"))
                )
                logger.info("Champ email trouvé, saisie de l'email...")
                email_input.clear()
                email_input.send_keys(self.email)
            except TimeoutException:
                logger.error("Champ email non trouvé - la page n'a peut-être pas chargé correctement")
                logger.error(f"URL actuelle: {self.driver.current_url}")
                logger.error(f"Titre de la page: {self.driver.title}")
                raise Exception("Impossible de trouver le champ email sur la page de connexion")

            # Cliquer sur continuer
            logger.info("Recherche du bouton continuer...")
            try:
                continue_button = self.driver.find_element(By.ID, "continue")
                continue_button.click()
                logger.info("Bouton continuer cliqué")
            except NoSuchElementException:
                logger.error("Bouton continuer non trouvé")
                raise Exception("Impossible de trouver le bouton continuer")

            time.sleep(2)  # Attendre le chargement

            # Remplir le mot de passe
            logger.info("Recherche du champ mot de passe...")
            try:
                password_input = wait.until(
                    EC.presence_of_element_located((By.ID, "ap_password"))
                )
                logger.info("Champ mot de passe trouvé, saisie du mot de passe...")
                password_input.clear()
                password_input.send_keys(self.password)
            except TimeoutException:
                logger.error("Champ mot de passe non trouvé")
                raise Exception("Impossible de trouver le champ mot de passe")

            # Cliquer sur se connecter
            logger.info("Recherche du bouton de connexion...")
            try:
                sign_in_button = self.driver.find_element(By.ID, "signInSubmit")
                sign_in_button.click()
                logger.info("Bouton de connexion cliqué")
            except NoSuchElementException:
                logger.error("Bouton de connexion non trouvé")
                raise Exception("Impossible de trouver le bouton de connexion")

            # Attendre la redirection ou la demande de 2FA
            time.sleep(5)

            # Vérifier si un code 2FA est requis
            if self._is_2fa_required():
                logger.info("Authentification à deux facteurs requise")
                if otp_code:
                    self.pending_otp = otp_code
                
                if await self._handle_2fa(otp_code):
                    # Attendre encore un peu après la validation du code
                    time.sleep(3)
                else:
                    logger.warning("Échec de la validation du code 2FA")
                    return False
            
            # Vérifier si on est connecté (présence du menu compte ou des commandes)
            logger.info("Vérification de la connexion...")
            current_url = self.driver.current_url
            logger.info(f"URL actuelle après connexion: {current_url}")
            logger.info(f"Titre de la page: {self.driver.title}")
            
            # Vérifier d'abord l'URL
            if "/ap/signin" in current_url or "/ap/cvf/request" in current_url:
                logger.warning("Toujours sur la page de connexion")
                # Vérifier si c'est une page 2FA
                if self._is_2fa_required():
                    logger.info("Page 2FA détectée - connexion nécessite un code OTP")
                    return False
                else:
                    logger.error("Sur la page de connexion mais 2FA non détectée")
                    return False
            
            # Si on n'est pas sur la page de login, vérifier les éléments de la page connectée
            try:
                # Créer wait si pas déjà défini (pour le mode manuel ou Firefox)
                if 'wait' not in locals():
                    wait = WebDriverWait(self.driver, self.timeout)
                
                wait.until(
                    EC.any_of(
                        EC.presence_of_element_located((By.ID, "nav-link-accountList")),
                        EC.presence_of_element_located((By.ID, "nav-orders")),
                        EC.url_contains("amazon.fr"),
                        EC.url_contains("amazon.com")
                    )
                )
                logger.info("Connexion réussie - éléments de navigation trouvés")
                return True
            except TimeoutException:
                # Vérifier l'URL pour être sûr
                logger.warning("Timeout lors de la recherche des éléments de navigation")
                logger.info(f"URL finale: {self.driver.current_url}")
                # Si on n'est pas sur la page de login, on considère qu'on est connecté
                if "/ap/signin" not in current_url and "/ap/cvf/request" not in current_url:
                    logger.info("Connexion réussie (vérification par URL uniquement)")
                    return True
                else:
                    logger.error("Connexion échouée - page de connexion toujours présente")
                    return False
        
        except Exception as e:
            import traceback
            logger.error(f"Erreur lors de la connexion: {str(e)}")
            logger.error(f"Type d'erreur: {type(e).__name__}")
            logger.error(f"Traceback complet:\n{traceback.format_exc()}")
            # Si c'est une exception que nous avons levée nous-mêmes, la propager
            if "Impossible de" in str(e) or "non trouvé" in str(e).lower():
                raise
            return False
    
    async def submit_otp(self, otp_code: str) -> bool:
        """
        Soumet un code OTP pour la 2FA et complète la connexion.
        
        Args:
            otp_code: Code OTP à soumettre
        
        Returns:
            True si le code est accepté et la connexion réussit
        """
        self.pending_otp = otp_code
        
        # Si le driver n'est pas initialisé, on doit d'abord faire le login
        if not self.driver:
            logger.info("Driver non initialisé, démarrage de la connexion avec code OTP...")
            return await self.login(otp_code=otp_code)
        
        # Sinon, on gère juste la 2FA
        success = await self._handle_2fa(otp_code)
        
        # Si la 2FA est acceptée, vérifier que la connexion est complète
        if success:
            # Attendre un peu pour que la page se charge
            time.sleep(3)
            # Vérifier qu'on est bien connecté
            try:
                current_url = self.driver.current_url
                if "/ap/signin" not in current_url and "/ap/cvf/request" not in current_url:
                    logger.info("Connexion complétée après 2FA")
                    return True
                else:
                    logger.warning("Toujours sur la page de connexion après 2FA")
                    return False
            except Exception as e:
                logger.error(f"Erreur lors de la vérification de connexion après 2FA: {str(e)}")
                return False
        
        return success
    
    def is_2fa_required(self) -> bool:
        """
        Vérifie si un code 2FA est actuellement requis.
        
        Returns:
            True si un code 2FA est requis
        """
        return self._is_2fa_required()
    
    def _is_on_orders_page(self) -> bool:
        """Vérifie si on est réellement sur la page des commandes (pas sur /ap/signin)."""
        try:
            current_url = self.driver.current_url
            # Exclure les pages de login qui contiennent "your-orders" dans return_to
            if "/ap/signin" in current_url or "/ap/cvf/" in current_url:
                return False
            # Vérifier le chemin de l'URL (pas les query params)
            from urllib.parse import urlparse
            path = urlparse(current_url).path.lower()
            return "order-history" in path or "your-orders" in path or "order" in path
        except Exception:
            return False

    def _has_next_orders_page(self) -> bool:
        """
        Vérifie s'il existe une page suivante de commandes (lien "Suivant" / "Next" cliquable).
        Returns:
            True si un lien page suivante existe et est cliquable
        """
        try:
            if not self.driver:
                return False
            # Sélecteurs courants Amazon pour la pagination (order history)
            next_selectors = [
                (By.CSS_SELECTOR, "ul.a-pagination li.a-last:not(.a-disabled) a"),
                (By.CSS_SELECTOR, ".a-pagination .a-last a:not(.a-disabled)"),
                (By.XPATH, "//span[contains(@class,'a-pagination')]//li[contains(@class,'a-last') and not(contains(@class,'a-disabled'))]//a"),
                (By.XPATH, "//a[contains(text(),'Suivant') or contains(text(),'Next')]"),
                (By.CSS_SELECTOR, "a.s-pagination-next:not(.s-pagination-disabled)"),
                (By.CSS_SELECTOR, "a[href*='pageToken']"),
            ]
            for by, selector in next_selectors:
                try:
                    elements = self.driver.find_elements(by, selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            # Éviter le lien "disabled"
                            parent = elem.find_element(By.XPATH, "./..")
                            if "a-disabled" in (parent.get_attribute("class") or ""):
                                continue
                            return True
                except NoSuchElementException:
                    continue
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Vérification page suivante: {e}")
            return False

    def _go_to_next_orders_page(self) -> bool:
        """
        Passe à la page suivante des commandes (clic sur Suivant / Next).
        Returns:
            True si la navigation a réussi, False sinon
        """
        try:
            if not self.driver:
                return False
            next_selectors = [
                (By.CSS_SELECTOR, "ul.a-pagination li.a-last:not(.a-disabled) a"),
                (By.CSS_SELECTOR, ".a-pagination .a-last a"),
                (By.XPATH, "//a[contains(text(),'Suivant') or contains(text(),'Next')]"),
                (By.CSS_SELECTOR, "a.s-pagination-next:not(.s-pagination-disabled)"),
                (By.CSS_SELECTOR, "a[href*='pageToken']"),
            ]
            for by, selector in next_selectors:
                try:
                    elements = self.driver.find_elements(by, selector)
                    for elem in elements:
                        if not elem.is_displayed() or not elem.is_enabled():
                            continue
                        try:
                            parent = elem.find_element(By.XPATH, "./..")
                            if "a-disabled" in (parent.get_attribute("class") or ""):
                                continue
                        except Exception:
                            pass
                        href = elem.get_attribute("href")
                        logger.info("Passage à la page suivante des commandes...")
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(0.5)
                            elem.click()
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", elem)
                        time.sleep(4)
                        if href and self.driver.current_url != href:
                            try:
                                self.driver.get(href)
                                time.sleep(4)
                            except Exception:
                                pass
                        if self._is_on_orders_page():
                            logger.info("Page suivante chargée")
                            return True
                        break
                    if self._is_on_orders_page():
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Clic page suivante ({selector}): {e}")
                    continue
            return False
        except Exception as e:
            logger.warning(f"Impossible de passer à la page suivante: {e}")
            return False

    def _get_amazon_periods_for_request(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        months: Optional[List[int]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> List[str]:
        """
        Détermine les libellés de période Amazon à sélectionner à partir du filtre de l'interface.
        Retourne la plus petite (ou les plus petites) périodes couvrant la demande.
        Ex. plage 2025-2026 → ["en 2026", "en 2025"] ; année 2025 → ["en 2025"] ; pas de filtre → ["les 3 derniers mois"].
        """
        if date_start and date_end:
            try:
                start_d = datetime.strptime(date_start, "%Y-%m-%d").date()
                end_d = datetime.strptime(date_end, "%Y-%m-%d").date()
                years_set = set(range(start_d.year, end_d.year + 1))
                years_desc = sorted(years_set, reverse=True)
                return [f"en {y}" for y in years_desc]
            except ValueError:
                pass
        if year is not None:
            return [f"en {year}"]
        return ["les 3 derniers mois"]

    def _select_orders_period(self, option_text: str) -> bool:
        """
        Sélectionne la période des commandes dans la liste déroulante Amazon.
        option_text: libellé exact (ex. "en 2025", "les 3 derniers mois").
        Returns:
            True si la sélection a réussi ou filtre non trouvé (on continue), False en cas d'erreur bloquante.
        """
        if not option_text:
            return True
        try:
            if not self.driver:
                return False
            select_elem = None
            for by, selector in [
                (By.ID, "orderFilter"),
                (By.CSS_SELECTOR, "select[name='orderFilter']"),
                (By.CSS_SELECTOR, "select#orderFilter"),
                (By.XPATH, "//select[contains(@name,'order') or contains(@id,'order') or contains(@id,'filter')]"),
                (By.CSS_SELECTOR, "#ordersContainer select, .order-history select, select.a-native-dropdown"),
            ]:
                try:
                    elems = self.driver.find_elements(by, selector)
                    for el in elems:
                        if el.is_displayed():
                            select_elem = el
                            break
                    if select_elem:
                        break
                except NoSuchElementException:
                    continue
            if not select_elem:
                logger.warning("Liste déroulante période des commandes non trouvée; poursuite sans filtre.")
                return True
            sel = Select(select_elem)
            try:
                sel.select_by_visible_text(option_text)
                logger.info("Période des commandes sélectionnée: %s", option_text)
                time.sleep(3)
                return True
            except Exception:
                for opt in sel.options:
                    if option_text in (opt.text or "").strip():
                        opt.click()
                        logger.info("Période des commandes sélectionnée (option): %s", option_text)
                        time.sleep(3)
                        return True
                raise
        except Exception as e:
            logger.warning("Impossible de sélectionner la période des commandes: %s", e)
            return True

    async def navigate_to_orders(self) -> bool:
        """
        Navigue vers la page des commandes.

        Returns:
            True si la navigation réussit, False sinon
        """
        try:
            # En mode manuel, on est déjà connecté - naviguer directement
            if self.manual_mode:
                logger.info("Mode manuel: navigation automatique vers la page des commandes...")
                self.driver.get(self.AMAZON_ORDERS_URL)
                time.sleep(5)

                current_url = self.driver.current_url
                logger.info(f"URL après navigation: {current_url}")

                # Si redirigé vers login, attendre que l'utilisateur se connecte
                if "/ap/signin" in current_url or "/ap/cvf/" in current_url:
                    logger.info("Redirection vers login détectée, attente de connexion manuelle...")
                    max_wait = 300
                    elapsed = 0
                    while elapsed < max_wait:
                        if self._is_on_orders_page():
                            logger.info("Page des commandes détectée!")
                            time.sleep(3)
                            return True
                        if elapsed % 10 == 0:
                            logger.info(f"Attente de navigation vers les commandes... ({elapsed}s/{max_wait}s)")
                        time.sleep(5)
                        elapsed += 5
                    logger.error(f"Timeout: page des commandes non atteinte en {max_wait}s")
                    return False

                # Vérifier qu'on est bien sur les commandes
                if self._is_on_orders_page():
                    logger.info("Page des commandes chargée avec succès")
                    time.sleep(2)
                    return True

                # Attendre un peu plus au cas où la page charge
                logger.info("Attente du chargement de la page des commandes...")
                for _ in range(12):  # 60 secondes max
                    time.sleep(5)
                    if self._is_on_orders_page():
                        logger.info("Page des commandes détectée!")
                        time.sleep(2)
                        return True

                logger.error("Impossible d'atteindre la page des commandes")
                return False

            # Mode automatique
            logger.info("Navigation vers la page des commandes...")
            logger.info(f"URL des commandes: {self.AMAZON_ORDERS_URL}")
            self.driver.get(self.AMAZON_ORDERS_URL)
            time.sleep(5)

            # Log de l'URL actuelle pour déboguer
            logger.info(f"URL apres navigation: {self.driver.current_url}")
            logger.info(f"Titre de la page: {self.driver.title}")

            # Vérifier qu'on est sur la page des commandes
            wait = WebDriverWait(self.driver, 20)
            wait.until(
                EC.presence_of_element_located((By.ID, "ordersContainer"))
            )
            logger.info("Page des commandes chargee")
            time.sleep(2)
            return True

        except Exception as e:
            logger.error(f"Erreur lors de la navigation: {str(e)}")
            return False
    
    def _log_order_html(self, order_element, index: int) -> None:
        """Log le HTML d'une commande pour debug (uniquement la première)."""
        if index == 0:
            try:
                html = order_element.get_attribute("outerHTML")
                # Tronquer à 3000 caractères pour les logs
                if len(html) > 3000:
                    html = html[:3000] + "... [tronqué]"
                logger.info(f"=== HTML de la commande #{index} ===\n{html}\n=== FIN HTML ===")
            except Exception as e:
                logger.warning(f"Impossible de logger le HTML: {e}")

    def _parse_order_date_from_element(self, order_element: Any) -> Optional[date_type]:
        """
        Parse la date de commande depuis le bloc commande (ex. "Commandé le 15 janvier 2025").
        Returns:
            date ou None si non trouvé
        """
        try:
            text = (order_element.text or "").strip()
            # FR: "Commandé le 15 janvier 2025", "15 janvier 2025", "15 janv. 2025"
            for pattern, repl in [
                (r"(?:Commandé le|Commande du)\s+(\d{1,2})\s+(\w+)\s+(\d{4})", None),
                (r"(\d{1,2})\s+(\w+)\s+(\d{4})", None),
            ]:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    day = int(match.group(1))
                    month_str = match.group(2).lower().rstrip(".")
                    year = int(match.group(3))
                    month = _MOIS_FR.get(month_str)
                    if month and 1 <= day <= 31 and 2020 <= year <= 2030:
                        return date_type(year, month, day)
            # EN: "Ordered on Jan 15, 2025", "Jan 15, 2025"
            en_months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                         "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
            match = re.search(r"(?:Ordered on\s+)?(\w{3})\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE)
            if match:
                month = en_months.get(match.group(1).lower())
                if month:
                    day = int(match.group(2))
                    year = int(match.group(3))
                    if 1 <= day <= 31 and 2020 <= year <= 2030:
                        return date_type(year, month, day)
        except Exception as e:
            logger.debug("Parse date commande: %s", e)
        return None

    def _get_order_id_from_element(self, order_element: Any, fallback_index: int) -> str:
        """Retourne l'identifiant de commande (data-order-id ou fallback)."""
        try:
            oid = order_element.get_attribute("data-order-id")
            if oid and oid.strip():
                return oid.strip()
        except Exception:
            pass
        try:
            for attr in ("id", "data-order-id"):
                val = order_element.get_attribute(attr) or ""
                if "order" in val.lower() and len(val) < 80:
                    return val
        except Exception:
            pass
        return f"order_{fallback_index}"

    def _count_existing_pdfs(self) -> int:
        """Compte les PDFs existants dans le dossier de téléchargement."""
        return len(list(self.download_path.glob("*.pdf")))

    def _find_popover_trigger(self, order_element) -> Optional[any]:
        """Trouve le bouton dropdown 'Facture' dans une commande Amazon."""
        # Sur Amazon.fr, le bouton "Facture ▽" est un <a> avec classe a-popover-trigger
        # ou un span.a-declarative contenant un lien avec le texte "Facture"
        trigger_selectors = [
            (By.CSS_SELECTOR, "a.a-popover-trigger"),
            (By.CSS_SELECTOR, ".a-popover-trigger"),
            (By.XPATH, ".//span[contains(@class, 'a-declarative')]//a"),
        ]
        for by, selector in trigger_selectors:
            try:
                elements = order_element.find_elements(by, selector)
                for elem in elements:
                    text = (elem.text or "").lower().strip()
                    if "facture" in text or "invoice" in text:
                        return elem
            except Exception:
                continue
        return None

    def _get_invoice_url_from_popover(self) -> Optional[str]:
        """Recupere l'URL du lien 'Facture' dans un popover Amazon ouvert."""
        popover_selectors = [
            (By.XPATH, "//div[contains(@class, 'a-popover') and not(contains(@style, 'display: none'))]//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'facture')]"),
            (By.CSS_SELECTOR, ".a-popover:not([style*='display: none']) .a-popover-content a[href*='invoice']"),
            (By.CSS_SELECTOR, ".a-popover:not([style*='display: none']) .a-popover-content a[href*='generated']"),
            (By.CSS_SELECTOR, ".a-popover:not([style*='display: none']) .a-popover-content a[href*='document']"),
            (By.XPATH, "//div[contains(@class, 'a-popover') and not(contains(@style, 'display: none'))]//ul//a"),
        ]

        for by, selector in popover_selectors:
            try:
                links = self.driver.find_elements(by, selector)
                for link in links:
                    text = (link.text or "").strip().lower()
                    href = (link.get_attribute("href") or "")
                    logger.info(f"  Popover lien: texte='{text}', href='{href[:100]}'")
                    # Prendre "Facture" mais pas "Recapitulatif de commande imprimable"
                    if text == "facture" or "invoice" in text.lower():
                        return href
                    if "invoice" in href.lower() or "document" in href.lower():
                        if "summary" not in href.lower() and "recap" not in href.lower():
                            return href
            except Exception:
                continue
        return None

    def _get_browser_cookies_session(self):
        """Cree une session requests avec les cookies du navigateur."""
        import requests as req
        session = req.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
        session.headers.update({
            'User-Agent': self.driver.execute_script("return navigator.userAgent;")
        })
        return session

    def _download_pdf_from_url(
        self,
        url: str,
        order_index: int,
        order_id: str = "",
        invoice_date: Optional[date_type] = None,
    ) -> Optional[str]:
        """Télécharge un PDF depuis une URL. Nom de fichier : amazon_YYYY-MM-DD_orderid.pdf si date dispo."""
        try:
            session = self._get_browser_cookies_session()
            logger.info("  Telechargement HTTP: %s...", url[:100])
            response = session.get(url, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                logger.warning("  HTTP %s pour %s", response.status_code, url[:80])
                return None

            content_type = response.headers.get("content-type", "").lower()
            is_pdf = "pdf" in content_type or response.content[:4] == b"%PDF"

            if not is_pdf:
                logger.warning("  Contenu non-PDF recu: %s", content_type)
                return None

            if invoice_date:
                safe_id = re.sub(r"[^\w\-]", "_", order_id or str(order_index))[:40]
                filename = f"amazon_{invoice_date.isoformat()}_{safe_id}.pdf"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"facture_{order_index}_{timestamp}.pdf"

            filepath = self.download_path / filename
            filepath.write_bytes(response.content)
            logger.info("  Facture sauvegardee: %s", filepath)
            return filename

        except Exception as e:
            logger.error("  Erreur telechargement HTTP: %s", e)
            return None

    def _close_all_popovers(self) -> None:
        """Ferme tous les popovers Amazon ouverts."""
        try:
            # Appuyer sur Escape pour fermer tout popover
            from selenium.webdriver.common.keys import Keys
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.3)
            # Aussi cacher via JS au cas ou
            self.driver.execute_script("""
                document.querySelectorAll('.a-popover').forEach(function(p) {
                    p.style.display = 'none';
                    p.style.visibility = 'hidden';
                });
                // Retirer les overlays Amazon
                document.querySelectorAll('.a-popover-wrapper, .a-popover-modal').forEach(function(o) {
                    o.remove();
                });
            """)
            time.sleep(0.3)
        except Exception:
            pass

    async def download_invoice(
        self,
        order_element: Any,
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date_type] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        """
        Télécharge la facture pour une commande donnée.
        Si la facture est déjà dans le registre et que force_redownload est False, skip.
        """
        try:
            oid = order_id or self._get_order_id_from_element(order_element, order_index)
            if not force_redownload and self.registry.is_downloaded(PROVIDER_AMAZON, oid):
                logger.info("Commande #%s (%s): deja telechargee, skip", order_index, oid)
                return None

            self._log_order_html(order_element, order_index)
            self._close_all_popovers()

            trigger = self._find_popover_trigger(order_element)
            if not trigger:
                logger.warning("Commande #%s: bouton 'Facture' non trouve", order_index)
                return None

            logger.info("Commande #%s: clic sur le dropdown 'Facture'...", order_index)
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger)
                time.sleep(0.5)
                trigger.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", trigger)
            time.sleep(2)

            invoice_url = self._get_invoice_url_from_popover()
            self._close_all_popovers()

            if not invoice_url:
                logger.warning("Commande #%s: URL facture non trouvee dans le popover", order_index)
                return None

            logger.info("Commande #%s: telechargement de la facture...", order_index)
            filename = self._download_pdf_from_url(
                invoice_url, order_index, order_id=oid, invoice_date=invoice_date
            )
            if filename:
                self.registry.add(
                    PROVIDER_AMAZON,
                    oid,
                    filename,
                    invoice_date=invoice_date.isoformat() if invoice_date else None,
                )
                logger.info("Commande #%s: OK - %s", order_index, filename)
            else:
                logger.warning("Commande #%s: echec du telechargement", order_index)
            return filename

        except Exception as e:
            logger.error("Commande #%s: erreur: %s", order_index, e)
            return None
    
    def _filter_orders_by_date(
        self,
        order_triples: List[Tuple[Any, str, Optional[date_type]]],
        year: Optional[int] = None,
        month: Optional[int] = None,
        months: Optional[List[int]] = None,
        date_start_str: Optional[str] = None,
        date_end_str: Optional[str] = None,
    ) -> List[Tuple[Any, str, Optional[date_type]]]:
        """
        Filtre les (order, order_id, date).
        Priorité : plage (date_start/date_end) > année + liste de mois > année + un mois > année seule.
        Si filtre actif, exclut les commandes sans date.
        """
        # Plage de dates
        if date_start_str and date_end_str:
            try:
                start_d = datetime.strptime(date_start_str, "%Y-%m-%d").date()
                end_d = datetime.strptime(date_end_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("Plage invalide date_start=%s date_end=%s, filtre plage ignoré", date_start_str, date_end_str)
                start_d = end_d = None
        else:
            start_d = end_d = None

        if start_d is not None and end_d is not None:
            out: List[Tuple[Any, str, Optional[date_type]]] = []
            for order, oid, d in order_triples:
                if d is None:
                    continue
                if start_d <= d <= end_d:
                    out.append((order, oid, d))
            return out

        # Année + plusieurs mois
        if year is not None and months:
            out = []
            for order, oid, d in order_triples:
                if d is None:
                    continue
                if d.year == year and d.month in months:
                    out.append((order, oid, d))
            return out

        # Année + un mois ou année seule
        if year is None and month is None:
            return order_triples
        out = []
        for order, oid, d in order_triples:
            if d is None:
                continue
            if year is not None and d.year != year:
                continue
            if month is not None and d.month != month:
                continue
            out.append((order, oid, d))
        return out

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
    ) -> Dict[str, Union[List[str], int]]:
        """
        Télécharge les factures Amazon.
        Filtre par plage (date_start/date_end), ou année + mois (months), ou year/month.
        Ne retélécharge pas les factures déjà enregistrées sauf force_redownload.
        """
        try:
            login_result = await self.login(otp_code=otp_code)
            if not login_result:
                if self._is_2fa_required():
                    raise Exception("Code 2FA requis - veuillez fournir le code OTP")
                raise Exception("Échec de la connexion à Amazon")

            if not await self.navigate_to_orders():
                raise Exception("Impossible d'accéder à la page des commandes")

            periods = self._get_amazon_periods_for_request(
                year=year, month=month, months=months,
                date_start=date_start, date_end=date_end,
            )
            logger.info("Période(s) Amazon à traiter (depuis le filtre interface): %s", periods)

            order_selectors = [
                "[data-order-id]",
                ".order-card",
                ".order",
                ".a-box-group.a-spacing-base.order",
                "div[id^='order-']",
                ".order-info",
            ]
            downloaded_files: List[str] = []
            count = 0
            global_order_index = 0

            for period_option in periods:
                if count >= max_invoices:
                    break
                self._select_orders_period(period_option)
                time.sleep(3)

                logger.info("Recherche des commandes sur la page (période: %s)...", period_option)
                orders = None
                for selector in order_selectors:
                    try:
                        orders = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if orders and len(orders) > 0:
                            logger.info("Commandes trouvees avec selecteur: %s", selector)
                            break
                    except Exception as e:
                        logger.warning("Erreur avec selecteur %s: %s", selector, e)
                        continue

                if not orders or len(orders) == 0:
                    logger.warning("Aucune commande pour la période %s; passage à la suivante.", period_option)
                    continue

                page_num = 1
                while True:
                    order_triples: List[Tuple[Any, str, Optional[date_type]]] = []
                    for i, order in enumerate(orders):
                        oid = self._get_order_id_from_element(order, global_order_index + i)
                        inv_date = self._parse_order_date_from_element(order)
                        order_triples.append((order, oid, inv_date))

                    filtered = self._filter_orders_by_date(
                        order_triples,
                        year=year,
                        month=month,
                        months=months,
                        date_start_str=date_start,
                        date_end_str=date_end,
                    )
                    if any([date_start, date_end, year is not None, month is not None, months]):
                        logger.info(
                            "Filtre date (year=%s month=%s months=%s plage=%s..%s): %s -> %s commandes",
                            year, month, months, date_start, date_end, len(order_triples), len(filtered)
                        )

                    to_process = min(len(filtered), max_invoices - count)
                    for j in range(to_process):
                        order, oid, inv_date = filtered[j]
                        try:
                            file_name = await self.download_invoice(
                                order,
                                order_index=global_order_index,
                                order_id=oid,
                                invoice_date=inv_date,
                                force_redownload=force_redownload,
                            )
                            if file_name:
                                downloaded_files.append(file_name)
                                count += 1
                            global_order_index += 1
                            time.sleep(1)
                        except Exception as e:
                            logger.warning("Erreur pour une commande: %s", e)
                            global_order_index += 1
                            continue

                    if count >= max_invoices:
                        logger.info("Limite de %s facture(s) atteinte", max_invoices)
                        break

                    if not self._has_next_orders_page():
                        logger.info("Pas de page suivante pour la période %s", period_option)
                        break
                    if not self._go_to_next_orders_page():
                        logger.warning("Impossible d'aller à la page suivante")
                        break

                    page_num += 1
                    logger.info("Récupération des commandes - période %s, page %s...", period_option, page_num)
                    orders = None
                    for selector in order_selectors:
                        try:
                            orders = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if orders and len(orders) > 0:
                                break
                        except Exception:
                            continue
                    if not orders or len(orders) == 0:
                        logger.info("Aucune commande sur la page suivante")
                        break
                    logger.info("%s commande(s) sur la page %s", len(orders), page_num)

            logger.info("Téléchargement terminé: %s facture(s) téléchargée(s)", count)
            return {"count": count, "files": downloaded_files}

        except Exception as e:
            logger.error("Erreur lors du téléchargement des factures: %s", e)
            raise
    
    async def close(self) -> None:
        """Ferme le navigateur (sauf si connexion continue ou mode manuel)."""
        if self.driver:
            # Connexion continue ou mode manuel : garder le navigateur ouvert
            if self.keep_browser_open or self.manual_mode:
                logger.info(
                    "Connexion continue activée - le navigateur reste ouvert. "
                    "Fermez-le manuellement si besoin."
                )
                return
            self.driver.quit()
            self.driver = None
            logger.info("Navigateur fermé")

