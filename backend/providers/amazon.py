"""
Provider Amazon : enveloppe le service existant AmazonInvoiceDownloader
pour respecter l'interface InvoiceProviderProtocol (V2).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union, Awaitable

from backend.providers.base import OrderInfo
from backend.services.amazon_downloader import AmazonInvoiceDownloader


class AmazonProvider:
    """
    Fournisseur Amazon implémentant InvoiceProviderProtocol.
    Délègue au service backend.services.amazon_downloader pour éviter toute duplication.
    """

    PROVIDER_ID = "amazon"

    def __init__(
        self,
        email: str,
        password: str,
        download_path: Union[str, Path],
        headless: bool = False,
        timeout: int = 30,
        otp_callback: Optional[Callable[[], Awaitable[str]]] = None,
        manual_mode: bool = False,
        browser: str = "chrome",
        firefox_profile_path: Optional[str] = None,
        chrome_user_data_dir: Optional[str] = None,
        keep_browser_open: bool = False,
    ) -> None:
        self._downloader = AmazonInvoiceDownloader(
            email=email,
            password=password,
            download_path=str(download_path),
            headless=headless,
            timeout=timeout,
            otp_callback=otp_callback,
            manual_mode=manual_mode,
            browser=browser,
            firefox_profile_path=firefox_profile_path,
            chrome_user_data_dir=chrome_user_data_dir,
            keep_browser_open=keep_browser_open,
        )

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    async def login(self, otp_code: Optional[str] = None) -> bool:
        return await self._downloader.login(otp_code=otp_code)

    async def navigate_to_invoices(self) -> bool:
        return await self._downloader.navigate_to_orders()

    def list_orders_or_invoices(self) -> List[OrderInfo]:
        """Amazon gère tout dans download_invoices ; liste vide ici (optionnel)."""
        return []

    async def download_invoice(
        self,
        order_or_id: Any,
        order_index: int = 0,
        order_id: str = "",
        invoice_date: Optional[date] = None,
        force_redownload: bool = False,
    ) -> Optional[str]:
        return await self._downloader.download_invoice(
            order_or_id,
            order_index=order_index,
            order_id=order_id or (str(order_or_id) if isinstance(order_or_id, str) else ""),
            invoice_date=invoice_date,
            force_redownload=force_redownload,
        )

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
        return await self._downloader.download_invoices(
            max_invoices=max_invoices,
            year=year,
            month=month,
            months=months,
            date_start=date_start,
            date_end=date_end,
            otp_code=otp_code,
            force_redownload=force_redownload,
        )

    async def close(self) -> None:
        await self._downloader.close()

    def is_2fa_required(self) -> bool:
        return self._downloader.is_2fa_required()

    async def submit_otp(self, otp_code: str) -> bool:
        return await self._downloader.submit_otp(otp_code)
