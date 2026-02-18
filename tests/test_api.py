"""
Tests pour l'API FastAPI (V2 multi-fournisseurs).
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.main import app, downloaders


@pytest.fixture
def client() -> TestClient:
    """Fixture pour créer un client de test."""
    return TestClient(app)


def test_root_endpoint(client: TestClient) -> None:
    """Test de l'endpoint racine."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_status_endpoint(client: TestClient) -> None:
    """Test de l'endpoint de statut."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "message" in data


def test_debug_endpoint(client: TestClient) -> None:
    """Test de l'endpoint de debug."""
    response = client.get("/api/debug")
    assert response.status_code == 200
    data = response.json()
    assert "downloaders" in data
    assert "settings_loaded" in data
    assert "has_email" in data
    assert "has_password" in data


def test_check_2fa_endpoint(client: TestClient) -> None:
    """Test de l'endpoint de vérification 2FA."""
    response = client.get("/api/check-2fa")
    # L'endpoint peut retourner 503 si le downloader n'est pas initialisé
    # ou 200 si tout va bien
    assert response.status_code in [200, 503]


def test_providers_endpoint(client: TestClient) -> None:
    """Test de l'endpoint liste des fournisseurs (V2)."""
    response = client.get("/api/providers")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    providers_list = data["providers"]
    assert isinstance(providers_list, list)
    ids = [p["id"] for p in providers_list]
    assert "amazon" in ids
    for p in providers_list:
        assert "id" in p and "name" in p and "configured" in p and "implemented" in p


def test_download_returns_503_when_downloader_unavailable(client: TestClient) -> None:
    """Le téléchargement retourne 503 quand le téléchargeur n'est pas disponible."""
    with patch("backend.main.downloaders", {}):
        response = client.post("/api/download", json={"max_invoices": 10})
    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "configuré" in detail or "initialisé" in detail


def test_submit_otp_returns_503_when_downloader_unavailable(client: TestClient) -> None:
    """Submit OTP retourne 503 quand le téléchargeur n'est pas disponible."""
    with patch("backend.main._get_downloader", return_value=None):
        response = client.post("/api/submit-otp", json={"otp_code": "123456"})
    assert response.status_code == 503

