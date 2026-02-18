"""
Tests unitaires pour le service AmazonInvoiceDownloader.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from backend.services.amazon_downloader import AmazonInvoiceDownloader


@pytest.fixture
def downloader() -> AmazonInvoiceDownloader:
    """Fixture pour créer une instance de téléchargeur."""
    return AmazonInvoiceDownloader(
        email="test@example.com",
        password="test_password",
        download_path="./test_factures",
        headless=True
    )


@pytest.mark.asyncio
async def test_login_success(downloader: AmazonInvoiceDownloader) -> None:
    """Test de connexion réussie."""
    with patch.object(downloader, '_setup_driver') as mock_setup:
        mock_driver = Mock()
        mock_setup.return_value = mock_driver

        # Configurer le driver mock
        mock_driver.get = Mock()
        mock_driver.find_element = Mock()
        mock_driver.execute_cdp_cmd = Mock()
        mock_driver.current_url = "https://www.amazon.fr/"
        mock_driver.title = "Amazon.fr"
        mock_driver.page_source = "<html>Amazon page</html>"

        # Mock des éléments de la page
        email_input = Mock()
        email_input.clear = Mock()
        email_input.send_keys = Mock()

        password_input = Mock()
        password_input.clear = Mock()
        password_input.send_keys = Mock()

        continue_button = Mock()
        continue_button.click = Mock()

        sign_in_button = Mock()
        sign_in_button.click = Mock()

        account_link = Mock()

        def find_element_side_effect(by, value):
            if value == "ap_email":
                return email_input
            elif value == "ap_password":
                return password_input
            elif value == "continue":
                return continue_button
            elif value == "signInSubmit":
                return sign_in_button
            elif value == "nav-link-accountList" or value == "nav-orders":
                return account_link
            raise Exception(f"Element not found: {value}")

        mock_driver.find_element.side_effect = find_element_side_effect

        # Utiliser WebDriverWait mock
        with patch('backend.services.amazon_downloader.WebDriverWait') as mock_wait, \
             patch.object(downloader, '_is_2fa_required', return_value=False), \
             patch('backend.services.amazon_downloader.time.sleep'):  # Skip sleep pour accélérer
            mock_wait_instance = Mock()
            mock_wait.return_value = mock_wait_instance

            # Mock de wait.until pour retourner les éléments attendus
            def wait_until_side_effect(condition):
                # Retourner le bon élément selon le contexte
                try:
                    # Essayer d'appeler la condition pour voir ce qu'elle cherche
                    result = condition(mock_driver)
                    return result if result else email_input
                except:
                    # Si ça échoue, retourner l'élément par défaut
                    return email_input

            mock_wait_instance.until = Mock(side_effect=wait_until_side_effect)

            result = await downloader.login()
            assert result is True

            # Vérifier que les méthodes ont été appelées
            mock_driver.get.assert_called()
            email_input.send_keys.assert_called_once_with("test@example.com")
            password_input.send_keys.assert_called_once_with("test_password")


def test_init_download_path(downloader: AmazonInvoiceDownloader) -> None:
    """Test que le dossier de téléchargement est créé."""
    import os
    assert os.path.exists(downloader.download_path)


@pytest.mark.asyncio
async def test_close(downloader: AmazonInvoiceDownloader) -> None:
    """Test de fermeture du navigateur."""
    mock_driver = Mock()
    downloader.driver = mock_driver

    await downloader.close()

    mock_driver.quit.assert_called_once()
    assert downloader.driver is None


@pytest.mark.asyncio
async def test_close_manual_mode(downloader: AmazonInvoiceDownloader) -> None:
    """Test que le navigateur reste ouvert en mode manuel."""
    downloader.manual_mode = True
    mock_driver = Mock()
    downloader.driver = mock_driver

    await downloader.close()

    # En mode manuel, quit() ne doit PAS être appelé
    mock_driver.quit.assert_not_called()
    # Le driver reste assigné
    assert downloader.driver is mock_driver


@pytest.mark.asyncio
async def test_close_keep_browser_open(downloader: AmazonInvoiceDownloader) -> None:
    """Test que le navigateur reste ouvert quand connexion continue est activée."""
    downloader.keep_browser_open = True
    mock_driver = Mock()
    downloader.driver = mock_driver

    await downloader.close()

    mock_driver.quit.assert_not_called()
    assert downloader.driver is mock_driver


def test_is_2fa_required_no_driver(downloader: AmazonInvoiceDownloader) -> None:
    """Test que is_2fa_required retourne False sans driver."""
    assert downloader.is_2fa_required() is False


def test_has_next_orders_page_no_driver(downloader: AmazonInvoiceDownloader) -> None:
    """Sans driver, _has_next_orders_page retourne False."""
    assert downloader._has_next_orders_page() is False


def test_go_to_next_orders_page_no_driver(downloader: AmazonInvoiceDownloader) -> None:
    """Sans driver, _go_to_next_orders_page retourne False."""
    assert downloader._go_to_next_orders_page() is False


def test_has_next_orders_page_with_driver_no_next(downloader: AmazonInvoiceDownloader) -> None:
    """Avec driver mais sans lien page suivante, retourne False."""
    mock_driver = Mock()
    mock_driver.find_elements = Mock(return_value=[])
    downloader.driver = mock_driver
    assert downloader._has_next_orders_page() is False


def test_is_2fa_required_with_otp_field(downloader: AmazonInvoiceDownloader) -> None:
    """Test de détection 2FA avec champ OTP présent."""
    mock_driver = Mock()
    downloader.driver = mock_driver

    # Mock un élément OTP trouvé
    mock_otp_element = Mock()
    mock_driver.find_element = Mock(return_value=mock_otp_element)
    mock_driver.page_source = "code de vérification"

    assert downloader.is_2fa_required() is True


@pytest.mark.asyncio
async def test_submit_otp_without_driver(downloader: AmazonInvoiceDownloader) -> None:
    """Test submit_otp démarre le login si pas de driver."""
    with patch.object(downloader, 'login', new_callable=AsyncMock) as mock_login:
        mock_login.return_value = True

        result = await downloader.submit_otp("123456")

        mock_login.assert_called_once_with(otp_code="123456")
        assert result is True


@pytest.mark.asyncio
async def test_navigate_to_orders(downloader: AmazonInvoiceDownloader) -> None:
    """Test de navigation vers la page des commandes."""
    mock_driver = Mock()
    downloader.driver = mock_driver

    # Mock un élément de la page des commandes
    mock_orders_container = Mock()

    with patch('backend.services.amazon_downloader.WebDriverWait') as mock_wait, \
         patch('backend.services.amazon_downloader.time.sleep'):
        mock_wait_instance = Mock()
        mock_wait.return_value = mock_wait_instance
        mock_wait_instance.until = Mock(return_value=mock_orders_container)

        result = await downloader.navigate_to_orders()

        assert result is True
        mock_driver.get.assert_called_once_with("https://www.amazon.fr/gp/css/order-history")

