"""Frozen `EvidenceService` (Plan 05 / Faz 5A, v2 §4.5/§5.16-5.17/§8.6).

```python
submit_evidence(conn, *, transaction_id, milestone_id, evidence_type, source,
                 actor_context, payload, verification_status,
                 external_reference=None, storage_ref=None, file_sha256=None,
                 analyzer_provider=None, analyzer_version=None) -> EvidenceRecord
verify_evidence(conn, *, evidence_id, verification_status, actor_context) -> EvidenceRecord
collect_transaction_delivery_evidence(conn, transaction_id) -> DeliveryEvidence
collect_milestone_evidence(conn, transaction_id, milestone_id) -> list[EvidenceRecord]
```

Bu dört imza donmuştur. HTTP/FastAPI bilmez, payment provider çağırmaz,
çağıranın connection'ını commit etmez. Idempotency, DB unique constraint'lerini
(`UNIQUE(transaction_id, evidence_type, external_reference)`,
`UNIQUE(transaction_id, file_sha256)`) source of truth kabul eder — uygulama
katmanındaki ön-kontrol yalnız hızlı yoldur, gerçek garanti DB'dedir (eşzamanlı
yarışta `sqlite3.IntegrityError` yakalanıp mevcut kayıt fetch edilir).

`collect_transaction_delivery_evidence`'ın `legacy_v1` dalı, `services/
settlement.py::_latest_evidence_payload`'ın (dokunulmadı, private) davranışını
BİREBİR tekrar eder — event tablosundaki en son `%e_irsaliye%`/`%video%`
event'inin payload'ını okur. Settlement bağlantısı (bu fonksiyonun
`decide()`'a beslenmesi) Berke'nin entegrasyon işidir.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from typing import Literal
from uuid import uuid4

from backend.app.eventbus import emit
from backend.app.repositories import evidence as evidence_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.services import audit
from backend.app.services.access_control import ActorContext
from backend.app.services.decision import DeliveryEvidence

EvidenceType = Literal["contract", "e_irsaliye", "video", "e_invoice", "other"]
EvidenceSource = Literal["upload", "external_api", "analyzer", "system"]
VerificationStatus = Literal["received", "verified", "rejected", "review_required"]

_REJECTED_STATUS = "rejected"


class EvidenceError(Exception):
    """Evidence domain hatalarının kökü."""


class EvidenceNotFoundError(EvidenceError):
    """Belirtilen evidence kaydı bulunamadı."""


class EvidenceIdempotencyConflictError(EvidenceError):
    """Aynı `(transaction_id, evidence_type, external_reference)` veya
    `(transaction_id, file_sha256)` farklı canonical içerikle yeniden
    gönderildi — fail closed (sessiz overwrite yok)."""

    def __init__(self, message: str) -> None:
        self.code = "EVIDENCE_IDEMPOTENCY_CONFLICT"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """`evidence_records` satırının servis-katmanı görünümü."""

    id: str
    transaction_id: str
    milestone_id: str | None
    evidence_type: EvidenceType
    source: EvidenceSource
    submitted_by_user_id: str
    submitted_by_entity_id: str
    external_reference: str | None
    storage_ref: str | None
    file_sha256: str | None
    payload: dict
    verification_status: VerificationStatus
    analyzer_provider: str | None
    analyzer_version: str | None
    created_at: str
    verified_at: str | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_payload_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_to_record(row: Row) -> EvidenceRecord:
    return EvidenceRecord(
        id=row["id"],
        transaction_id=row["transaction_id"],
        milestone_id=row["milestone_id"],
        evidence_type=row["evidence_type"],
        source=row["source"],
        submitted_by_user_id=row["submitted_by_user_id"],
        submitted_by_entity_id=row["submitted_by_entity_id"],
        external_reference=row["external_reference"],
        storage_ref=row["storage_ref"],
        file_sha256=row["file_sha256"],
        payload=json.loads(row["payload_json"]),
        verification_status=row["verification_status"],
        analyzer_provider=row["analyzer_provider"],
        analyzer_version=row["analyzer_version"],
        created_at=row["created_at"],
        verified_at=row["verified_at"],
    )


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _existing_for_identity(
    conn: Connection, *, transaction_id: str, evidence_type: str, external_reference: str | None,
    file_sha256: str | None,
) -> Row | None:
    if external_reference is not None:
        row = evidence_repo.get_by_external_reference(
            conn, transaction_id=transaction_id, evidence_type=evidence_type,
            external_reference=external_reference,
        )
        if row is not None:
            return row
    if file_sha256 is not None:
        return evidence_repo.get_by_file_sha256(
            conn, transaction_id=transaction_id, file_sha256=file_sha256
        )
    return None


def submit_evidence(
    conn: Connection,
    *,
    transaction_id: str,
    milestone_id: str | None,
    evidence_type: EvidenceType,
    source: EvidenceSource,
    actor_context: ActorContext,
    payload: dict,
    verification_status: VerificationStatus,
    external_reference: str | None = None,
    storage_ref: str | None = None,
    file_sha256: str | None = None,
    analyzer_provider: str | None = None,
    analyzer_version: str | None = None,
) -> EvidenceRecord:
    """Yeni bir evidence kaydı ekler; aynı identity (external_reference veya
    file_sha256) + aynı canonical payload için idempotenttir (yeni event YOK).
    Farklı payload'la yeniden gönderilirse `EvidenceIdempotencyConflictError`."""
    if actor_context.user_id is None or actor_context.acting_entity_id is None:
        raise EvidenceError("submit_evidence authenticated user + acting_entity_id gerektirir.")

    canonical_payload_json = _canonical_payload_json(payload)

    existing = _existing_for_identity(
        conn, transaction_id=transaction_id, evidence_type=evidence_type,
        external_reference=external_reference, file_sha256=file_sha256,
    )
    if existing is not None:
        if existing["payload_json"] == canonical_payload_json:
            return _row_to_record(existing)
        raise EvidenceIdempotencyConflictError(
            f"Aynı kimlikle (evidence_type={evidence_type!r}, "
            f"external_reference={external_reference!r}, file_sha256={file_sha256!r}) "
            "farklı içerikli bir kanıt zaten var."
        )

    record_id = uuid4().hex
    created_at = _utc_now_iso()
    try:
        evidence_repo.insert(
            conn,
            id=record_id,
            transaction_id=transaction_id,
            milestone_id=milestone_id,
            evidence_type=evidence_type,
            source=source,
            submitted_by_user_id=actor_context.user_id,
            submitted_by_entity_id=actor_context.acting_entity_id,
            external_reference=external_reference,
            storage_ref=storage_ref,
            file_sha256=file_sha256,
            payload_json=canonical_payload_json,
            verification_status=verification_status,
            analyzer_provider=analyzer_provider,
            analyzer_version=analyzer_version,
            created_at=created_at,
        )
    except sqlite3.IntegrityError:
        # UNIQUE yarışı: source of truth DB'dir -- eşzamanlı ikinci istek
        # idempotent olarak mevcut satırı döner (aynı içerikse), farklıysa
        # fail-closed reddedilir.
        raced = _existing_for_identity(
            conn, transaction_id=transaction_id, evidence_type=evidence_type,
            external_reference=external_reference, file_sha256=file_sha256,
        )
        if raced is None:
            raise
        if raced["payload_json"] == canonical_payload_json:
            return _row_to_record(raced)
        raise EvidenceIdempotencyConflictError(
            f"Aynı kimlikle (evidence_type={evidence_type!r}) farklı içerikli "
            "bir kanıt zaten var (eşzamanlı yarış)."
        ) from None

    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="evidence.submitted",
        target=f"evidence_record:{record_id}",
        metadata_allowlist=frozenset({"evidence_type", "source", "verification_status"}),
        metadata={
            "evidence_type": evidence_type,
            "source": source,
            "verification_status": verification_status,
        },
        transaction_id=transaction_id,
    )

    emit(
        conn,
        transaction_id,
        "evidence_submitted",
        {
            "evidence_id": record_id,
            "evidence_type": evidence_type,
            "verification_status": verification_status,
        },
        source,
    )

    return _row_to_record(evidence_repo.get_by_id(conn, record_id))


