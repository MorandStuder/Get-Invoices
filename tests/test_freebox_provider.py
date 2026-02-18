"""
Tests du provider Freebox (Espace abonné).
"""
import pytest
from backend.providers.freebox import FreeboxProvider, PROVIDER_FREEBOX


def test_freebox_provider_id() -> None:
    assert FreeboxProvider.PROVIDER_ID == PROVIDER_FREEBOX
    assert FreeboxProvider.PROVIDER_ID == "freebox"


def test_freebox_provider_init() -> None:
    p = FreeboxProvider(
        login="test@free.fr",
        password="secret",
        download_path="./test_factures_freebox",
    )
    assert p.provider_id == "freebox"
    assert p.login == "test@free.fr"
    assert p.download_path.name == "test_factures_freebox"


def test_freebox_list_orders_no_driver() -> None:
    p = FreeboxProvider(login="a", password="b", download_path="./test_freebox")
    assert p.list_orders_or_invoices() == []


@pytest.mark.asyncio
async def test_freebox_close_no_driver() -> None:
    p = FreeboxProvider(login="a", password="b", download_path="./test_freebox")
    await p.close()
    assert p.driver is None
