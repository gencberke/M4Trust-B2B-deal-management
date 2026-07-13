"""Demo/test senaryo motoru — bir account_v2 işlemini YALNIZ gerçek servisleri
çağırarak adlandırılmış bir yaşam döngüsü durumuna ilerletir (Plan 14 / D1).

Bu modül **ham SQL ile business state yazmaz**: her adım gerçek servis yolunu
kullanır (`transaction_pipeline.run_pipeline`, `ParticipantService`,
`tracking_policy`, `RatificationPackageService`, `services/ratifications`,
`evidence_records`, `settlement.evaluate_settlement`, `disputes`). Bir guard'ı
ihlal edecek adım gerçek 409/exception'ı yüzeye çıkarır — durum zorlanmaz
(ARCHITECTURE §6, Plan 14 değişmez kuralı). Aynı modül hem seed CLI'ı hem D3
demo router'ı tarafından tüketilir (tek implementasyon, iki tüketici).

Adımlar idempotenttir: aynı `transaction_id` ile yeniden çalıştırma duplicate
üretmez ve mevcut ilerlemeyi korur.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from sqlite3 import Connection
from uuid import uuid4

from backend.app.config import Settings
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import entities as entities_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import users as users_repo
from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.schemas.tracking import TrackingMode
from backend.app.services import disputes as disputes_service
from backend.app.services import evidence_records as evidence_service
from backend.app.services import invitations as invitations_service
from backend.app.services import participants as participants_service
from backend.app.services import ratification_package as package_service
from backend.app.services import ratifications as ratifications_service
from backend.app.services import rule_versions
from backend.app.services import settlement
from backend.app.services import transaction_pipeline
from backend.app.services.access_control import ActorContext
from backend.app.services.auth import normalize_email
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.notifications import make_notification_provider
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services import processing_jobs
from backend.app.services.tracking_policy import (
    create_draft_policy,
    load_tracking_policy,
    lock_manager_policy,
    update_manager_policy,
)
from backend.app.schemas.tracking import TrackingPolicyStatus

# Adlandırılmış hedef durumlar (canonical account_v2 state + demo türevleri).
TARGET_STATES = (
    "awaiting_review",
    "awaiting_ratification",
    "active",
    "active_partial",
    "settled",
    "disputed",
)

_REQUEST_ID = "demo-scenarios"


class DemoScenarioError(Exception):
    """Demo senaryo motorunun kurtarılabilir hata kökü (yanlış hedef, eksik seed)."""


@dataclass(frozen=True)
class DemoEntityRef:
    """Bir demo tarafının kimliği — seed'li kullanıcı/entity ile eşleşir."""

    user_id: str
    entity_id: str
    email: str
    display_name: str
    tax_id: str


@dataclass(frozen=True)
class DemoParties:
    """İşlemi başlatan (buyer/manager) ve karşı taraf (seller)."""

    buyer: DemoEntityRef
    seller: DemoEntityRef


# Seed'li demo kimlikleri — `scripts/seed_demo_users.py` ile e-posta/legal_name
# olarak eşleşir; buyer=işlemi başlatan/manager, seller=karşı taraf.
_SEED_BUYER = {
    "email": "berke@m4trust.demo",
    "legal_name": "ABC Sanayi ve Ticaret A.Ş.",
    "tax_id": "1111111111",
}
_SEED_SELLER = {
    "email": "yusuf@m4trust.demo",
    "legal_name": "XYZ Lojistik Ltd. Şti.",
    "tax_id": "2222222222",
}


def _resolve_seed_ref(conn: Connection, spec: dict) -> DemoEntityRef:
    normalized = normalize_email(spec["email"])
    user = users_repo.get_user_by_email(conn, normalized)
    if user is None:
        raise DemoScenarioError(
            f"Seed'li demo user bulunamadı: {normalized} (önce seed_demo_users çalıştırın)."
        )
    entities = entities_repo.list_entities_for_user(conn, user["id"])
    entity = next((row for row in entities if row["legal_name"] == spec["legal_name"]), None)
    if entity is None:
        raise DemoScenarioError(f"Seed'li demo entity bulunamadı: {spec['legal_name']}.")
    return DemoEntityRef(
        user_id=user["id"],
        entity_id=entity["id"],
        email=normalized,
        display_name=spec["legal_name"],
        tax_id=spec["tax_id"],
    )


