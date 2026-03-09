"""
Tests du provider Bouygues Telecom (mode semi-manuel).
"""

import tempfile
from pathlib import Path

import pytest

from backend.providers.bouygues import PROVIDER_BOUYGUES, BouyguesProvider


def test_bouygues_provider_id() -> None:
    assert BouyguesProvider.PROVIDER_ID == PROVIDER_BOUYGUES
    assert BouyguesProvider.PROVIDER_ID == "bouygues"


def test_bouygues_provider_init() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = BouyguesProvider(
            login="test@example.com",
            password="secret",
            download_path=tmp,
        )
        assert p.provider_id == "bouygues"
        assert p.login_identifier == "test@example.com"
        assert Path(p.download_path) == Path(tmp)


def test_bouygues_list_orders_no_driver() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = BouyguesProvider(login="a", password="b", download_path=tmp)
        assert p.list_orders_or_invoices() == []


def test_bouygues_parse_invoice_date_basic() -> None:
    """Parsing très simple de dates YYYY-MM / YYYY/MM dans les textes."""
    with tempfile.TemporaryDirectory() as tmp:
        p = BouyguesProvider(login="a", password="b", download_path=tmp)
        assert p._parse_invoice_date_from_text("Facture 2024-06") is not None
        assert p._parse_invoice_date_from_text("2023/12") is not None
        assert p._parse_invoice_date_from_text("pas de date") is None


def test_bouygues_is_2fa_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = BouyguesProvider(login="a", password="b", download_path=tmp)
        assert p.is_2fa_required() is False


@pytest.mark.asyncio
async def test_bouygues_close_no_driver() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = BouyguesProvider(login="a", password="b", download_path=tmp)
        await p.close()
        assert p.driver is None
