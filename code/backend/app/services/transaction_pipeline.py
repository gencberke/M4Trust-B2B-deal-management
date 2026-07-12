"""Sözleşme upload pipeline'ı (Plan 04 / Faz 4A) — `routers/transactions.py`'den taşındı.

convert -> `privacy.analyze()` -> `ContextBuilder.build()` -> blocking-check ->
extract -> restore -> schema validate ortak çekirdektir (CLI ile aynı sıra,
§6.7); ardından persistence lifecycle'a göre dallanır:

- **legacy_v1**: `extracted_rules`'a yazar — DAVRANIŞ DEĞİŞMEDİ.
- **account_v2**: `contract_documents` (normalized markdown hash) +
  `extraction_runs` (immutable, adapter'dan dönen RESTORE ÖNCESİ ham payload)
  + (yalnız extraction başarılıysa) `rule_set_versions` initial version —
  `extracted_rules`'a YAZMAZ.

State/event semantiği iki mod için ortaktır (§13): state transitions +
`contract_extracted`/`rules_validated` event'leri + PASS'ta tracking policy
önerisi Plan 03'ten devralınan, değiştirilmeyen davranıştır.

Account modda ham upload byte'ları `DocumentStorageProvider`'dan okunur —
request-scope temp dosyası kalıcı source of truth DEĞİLDİR (§4); pipeline
kendi geçici çalışma dosyasını storage'dan yeniden üretir.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from importlib.metadata import PackageNotFoundError, version as package_version
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from pydantic import ValidationError

from scripts.document_parser import DocumentConverter

from backend.app.config import Settings
from backend.app.db import open_background_connection
from backend.app.eventbus import emit
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import extraction_runs as extraction_runs_repo
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services import processing_jobs
from backend.app.services import review as review_service
from backend.app.services import rule_versions
from backend.app.services.access_control import ActorContext
from backend.app.services.context_builder import ContextBuilder, ContextPack
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.extraction import make_extraction_service
from backend.app.services.privacy import PrivacyReport, analyze, restore
from backend.app.services.rag import Retriever
from backend.app.services.tracking_policy import (
    recommend_physical_delivery,
    update_system_recommendation,
)
from backend.app.services.validator import validate

# §9: extraction davranışından bağımsız, merkezi sabitler.
EXTRACTION_PROMPT_VERSION = "v1"
EXTRACTION_SCHEMA_VERSION = "v1"
_FAKE_MODEL_ID = "fake-extraction-v1"

_VALIDATOR_STATUS_TO_STATE = {
    "PASS": "awaiting_approval",
    "NEEDS_REVIEW": "awaiting_review",
    "REJECT": "rejected",
}

# extraction_runs.failure_reason — yalnız bu sabit, güvenli kategorilerden
# biri yazılır; ham adapter hata mesajı/traceback/document metni ASLA girmez.
_SAFE_FAILURE_REASON = {
    "blocking": "Hassas ödeme doğrulama verisi tespit edildi; dış LLM çağrısı atlandı.",
    "extraction_failed": "Extraction sağlayıcısı geçerli bir sonuç üretemedi.",
    "restore_invalid": "Restore sonrası şema doğrulaması başarısız oldu.",
    "pipeline_error": "Pipeline işlenirken beklenmeyen bir hata oluştu.",
}

_CARD_SAD_TYPES = {"TRACK_DATA", "CVV", "PIN"}


@dataclass(frozen=True, slots=True)
class LegacyPipelineInput:
    """`legacy_v1` raw upload, durably encrypted before dispatch."""

    storage_ref: str
    suffix: str


@dataclass(frozen=True, slots=True)
class AccountPipelineInput:
    """`account_v2` — kalıcı storage'dan okunur; request temp dosyası kullanılmaz."""

    document_id: str
    storage_ref: str
    suffix: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_risk_flags(payload: dict, risk_flags: list[str], *, needs_review: bool) -> dict:
    """`privacy_report.risk_flags`'i extraction JSON'a birleştirir (şema değişmez).

    `scripts/extract_contract.py::_merge_risk_flags` ile aynı küçük mantık —
    plan gereği import edilmez, bağımsız olarak yeniden uygulanır.
    """
    existing = list(payload.get("risk_flags") or [])
    for flag in risk_flags:
        if flag not in existing:
            existing.append(flag)
    payload["risk_flags"] = existing
    if needs_review:
        payload["needs_manual_review"] = True
    return payload