def resolve_seeded_demo_parties(conn: Connection) -> DemoParties:
    """Seed'li Berke/Yusuf + ABC/XYZ'den `DemoParties` çözer (CLI + demo router paylaşır)."""
    return DemoParties(
        buyer=_resolve_seed_ref(conn, _SEED_BUYER),
        seller=_resolve_seed_ref(conn, _SEED_SELLER),
    )


def _actor(ref: DemoEntityRef) -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=ref.user_id,
        acting_entity_id=ref.entity_id,
        auth_method="session",
        request_id=_REQUEST_ID,
    )


# --- sözleşme metni (marker'lı, deterministik başlıklı) ----------------------


def _contract_markdown(*, profile: str, title: str) -> str:
    """Fake extraction profilini seçen marker'ı taşıyan passthrough markdown."""
    return (
        f"<!-- [[m4trust-fake-profile: {profile}]] -->\n\n"
        f"# {title}\n\n"
        "Bu sözleşme M4Trust demo/test senaryo motoru tarafından üretilmiştir.\n"
        f"Fake extraction profili: `{profile}`.\n"
    )


# --- adım 1: create_uploaded -------------------------------------------------


def _transaction_row(conn: Connection, transaction_id: str):
    return conn.execute(
        "SELECT id, state, lifecycle_version FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()


def create_uploaded(
    conn: Connection,
    settings: Settings,
    *,
    transaction_id: str,
    parties: DemoParties,
    profile: str,
    title: str,
) -> str:
    """Account_v2 işlemi oluşturur ve extraction pipeline'ını senkron çalıştırır.

    Idempotent: transaction zaten varsa hiçbir şey yapmaz. Gerçek create yolu
    (`routers/transactions.py::_create_account_transaction`) ile aynı servisleri
    kullanır; pipeline `run_pipeline` üzerinden gerçek convert→extract→validate
    zincirini işletir (fake profil marker'la seçilir).
    """
    if _transaction_row(conn, transaction_id) is not None:
        return transaction_id

    buyer = parties.buyer
    document_id = uuid4().hex
    markdown = _contract_markdown(profile=profile, title=title)
    content = markdown.encode("utf-8")
    content_sha256 = hashlib.sha256(content).hexdigest()

    storage = make_document_storage_provider(settings)
    stored = storage.store(
        transaction_id=transaction_id,
        document_id=document_id,
        original_filename=f"{title}.md",
        media_type="text/markdown",
        content=content,
        expected_sha256=content_sha256,
    )

    conn.execute(
        "INSERT INTO transactions "
        "(id, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, "
        "created_at, created_by_user_id, owner_entity_id, lifecycle_version, content_sha256) "
        "VALUES (?, 'uploaded', NULL, NULL, NULL, NULL, NULL, 'now', ?, ?, 'account_v2', ?)",
        (transaction_id, buyer.user_id, buyer.entity_id, content_sha256),
    )
    create_draft_policy(conn, transaction_id)
    documents_repo.insert_document(
        conn,
        document_id=document_id,
        transaction_id=transaction_id,
        version=1,
        original_filename=f"{title}.md",
        media_type="text/markdown",
        storage_ref=stored.storage_ref,
        content_sha256=stored.content_sha256,
        uploaded_by_user_id=buyer.user_id,
        now="now",
    )
    participants_service.attach_creator(
        conn, transaction_id, _actor(buyer), "buyer", buyer.entity_id
    )
    participants_service.create_counterparty_placeholder(conn, transaction_id, "seller", None)
    processing_jobs.ensure_job(
        conn,
        kind="extraction",
        source_id=transaction_id,
        transaction_id=transaction_id,
        idempotency_key=f"extraction:transaction:{transaction_id}",
    )
    conn.commit()

    # Pipeline kendi arka plan bağlantısını açar; create commit'i sonrası çağırılır
    # ki storage/transaction satırı görünür olsun (gerçek BackgroundTasks davranışı).
    transaction_pipeline.run_pipeline(
        transaction_id,
        True,  # is_passthrough — markdown doğrudan okunur
        settings,
        transaction_pipeline.AccountPipelineInput(
            document_id=document_id, storage_ref=stored.storage_ref, suffix=".md"
        ),
    )
    return transaction_id


# --- adım 2: attach_and_confirm_parties --------------------------------------


def _seller_participant(conn: Connection, transaction_id: str):
    return participants_repo.get_participant(conn, transaction_id, "seller")


def attach_and_confirm_parties(
    conn: Connection, *, transaction_id: str, parties: DemoParties
) -> None:
    """Karşı tarafı gerçek davet+accept ile bağlar ve iki tarafın profilini onaylar.

    Idempotent: seller zaten bağlıysa yeni davet üretilmez; confirmed profil
    yeniden confirm edilmez.
    """
    buyer, seller = parties.buyer, parties.seller

    seller_row = _seller_participant(conn, transaction_id)
    if seller_row is not None and seller_row["legal_entity_id"] is None:
        created = invitations_service.create_invitation(
            conn,
            transaction_id,
            "seller",
            normalize_email(seller.email),
            _actor(buyer),
            make_notification_provider(),
            invite_link_builder=lambda raw_token: f"/api/invitations/{raw_token}/accept",
        )
        participants_service.accept_invitation(
            conn, created.raw_token, _actor(seller), seller.entity_id
        )

    for ref, role in ((buyer, "buyer"), (seller, "seller")):
        _confirm_profile(conn, transaction_id, ref)


def _confirm_profile(conn: Connection, transaction_id: str, ref: DemoEntityRef) -> None:
    actor = _actor(ref)
    my_participant = participants_service.get_my_participant_for_actor(
        conn, transaction_id, actor
    )
    if my_participant is None:
        raise DemoScenarioError(
            f"{ref.entity_id} için bu işlemde bağlı participant bulunamadı."
        )
    if my_participant.status.value == "confirmed":
        return
    participants_service.update_declared_profile(
        conn,
        transaction_id,
        actor,
        {"name": ref.display_name, "tax_id": ref.tax_id},
    )
    participants_service.confirm_my_profile(conn, transaction_id, actor)


# --- adım 3: lock_policy -----------------------------------------------------


def _current_extraction(conn: Connection, transaction_id: str) -> ExtractionJSON:
    current = rule_versions.get_current(conn, transaction_id)
    if current is None or current.extraction is None:
        raise DemoScenarioError(
            "Doğrulanmış rule set bulunamadı; extraction PASS almadı (policy kilitlenemez)."
        )
    return current.extraction


def _natural_tracking_mode(extraction: ExtractionJSON) -> TrackingMode:
    """Sözleşmesel kanıta göre doğal takip modu (§6.10/§6.12)."""
    required = set()
    for rule in extraction.payment_rules:
        required.update(rule.required_evidence)
    if RequiredEvidence.video in required:
        return TrackingMode.document_and_video
    if RequiredEvidence.e_irsaliye in required:
        return TrackingMode.document_only
    return TrackingMode.off


def lock_policy(conn: Connection, *, transaction_id: str, parties: DemoParties) -> None:
    """Takip politikasını sözleşmesel kanıta göre doğal modda kilitler (idempotent)."""
    policy = load_tracking_policy(conn, transaction_id)
    if policy is not None and policy.status is TrackingPolicyStatus.locked:
        return  # zaten kilitli — idempotent no-op

    extraction = _current_extraction(conn, transaction_id)
    mode = _natural_tracking_mode(extraction)
    physical = mode is not TrackingMode.off

    _, _, conflict = update_manager_policy(
        conn,
        transaction_id,
        extraction,
        physical_delivery_confirmed=physical,
        tracking_mode=mode,
        configured_by_user_id=parties.buyer.user_id,
    )
    if conflict is not None:
        raise DemoScenarioError(f"Policy güncelleme çelişkisi: {conflict.conflicts}")

    _, _, conflict = lock_manager_policy(
        conn, transaction_id, extraction, locked_by_user_id=parties.buyer.user_id
    )
    if conflict is not None:
        raise DemoScenarioError(f"Policy kilit çelişkisi: {conflict.conflicts}")


# --- adım 4: build_package ---------------------------------------------------


def build_package(conn: Connection, *, transaction_id: str, parties: DemoParties):
    """Current package'ı build + open eder (idempotent). Package döner."""
    package = package_service.build_current_package(
        conn,
        transaction_id=transaction_id,
        funding_schedule_spec=FundingScheduleSpec(),
        capabilities=MOKA_STANDARD_PROFILE,
        actor_context=_actor(parties.buyer),
    )
    package = package_service.open_package(
        conn, package_id=package.id, actor_context=_actor(parties.buyer)
    )
    return package


# --- adım 5: ratify ----------------------------------------------------------


def ratify(conn: Connection, *, transaction_id: str, parties: DemoParties, role: str) -> None:
    """Belirtilen tarafın (buyer/seller) current package'ı ratify etmesi (idempotent).

    İkinci ratification `FundingCoordinator.ensure_pool_funded`'ı tetikler ve
    işlemi `active`'e taşır (gerçek servis; provider mock/fake).
    """
    package = package_service.get_current(conn, transaction_id)
    if package is None:
        raise DemoScenarioError("Ratify için current package yok (önce build_package).")
    ref = parties.buyer if role == "buyer" else parties.seller
    ratifications_service.create_ratification(
        conn, package_id=package.id, actor_context=_actor(ref), auth_method="session"
    )


# --- adım 6: submit_eirsaliye ------------------------------------------------


def submit_eirsaliye(
    conn: Connection,
    settings: Settings,
    *,
    transaction_id: str,
    parties: DemoParties,
    quantity: float,
    reference: str,
    milestone_id: str | None = None,
) -> dict | None:
    """Seller adına verified e-irsaliye kaydeder ve settlement'ı yeniden değerlendirir.

    `milestone_id` verilmezse tek aday milestone'a bağlanır; çoklu adayda ilk
    (en düşük sequence) milestone seçilir (deterministik demo davranışı).
    """
    if milestone_id is None:
        rows = milestones_repo.list_for_transaction(conn, transaction_id)
        if len(rows) > 1:
            milestone_id = sorted(rows, key=lambda r: r["rule_index"])[0]["id"]

    evidence_service.submit_evidence(
        conn,
        transaction_id=transaction_id,
        milestone_id=milestone_id,
        evidence_type="e_irsaliye",
        source="external_api",
        actor_context=_actor(parties.seller),
        payload={"delivered_quantity": quantity},
        verification_status="verified",
        external_reference=reference,
    )
    result = settlement.evaluate_settlement(conn, transaction_id, settings)
    conn.commit()
    return result


# --- adım 7: dispute ---------------------------------------------------------


def open_demo_dispute(
    conn: Connection,
    *,
    transaction_id: str,
    parties: DemoParties,
    reason_code: str = "QUALITY_ISSUE",
    description: str = "Demo senaryosu: teslimat itirazi.",
) -> None:
    """Seller approver adına gerçek dispute açar (idempotent — zaten açıksa yutar)."""
    try:
        disputes_service.open_dispute(
            conn,
            transaction_id=transaction_id,
            milestone_id=None,
            reason_code=reason_code,
            description=description,
            actor_context=_actor(parties.seller),
        )
    except disputes_service.DisputeAlreadyOpenError:
        return


# --- orkestrasyon ------------------------------------------------------------

# Hedef state → gereken fake profil.
_PROFILE_FOR_TARGET = {
    "awaiting_review": "review",
    "awaiting_ratification": "delivery",
    "active": "delivery",
    "active_partial": "delivery",
    "settled": "delivery",
    "disputed": "delivery",
}


_FUNDED_STATES = frozenset({"active", "settled", "funding_pending"})


def _to_active(conn: Connection, settings: Settings, transaction_id: str, parties: DemoParties):
    """awaiting_review sonrası → active'e kadar ortak merdiven (idempotent).

    İşlem zaten fonlanmışsa (active/settled/funding_pending) pre-funding
    merdiveni atlanır — package post-funding değiştirilemez (gerçek 409 guard).
    """
    row = _transaction_row(conn, transaction_id)
    if row is not None and row["state"] in _FUNDED_STATES:
        return

    attach_and_confirm_parties(conn, transaction_id=transaction_id, parties=parties)
    lock_policy(conn, transaction_id=transaction_id, parties=parties)
    build_package(conn, transaction_id=transaction_id, parties=parties)
    ratify(conn, transaction_id=transaction_id, parties=parties, role="buyer")
    ratify(conn, transaction_id=transaction_id, parties=parties, role="seller")


def advance(
    conn: Connection,
    settings: Settings,
    *,
    transaction_id: str,
    target_state: str,
    parties: DemoParties,
) -> dict:
    """Var olan bir account_v2 işlemini `target_state`'e kadar gerçek servislerle ilerletir.

    Guard ihlali gerçek exception/409 olarak yüzer (state zorlanmaz). Zaten
    hedefte/ilerideyse idempotent no-op'a yaklaşır.
    """
    if target_state not in TARGET_STATES:
        raise DemoScenarioError(
            f"Bilinmeyen hedef durum: {target_state!r} (geçerli: {', '.join(TARGET_STATES)})."
        )

    row = _transaction_row(conn, transaction_id)
    if row is None:
        raise DemoScenarioError(f"İşlem bulunamadı: {transaction_id!r}.")
    if row["lifecycle_version"] != "account_v2":
        raise DemoScenarioError("Demo advance yalnız account_v2 işlemler içindir.")

    if target_state == "awaiting_review":
        # Pipeline zaten NEEDS_REVIEW → awaiting_review üretmiş olmalı.
        conn.commit()
        return _status(conn, transaction_id)

    if target_state == "awaiting_ratification":
        attach_and_confirm_parties(conn, transaction_id=transaction_id, parties=parties)
        lock_policy(conn, transaction_id=transaction_id, parties=parties)
        build_package(conn, transaction_id=transaction_id, parties=parties)
        conn.commit()
        return _status(conn, transaction_id)

    # active / active_partial / settled / disputed hepsi active tabanı ister.
    _to_active(conn, settings, transaction_id, parties)

    if target_state == "active":
        conn.commit()
        return _status(conn, transaction_id)

    if target_state == "disputed":
        open_demo_dispute(conn, transaction_id=transaction_id, parties=parties)
        conn.commit()
        return _status(conn, transaction_id)

    if target_state == "active_partial":
        # Tek milestone'a kısmi teslim; diğer(ler)i pending kalır.
        submit_eirsaliye(
            conn, settings, transaction_id=transaction_id, parties=parties,
            quantity=5.0, reference=f"demo-irsaliye-partial-{transaction_id[:8]}",
        )
        return _status(conn, transaction_id)

    if target_state == "settled":
        # Tüm milestone'lara tam teslim → tüm unit'ler release → settled.
        rows = sorted(
            milestones_repo.list_for_transaction(conn, transaction_id),
            key=lambda r: r["rule_index"],
        )
        for index, milestone in enumerate(rows):
            submit_eirsaliye(
                conn, settings, transaction_id=transaction_id, parties=parties,
                quantity=10.0, reference=f"demo-irsaliye-full-{transaction_id[:8]}-{index}",
                milestone_id=milestone["id"],
            )
        return _status(conn, transaction_id)

    raise DemoScenarioError(f"Ele alınmayan hedef: {target_state!r}")  # pragma: no cover


def create_scenario(
    conn: Connection,
    settings: Settings,
    *,
    scenario: str,
    parties: DemoParties,
    transaction_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Taze bir account_v2 işlemi oluşturup `scenario` durumuna ilerletir.

    `transaction_id`/`title` verilmezse deterministik olmayan/UUID türetilir;
    seed CLI deterministik başlık geçirerek idempotent kalır.
    """
    if scenario not in TARGET_STATES:
        raise DemoScenarioError(
            f"Bilinmeyen senaryo: {scenario!r} (geçerli: {', '.join(TARGET_STATES)})."
        )
    tx_id = transaction_id or uuid4().hex
    profile = _PROFILE_FOR_TARGET[scenario]
    scenario_title = title or f"Demo — {scenario}"

    create_uploaded(
        conn, settings, transaction_id=tx_id, parties=parties,
        profile=profile, title=scenario_title,
    )
    return advance(
        conn, settings, transaction_id=tx_id, target_state=scenario, parties=parties
    )


def _status(conn: Connection, transaction_id: str) -> dict:
    row = _transaction_row(conn, transaction_id)
    return {
        "transaction_id": transaction_id,
        "state": row["state"] if row is not None else None,
        "lifecycle_version": row["lifecycle_version"] if row is not None else None,
    }
