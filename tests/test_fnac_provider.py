"""
Tests du provider FNAC (Espace client fnac.com).
"""

import tempfile
from datetime import date
from pathlib import Path

import pytest

from backend.providers.fnac import PROVIDER_FNAC, FnacProvider


def test_fnac_provider_id() -> None:
    assert FnacProvider.PROVIDER_ID == PROVIDER_FNAC
    assert FnacProvider.PROVIDER_ID == "fnac"


def test_fnac_provider_init() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(
            login="test@example.com",
            password="secret",
            download_path=tmp,
        )
        assert p.provider_id == "fnac"
        assert p._login == "test@example.com"
        assert Path(p.download_path) == Path(tmp)


def test_fnac_list_orders_no_driver() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        assert p.list_orders_or_invoices() == []


def test_fnac_parse_invoice_date_mois_fr() -> None:
    """Test du parsing des dates au format 'mois année' (français)."""
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        assert p._parse_invoice_date("janvier 2024") == date(2024, 1, 1)
        assert p._parse_invoice_date("février 2023") == date(2023, 2, 1)
        assert p._parse_invoice_date("décembre 2025") == date(2025, 12, 1)
        assert p._parse_invoice_date("Facture novembre 2022") == date(2022, 11, 1)


def test_fnac_parse_invoice_date_iso() -> None:
    """Test du parsing des dates au format YYYY-MM ou YYYY/M."""
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        assert p._parse_invoice_date("2024-06") == date(2024, 6, 1)
        assert p._parse_invoice_date("2023/12") == date(2023, 12, 1)


def test_fnac_parse_invoice_date_invalid() -> None:
    """Dates invalides ou vides retournent None."""
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        assert p._parse_invoice_date("") is None
        assert p._parse_invoice_date("pas de date") is None
        assert p._parse_invoice_date("1999-01") is None  # année hors plage
        assert p._parse_invoice_date("2101-01") is None  # année hors plage 2000-2100


def test_fnac_is_2fa_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        assert p.is_2fa_required() is False


@pytest.mark.asyncio
async def test_fnac_close_no_driver() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = FnacProvider(login="a", password="b", download_path=tmp)
        await p.close()
        assert p.driver is None