def _rag_provenance(context: ContextPack | None) -> list[dict]:
    """Yalnız seçilmiş kaynakların güvenli metadata'sı — tam metin/prompt asla girmez."""
    if context is None:
        return []
    return [
        {
            "source": src.source,
            "source_type": src.source_type,
            "collection": src.collection,
            "madde_no": src.madde_no,
            "heading": src.heading,
            "score": src.score,
            "chunk_id": src.chunk_id,
            "collection_version": src.collection_version,
        }
        for src in context.sources
    ]


def _rag_collection_versions(context: ContextPack | None) -> dict[str, list[str]]:
    versions: dict[str, set[str]] = {}
    if context is not None:
        for source in context.sources:
            value = source.collection_version or "unversioned"
            versions.setdefault(source.collection, set()).add(value)
    return {name: sorted(values) for name, values in sorted(versions.items())}


def _llm_provider_version(provider: str) -> str:
    if provider != "openai":
        return "fake-extraction-v1"
    try:
        return package_version("openai")
    except PackageNotFoundError:
        return "unknown"


def _privacy_summary(report: PrivacyReport) -> dict:
    """Yalnız güvenli özet — placeholder mapping/orijinal PII/PAN/CVV/IBAN asla girmez."""
    return {
        "detected_types": sorted(report.detected_types),
        "risk_flags": list(report.risk_flags),
        "blocking_finding_codes": sorted(report.detected_types & _CARD_SAD_TYPES),
        "mapping_count": len(report.mapping),
    }


def _apply_success_side_effects(
    conn: Connection,
    transaction_id: str,
    extraction: ExtractionJSON,
    validator_status: str,
    findings_payload: list[dict],
) -> None:
    """State transition + `contract_extracted`/`rules_validated` event'leri + PASS'ta policy önerisi.

    Legacy ve account modun ortak, DEĞİŞMEYEN davranışı (§13).
    """
    new_state = _VALIDATOR_STATUS_TO_STATE[validator_status]
    conn.execute("UPDATE transactions SET state = ? WHERE id = ?", (new_state, transaction_id))

    emit(
        conn,
        transaction_id,
        "contract_extracted",
        {
            "parties": {
                "buyer_name": extraction.parties.buyer.name,
                "seller_name": extraction.parties.seller.name,
            },
            "currency": extraction.commercial_terms.currency.value,
            "total_amount": extraction.commercial_terms.total_amount,
            "num_rules": len(extraction.payment_rules),
        },
        "pipeline",
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {"status": validator_status, "findings": findings_payload},
        "validator",
    )
    if validator_status == "PASS":
        recommendation = recommend_physical_delivery(extraction)
        policy = update_system_recommendation(conn, transaction_id, recommendation)
        if policy is not None:
            emit(
                conn,
                transaction_id,
                "tracking_policy_recommended",
                {
                    "recommendation": recommendation.recommendation.value,
                    "reason_codes": [reason.value for reason in recommendation.reason_codes],
                },
                "tracking_policy",
            )


def _apply_no_extraction_side_effects(conn: Connection, transaction_id: str, safe_message: str) -> None:
    """Geçerli extraction üretilemediğinde ortak state/event davranışı (§13).

    `safe_message` yalnız `_SAFE_FAILURE_REASON`'daki sabit kategorilerden biri
    olmalıdır -- ham provider/exception mesajı (`extraction.py::ExtractionResult
    .reason`, `str(exc)`) buraya ASLA girmez; aksi halde `rules_validated`
    event'i (kalıcı `events` tablosu) üzerinden PII/secret/provider-detayı
    sızabilir (Bloklayıcı 1).
    """
    conn.execute(
        "UPDATE transactions SET state = 'awaiting_review' WHERE id = ?", (transaction_id,)
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {
            "status": "NEEDS_REVIEW",
            "findings": [
                {"code": "EXTRACTION_UNAVAILABLE", "severity": "review", "message": safe_message}
            ],
        },
        "pipeline",
    )


