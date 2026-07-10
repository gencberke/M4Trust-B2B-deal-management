"""PaymentProvider adapter — Moka United havuz ödeme contract'ı (§3.3).

`PaymentProvider` gerçek Moka API'sinin beş metodunu tanımlar; `MockMokaProvider`
gerçek HTTP çağrısı yapmaz, `mock_payments` tablosunu kendi basit deftereri
(simüle edilmiş ledger) olarak kullanır. Cevap şekli gerçek Moka response'una
birebir uyar (`ResultCode`, `Data.IsSuccessful`, `Data.VirtualPosOrderId`) —
böylece v1'de gerçek `RealMokaProvider` yalnızca bu adaptörün altını değiştirir,
akış kodu (routers/decision) etkilenmez (§6.3 adapter+fake ilkesi).

Release (approve) çağrısını yalnızca deterministik akış (routers/approvals +
decision) tetikler; bu modül kendi başına yetkilendirme kararı vermez (§6.1).
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.config import Settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _moka_success(virtual_pos_order_id: str) -> dict:
    """Gerçek Moka başarı cevabının şekli — tüm başarılı metotlar bunu döner."""

    return {
        "ResultCode": "Success",
        "ResultMessage": "",
        "Data": {
            "IsSuccessful": True,
            "VirtualPosOrderId": virtual_pos_order_id,
            "ResultCode": "",
            "ResultMessage": "",
        },
    }


def _moka_failure(message: str) -> dict:
    """Gerçek Moka hata cevabının şekli — bilinmeyen kayıt/başarısız işlem."""

    return {
        "ResultCode": "Failed",
        "ResultMessage": message,
        "Data": {
            "IsSuccessful": False,
            "VirtualPosOrderId": "",
            "ResultCode": "Failed",
            "ResultMessage": message,
        },
    }


class PaymentProvider(ABC):
    """Moka havuz ödeme contract'ının adapter arayüzü (§3.3, beş metot)."""

    @abstractmethod
    def create_pool_payment(self, *, amount: float, currency: str, other_trx_code: str) -> dict:
        """Havuz ödemesi oluşturur (Moka `IsPoolPayment=1`) — para tahsil edilir, tutulur."""

    @abstractmethod
    def get_payment_status(self, *, other_trx_code: str) -> dict:
        """Ödeme/transaction durumunu döner (Moka ödeme/transaction listesi)."""

    @abstractmethod
    def approve_pool_payment(self, *, other_trx_code: str, capture_ratio: float = 1.0) -> dict:
        """Havuzdaki tutarı serbest bırakır (Moka `/PaymentDealer/DoApprovePoolPayment`)."""

    @abstractmethod
    def undo_approve_pool_payment(self, *, other_trx_code: str) -> dict:
        """Serbest bırakmayı geri alır (Moka `/PaymentDealer/UndoApprovePoolPayment`)."""

    @abstractmethod
    def refund_payment(self, *, other_trx_code: str) -> dict:
        """Ödemeyi iade eder."""


class MockMokaProvider(PaymentProvider):
    """`mock_payments` tablosunu ledger olarak kullanan mock Moka adaptörü.

    Gerçek provider HTTP çağrısı yapardı; bu mock aynı contract şeklini
    üretip durumu lokal DB'de tutar. Metotlar `conn.commit()` ÇAĞIRMAZ —
    transaction'ın sahibi çağıran taraftır (router/request); bu sınıf yalnızca
    `execute` eder, commit/rollback çağıranın sorumluluğundadır.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _find_row(self, other_trx_code: str) -> sqlite3.Row | None:
        cursor = self._conn.execute(
            "SELECT * FROM mock_payments WHERE other_trx_code = ?",
            (other_trx_code,),
        )
        return cursor.fetchone()

    def create_pool_payment(self, *, amount: float, currency: str, other_trx_code: str) -> dict:
        # `currency` contract fidelity için kabul edilir; mock tek para birimiyle
        # çalıştığından ayrıca saklanmaz (gerçek provider'da Moka'ya geçilir).
        existing = self._find_row(other_trx_code)
        if existing is not None:
            # İdempotent: aynı other_trx_code için ikinci kayıt açılmaz.
            return _moka_success(existing["virtual_pos_order_id"])

        virtual_pos_order_id = f"ORDER-{uuid4()}"
        self._conn.execute(
            """
            INSERT INTO mock_payments
                (transaction_id, other_trx_code, virtual_pos_order_id, status, amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (other_trx_code, other_trx_code, virtual_pos_order_id, "pool", amount, _utc_now_iso()),
        )
        return _moka_success(virtual_pos_order_id)

    def get_payment_status(self, *, other_trx_code: str) -> dict:
        row = self._find_row(other_trx_code)
        if row is None:
            return _moka_failure("Kayıt bulunamadı")
        envelope = _moka_success(row["virtual_pos_order_id"])
        envelope["Data"]["status"] = row["status"]
        return envelope

    def approve_pool_payment(self, *, other_trx_code: str, capture_ratio: float = 1.0) -> dict:
        row = self._find_row(other_trx_code)
        if row is None:
            return _moka_failure("Kayıt bulunamadı")
        if row["status"] != "pool":
            return _moka_failure("Ödeme havuz durumunda değil")

        if capture_ratio >= 1.0:
            new_status = "released"
        elif capture_ratio > 0:
            # `mock_payments` şemasında tek bir `amount` kolonu var, ayrı bir
            # `released_amount` yok; bu yüzden kısmi serbest bırakma durumu
            # `status="partially_released"` ile kodlanır — kalan tutar
            # kavramsal olarak hâlâ havuzdadır, ayrı bir satıra bölünmez.
            new_status = "partially_released"
        else:
            return _moka_failure("Geçersiz capture_ratio")

        self._conn.execute(
            "UPDATE mock_payments SET status = ? WHERE other_trx_code = ?",
            (new_status, other_trx_code),
        )
        return _moka_success(row["virtual_pos_order_id"])

    def undo_approve_pool_payment(self, *, other_trx_code: str) -> dict:
        """Serbest bırakmayı geri alır.

        Gerçek Moka'da bu işlem yalnızca gün sonu/bayi ekstresi kapanmadan
        önce geçerlidir — sınırsız bir geri alma değildir. Mock bu kısıtı
        modellemez (demo kapsamı), gerçek adaptörde eklenmesi gerekir.
        """

        row = self._find_row(other_trx_code)
        if row is None:
            return _moka_failure("Kayıt bulunamadı")

        self._conn.execute(
            "UPDATE mock_payments SET status = ? WHERE other_trx_code = ?",
            ("pool", other_trx_code),
        )
        return _moka_success(row["virtual_pos_order_id"])

    def refund_payment(self, *, other_trx_code: str) -> dict:
        row = self._find_row(other_trx_code)
        if row is None:
            return _moka_failure("Kayıt bulunamadı")

        self._conn.execute(
            "UPDATE mock_payments SET status = ? WHERE other_trx_code = ?",
            ("refunded", other_trx_code),
        )
        return _moka_success(row["virtual_pos_order_id"])


def make_payment_provider(settings: Settings, conn: sqlite3.Connection) -> PaymentProvider:
    """`settings.payment_provider`'a göre adaptör seçer (§3.3 seçim env'i)."""

    if settings.payment_provider == "mock":
        return MockMokaProvider(conn)
    raise NotImplementedError(f"Bilinmeyen payment provider: {settings.payment_provider}")
