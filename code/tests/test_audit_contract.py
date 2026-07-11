"""`backend.app.services.audit` kontrat testleri.

Bu aşamada `audit_events` tablosu yoktur (migration 006, Plan 03); testler
`record()`'un (a) allowlist/redaksiyon kurallarını DB'den önce uyguladığını ve
(b) kendi connection'ını asla açmadığını/commit etmediğini kilitler.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.app.services.audit import AuditActor, DisallowedMetadataError, record


class _NoIOConnection:
    """`conn` üzerinde HİÇBİR I/O çağrısı yapılmadığını kanıtlayan sentinel.

    Herhangi bir attribute erişimi (execute/commit/rollback/close/cursor...)
    testi düşürür — `record()`'un iskelet aşamasında `conn`'a hiç dokunmaması
    gerektiğini doğrudan kanıtlar.
    """

    def __getattr__(self, name: str):  # noqa: D105
        raise AssertionError(f"record() conn.{name} çağırmamalı (henüz tablo yok).")


@pytest.fixture()
def actor() -> AuditActor:
    return AuditActor(actor_type="anonymous")


def test_record_never_opens_its_own_connection(monkeypatch: pytest.MonkeyPatch, actor) -> None:
    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("audit.record() kendi sqlite3.connect()'ini açmamalı.")

    monkeypatch.setattr(sqlite3, "connect", _forbidden_connect)

    with pytest.raises(NotImplementedError):
        record(_NoIOConnection(), actor, "review.approve", "transaction:1", frozenset({"note"}))


def test_record_does_not_touch_connection_object(actor) -> None:
    with pytest.raises(NotImplementedError):
        record(_NoIOConnection(), actor, "review.approve", "transaction:1", frozenset())


def test_record_rejects_metadata_outside_allowlist(actor) -> None:
    with pytest.raises(DisallowedMetadataError):
        record(
            _NoIOConnection(),
            actor,
            "review.approve",
            "transaction:1",
            frozenset({"note"}),
            metadata={"note": "ok", "extra_field": "not allowed"},
        )


@pytest.mark.parametrize(
    "forbidden_key",
    ["token", "buyer_token", "password", "checkkey", "card_token", "pan", "cvc", "cvv", "iban", "tckn"],
)
def test_record_rejects_forbidden_key_patterns_even_if_allowlisted(
    actor, forbidden_key: str
) -> None:
    with pytest.raises(DisallowedMetadataError):
        record(
            _NoIOConnection(),
            actor,
            "review.approve",
            "transaction:1",
            frozenset({forbidden_key}),
            metadata={forbidden_key: "irrelevant"},
        )


def test_record_allows_empty_metadata_with_empty_allowlist(actor) -> None:
    with pytest.raises(NotImplementedError):
        record(_NoIOConnection(), actor, "review.approve", "transaction:1", frozenset())


def test_record_allows_metadata_within_allowlist_and_reaches_skeleton_notimplemented(
    actor,
) -> None:
    with pytest.raises(NotImplementedError):
        record(
            _NoIOConnection(),
            actor,
            "review.approve",
            "transaction:1",
            frozenset({"note", "severity"}),
            metadata={"note": "ok", "severity": "low"},
        )


def test_metadata_validation_runs_before_notimplemented_is_raised(actor) -> None:
    # Sıra kritik: yasak alan varsa NotImplementedError'a hiç ulaşılmamalı.
    with pytest.raises(DisallowedMetadataError):
        record(
            _NoIOConnection(),
            actor,
            "review.approve",
            "transaction:1",
            frozenset({"password"}),
            metadata={"password": "x"},
        )