def _persist_legacy(
    conn: Connection,
    transaction_id: str,
    settings: Settings,
    extraction: ExtractionJSON | None,
    safe_reason_key: str,
) -> None:
    """`legacy_v1` — `extracted_rules`'a yazar (mevcut davranış, DEĞİŞMEDİ).

    `safe_reason_key`, `_SAFE_FAILURE_REASON`'daki sabit kategorilerden biridir
    -- ham adapter/exception mesajı `extracted_rules.validator_report`'a
    ASLA yazılmaz (Bloklayıcı 1).
    """
    if extraction is not None:
        validator_report = validate(
            extraction, confidence_threshold=settings.validator_confidence_threshold
        )
        findings_payload = [
            {"code": f.code, "severity": f.severity, "message": f.message}
            for f in validator_report.findings
        ]
        conn.execute(
            "INSERT INTO extracted_rules "
            "(transaction_id, extraction_json, validator_status, validator_report, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                transaction_id,
                json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False),
                validator_report.status,
                json.dumps(findings_payload, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )
        _apply_success_side_effects(
            conn, transaction_id, extraction, validator_report.status, findings_payload
        )
    else:
        safe_message = _SAFE_FAILURE_REASON[safe_reason_key]
        conn.execute(
            "INSERT INTO extracted_rules "
            "(transaction_id, extraction_json, validator_status, validator_report, created_at) "
            "VALUES (?, NULL, 'NEEDS_REVIEW', ?, ?)",
            (transaction_id, safe_message, _utc_now_iso()),
        )
        _apply_no_extraction_side_effects(conn, transaction_id, safe_message)


def _persist_account(
    conn: Connection,
    transaction_id: str,
    document_id: str,
    settings: Settings,
    context: ContextPack | None,
    privacy_report: PrivacyReport,
    extraction: ExtractionJSON | None,
    raw_result_data: ExtractionJSON | None,
    safe_reason_key: str,
    conversion_provenance: dict,
) -> None:
    """`account_v2` — `contract_documents`/`extraction_runs`/`rule_set_versions`'a yazar.

    Normal başarı yolunda `extracted_rules`'a YAZILMAZ (§10).
    """
    run_id = uuid4().hex
    now = _utc_now_iso()
    provider = settings.llm_provider
    model = settings.llm_model if settings.llm_provider == "openai" else _FAKE_MODEL_ID
    rag_provenance_json = json.dumps(_rag_provenance(context), ensure_ascii=False)
    privacy_summary_json = json.dumps(_privacy_summary(privacy_report), ensure_ascii=False)

    if extraction is not None:
        extraction_runs_repo.insert_extraction_run(
            conn,
            run_id=run_id,
            transaction_id=transaction_id,
            document_id=document_id,
            provider=provider,
            model=model,
            prompt_version=EXTRACTION_PROMPT_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            rag_provenance_json=rag_provenance_json,
            privacy_summary_json=privacy_summary_json,
            extraction_json=(
                json.dumps(raw_result_data.model_dump(mode="json"), ensure_ascii=False)
                if raw_result_data is not None
                else None
            ),
            status="ok",
            failure_reason=None,
            now=now,
            ocr_engine=conversion_provenance.get("ocr_engine"),
            ocr_version=conversion_provenance.get("ocr_version"),
            ocr_confidence=conversion_provenance.get("ocr_confidence"),
            llm_provider_version=_llm_provider_version(provider),
            rag_collection_versions_json=json.dumps(
                _rag_collection_versions(context), sort_keys=True
            ),
            source_locator_json=json.dumps(
                {
                    "document_engine": conversion_provenance.get("document_engine"),
                    "document_engine_version": conversion_provenance.get(
                        "document_engine_version"
                    ),
                    "page_count": conversion_provenance.get("page_count"),
                    "ocr_pages": conversion_provenance.get("ocr_pages", []),
                },
                sort_keys=True,
            ),
        )
        rule_version = rule_versions.create_initial_from_extraction(
            conn,
            transaction_id=transaction_id,
            extraction_run_id=run_id,
            rules_payload=extraction.model_dump(mode="json"),
            created_by_actor_type="system",
        )
        validated = rule_versions.validate_version(
            conn,
            version_id=rule_version.id,
            confidence_threshold=settings.validator_confidence_threshold,
        )
        review_service.open_validator_case(
            conn,
            transaction_id=transaction_id,
            source_id=validated.id,
            validator_status=validated.validator_status or "",
            finding_codes=[
                finding["code"]
                for finding in (validated.validator_report or [])
                if isinstance(finding, dict) and isinstance(finding.get("code"), str)
            ],
            actor_context=ActorContext(actor_type="anonymous"),
        )
        _apply_success_side_effects(
            conn, transaction_id, extraction, validated.validator_status, validated.validator_report
        )
    else:
        extraction_runs_repo.insert_extraction_run(
            conn,
            run_id=run_id,
            transaction_id=transaction_id,
            document_id=document_id,
            provider=provider,
            model=model,
            prompt_version=EXTRACTION_PROMPT_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            rag_provenance_json=rag_provenance_json,
            privacy_summary_json=privacy_summary_json,
            extraction_json=None,
            status="needs_review",
            failure_reason=_SAFE_FAILURE_REASON[safe_reason_key],
            now=now,
            ocr_engine=conversion_provenance.get("ocr_engine"),
            ocr_version=conversion_provenance.get("ocr_version"),
            ocr_confidence=conversion_provenance.get("ocr_confidence"),
            llm_provider_version=_llm_provider_version(provider),
            rag_collection_versions_json=json.dumps(
                _rag_collection_versions(context), sort_keys=True
            ),
            source_locator_json=json.dumps(
                {
                    "document_engine": conversion_provenance.get("document_engine"),
                    "document_engine_version": conversion_provenance.get(
                        "document_engine_version"
                    ),
                    "page_count": conversion_provenance.get("page_count"),
                    "ocr_pages": conversion_provenance.get("ocr_pages", []),
                },
                sort_keys=True,
            ),
        )
        _apply_no_extraction_side_effects(conn, transaction_id, _SAFE_FAILURE_REASON[safe_reason_key])