def verify_evidence(
    conn: Connection, *, evidence_id: str, verification_status: VerificationStatus,
    actor_context: ActorContext,
) -> EvidenceRecord:
    """Mevcut kaydın `verification_status`'ünü değiştirir (bound alanlar sabit kalır)."""
    row = evidence_repo.get_by_id(conn, evidence_id)
    if row is None:
        raise EvidenceNotFoundError(evidence_id)

    verified_at = _utc_now_iso()
    evidence_repo.mark_verified(
        conn, evidence_id=evidence_id, verification_status=verification_status, verified_at=verified_at
    )
    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="evidence.verified",
        target=f"evidence_record:{evidence_id}",
        metadata_allowlist=frozenset({"verification_status"}),
        metadata={"verification_status": verification_status},
        transaction_id=row["transaction_id"],
    )
    return _row_to_record(evidence_repo.get_by_id(conn, evidence_id))


def _legacy_latest_event_payload(conn: Connection, transaction_id: str, event_term: str) -> dict | None:
    """`services/settlement.py::_latest_evidence_payload`'ın birebir eşdeğeri
    (private olduğu için import edilemez; settlement.py'ye dokunulmaz)."""
    row = conn.execute(
        "SELECT * FROM events WHERE transaction_id = ? AND event_type LIKE ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id, f"%{event_term}%"),
    ).fetchone()
    if row is None:
        return None
    for column in ("payload_json", "data_json", "payload", "data"):
        if column not in row.keys() or row[column] is None:
            continue
        try:
            value = json.loads(row[column]) if isinstance(row[column], str) else row[column]
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def collect_transaction_delivery_evidence(conn: Connection, transaction_id: str) -> DeliveryEvidence:
    """Lifecycle-bağımsız merkezi kanıt okuma kapısı. `decision.py` değişmez;
    yalnız `DeliveryEvidence`'ın nasıl doldurulduğu değişir."""
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        return DeliveryEvidence(e_irsaliye=None, video=None)

    if transaction["lifecycle_version"] == "account_v2":
        e_irsaliye_row = evidence_repo.latest_for_type(
            conn, transaction_id=transaction_id, evidence_type="e_irsaliye"
        )
        video_row = evidence_repo.latest_for_type(
            conn, transaction_id=transaction_id, evidence_type="video"
        )
        return DeliveryEvidence(
            e_irsaliye=json.loads(e_irsaliye_row["payload_json"]) if e_irsaliye_row is not None else None,
            video=json.loads(video_row["payload_json"]) if video_row is not None else None,
        )

    return DeliveryEvidence(
        e_irsaliye=_legacy_latest_event_payload(conn, transaction_id, "e_irsaliye"),
        video=_legacy_latest_event_payload(conn, transaction_id, "video"),
    )


def collect_milestone_evidence(
    conn: Connection, transaction_id: str, milestone_id: str
) -> list[EvidenceRecord]:
    """Belirli bir milestone'a bağlı kanıt kayıtları (Plan 06 milestone modeli
    için hazırlık — bu fazda `milestones` tablosu yok, yalnız FK'siz
    `milestone_id` filtreli okuma sağlanır)."""
    return [
        _row_to_record(row)
        for row in evidence_repo.list_for_milestone(
            conn, transaction_id=transaction_id, milestone_id=milestone_id
        )
    ]