def _execute_pipeline(
    conn: Connection,
    transaction_id: str,
    file_path: Path,
    is_passthrough: bool,
    settings: Settings,
    account_input: AccountPipelineInput | None,
) -> None:
    """convert -> analyze -> ContextBuilder -> blocking-check -> extract -> restore -> validate."""
    if is_passthrough:
        markdown = file_path.read_text(encoding="utf-8")
        conversion_provenance = {
            "document_engine": "utf8-passthrough",
            "document_engine_version": "v1",
            "ocr_engine": None,
            "ocr_version": None,
            "ocr_confidence": None,
            "page_count": None,
            "ocr_pages": [],
        }
    else:
        converter = DocumentConverter()
        markdown = converter.convert(file_path)
        conversion_provenance = converter.last_provenance

    report = analyze(markdown)  # §6.7: mask + kart-verisi sınıflandırma (canlı çağrıdan ÖNCE)
    storage = make_document_storage_provider(settings)
    base_id = account_input.document_id if account_input is not None else "legacy-v1"
    markdown_bytes = markdown.encode("utf-8")
    masked_bytes = report.masked_text.encode("utf-8")
    markdown_stored = storage.store(
        transaction_id=transaction_id,
        document_id=f"{base_id}-markdown",
        original_filename="normalized-markdown.txt",
        media_type="text/markdown",
        content=markdown_bytes,
        expected_sha256=hashlib.sha256(markdown_bytes).hexdigest(),
    )
    masked_stored = storage.store(
        transaction_id=transaction_id,
        document_id=f"{base_id}-masked",
        original_filename="masked-markdown.txt",
        media_type="text/markdown",
        content=masked_bytes,
        expected_sha256=hashlib.sha256(masked_bytes).hexdigest(),
    )
    conn.execute(
        "UPDATE transactions SET markdown = NULL, masked_markdown = NULL, "
        "markdown_storage_ref = ?, masked_markdown_storage_ref = ? WHERE id = ?",
        (markdown_stored.storage_ref, masked_stored.storage_ref, transaction_id),
    )

    if account_input is not None:
        normalized_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        documents_repo.set_normalized_markdown_sha256(
            conn, document_id=account_input.document_id, normalized_markdown_sha256=normalized_hash
        )

    builder = ContextBuilder(settings, Retriever(settings))
    context = builder.build(report.masked_text, privacy_report=report)

    extraction: ExtractionJSON | None = None
    raw_result_data: ExtractionJSON | None = None
    safe_reason_key = "extraction_failed"

    # §6.7 / PCI: SAD (CVV/track/PIN) tespitinde canlı (openai) provider çağrılmaz.
    # Not (Bloklayıcı 1): burada ADAPTER/exception ham mesajı hiçbir zaman tutulmaz --
    # yalnız `_SAFE_FAILURE_REASON`'daki sabit kategori anahtarı taşınır; gerçek
    # mesaj (provider response body, endpoint detayı, PII/secret içerebilir)
    # `extraction.py::ExtractionResult.reason`/`str(exc)` içinde kalır ve bu
    # fonksiyonun dışına, hiçbir kalıcı alana (events/extracted_rules/
    # extraction_runs) sızmaz.
    if report.blocking_findings and settings.llm_provider == "openai":
        safe_reason_key = "blocking"
    else:
        result = make_extraction_service(settings).extract(report.masked_text, context)
        if result.status != "ok" or result.data is None:
            safe_reason_key = "extraction_failed"
        else:
            raw_result_data = result.data
            restored = restore(result.data.model_dump(), report.mapping)
            restored = _merge_risk_flags(
                restored, report.risk_flags, needs_review=bool(report.blocking_findings)
            )
            try:
                extraction = ExtractionJSON.model_validate(restored)
            except ValidationError:
                safe_reason_key = "restore_invalid"

    if account_input is not None:
        _persist_account(
            conn,
            transaction_id,
            account_input.document_id,
            settings,
            context,
            report,
            extraction,
            raw_result_data,
            safe_reason_key,
            conversion_provenance,
        )
    else:
        _persist_legacy(conn, transaction_id, settings, extraction, safe_reason_key)


def _materialize_account_temp_file(content: bytes, suffix: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(content)
    finally:
        tmp.close()
    return Path(tmp.name)


def run_pipeline(
    transaction_id: str,
    is_passthrough: bool,
    settings: Settings,
    mode_input: LegacyPipelineInput | AccountPipelineInput,
    *,
    attempt_already_claimed: bool = False,
) -> None:
    """`BackgroundTasks` tarafından çağrılan pipeline task'ı — kendi DB bağlantısını açar.

    İstek anındaki `get_db` bağlantısı task koşana kadar kapanmış olur (Pinned
    design decision #2); bu yüzden `open_background_connection(settings)` ile
    bağımsız bir bağlantı açılır, `finally`'de commit/close edilir. Hat asla
    sessizce çökmez: beklenmeyen bir istisna `awaiting_review` + hata
    event'ine düşer, `extracting`'te asla takılı kalınmaz. Account modda
    ayrıca provenance için (güvenli, sabit) bir `extraction_runs` "failed"
    satırı da eklenir.
    """
    account_input = mode_input if isinstance(mode_input, AccountPipelineInput) else None
    conn = open_background_connection(settings)
    extraction_job = None
    file_path: Path | None = None
    try:
        extraction_job = processing_jobs.ensure_job(
            conn,
            kind="extraction",
            source_id=transaction_id,
            transaction_id=transaction_id,
            idempotency_key=f"extraction:transaction:{transaction_id}",
        )
        if extraction_job["status"] == "succeeded":
            return
        if not attempt_already_claimed:
            claimed = processing_jobs.claim_for_retry(
                conn,
                extraction_job["id"],
                from_statuses=("queued", "retry_pending", "failed", "unknown"),
            )
            if not claimed:
                # Another worker owns this job; never duplicate extraction.
                return
        conn.execute(
            "UPDATE transactions SET state = 'extracting' WHERE id = ?", (transaction_id,)
        )
        conn.commit()

        try:
            storage = make_document_storage_provider(settings)
            content = storage.read_bytes(mode_input.storage_ref)
            file_path = _materialize_account_temp_file(content, mode_input.suffix)
            _execute_pipeline(conn, transaction_id, file_path, is_passthrough, settings, account_input)
        except Exception:  # noqa: BLE001 — hat asla sessizce çökmez (Notes for Implementer)
            conn.execute(
                "UPDATE transactions SET state = 'awaiting_review' WHERE id = ?", (transaction_id,)
            )
            # Bloklayıcı 1: ham exception mesajı (traceback, provider response body,
            # PII olabilecek herhangi bir değer) kalıcı event payload'ına ASLA
            # girmez -- yalnız sabit, güvenli `_SAFE_FAILURE_REASON["pipeline_error"]`
            # yazılır.
            emit(
                conn,
                transaction_id,
                "rules_validated",
                {
                    "status": "NEEDS_REVIEW",
                    "findings": [
                        {
                            "code": "PIPELINE_ERROR",
                            "severity": "review",
                            "message": _SAFE_FAILURE_REASON["pipeline_error"],
                        }
                    ],
                },
                "pipeline",
            )
            if account_input is not None:
                extraction_runs_repo.insert_extraction_run(
                    conn,
                    run_id=uuid4().hex,
                    transaction_id=transaction_id,
                    document_id=account_input.document_id,
                    provider=settings.llm_provider,
                    model=(
                        settings.llm_model if settings.llm_provider == "openai" else _FAKE_MODEL_ID
                    ),
                    prompt_version=EXTRACTION_PROMPT_VERSION,
                    schema_version=EXTRACTION_SCHEMA_VERSION,
                    rag_provenance_json="[]",
                    privacy_summary_json="{}",
                    extraction_json=None,
                    status="failed",
                    failure_reason=_SAFE_FAILURE_REASON["pipeline_error"],
                    now=_utc_now_iso(),
                )
            if extraction_job is not None:
                processing_jobs.mark_failed(
                    conn, extraction_job["id"], reason_code="PIPELINE_ERROR"
                )
        else:
            if extraction_job is not None:
                processing_jobs.mark_succeeded(conn, extraction_job["id"])

        conn.commit()
    finally:
        conn.close()
        if file_path is not None:
            file_path.unlink(missing_ok=True)
