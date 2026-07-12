"""Plan 04 / Faz 4A — account_v2 pipeline provenance testleri.

Legacy (`legacy_v1`) regresyonu bu dosyada YENİDEN test edilmez — mevcut
`test_api_flow.py`/`test_delivery_flow.py`/`test_manager_policy_api.py` paketi
(pipeline `services/transaction_pipeline.py`'ye taşındıktan sonra da) değişmeden
yeşil kalır. Burada yalnız YENİ account_v2 provenance zinciri (storage ->
extraction_runs -> rule_set_versions) ve legacy/account ayrımı test edilir.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient

from backend.app.db import connect
from backend.app.services.extraction import ExtractionResult
from extraction_fixtures import contractual_video_contract, patch_extraction
from tests._identity_support import identity_keys  # noqa: F401

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
)

_ENTITY_PAYLOAD = {
    "entity_type": "company",
    "legal_name": "ABC Sanayi A.Ş.",
    "tax_identifier_type": "vkn",
    "tax_identifier": "1234567890",
}


class _FailingExtractionService:
    """`extract()` her zaman kontrollü bir needs_review sonucu döner (test dublörü)."""

    def extract(self, masked_markdown, context) -> ExtractionResult:
        return ExtractionResult(status="needs_review", reason="stub: sağlayıcı yanıt vermedi")


@pytest.fixture(autouse=True)
def _isolated_document_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))


def _register_login(client: TestClient, email: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "first_name": "A", "last_name": "B"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("m4t_csrf")}


def _create_entity(client: TestClient) -> str:
    r = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf(client))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload_account_mode(client: TestClient, *, acting_entity_id: str) -> dict:
    response = client.post(
        "/api/transactions",
        data={"acting_entity_id": acting_entity_id, "own_role": "buyer"},
        files={"file": ("sozlesme.md", io.BytesIO(_SAMPLE_MARKDOWN.encode()), "text/markdown")},
        headers={**_csrf(client), "X-Acting-Entity-ID": acting_entity_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _account_transaction(client: TestClient, identity_keys) -> dict:
    _register_login(client, "buyer@example.com")
    entity_id = _create_entity(client)
    return _upload_account_mode(client, acting_entity_id=entity_id)


def test_account_upload_creates_durable_document_row(client: TestClient, identity_keys) -> None:
    created = _account_transaction(client, identity_keys)
    transaction_id = created["id"]

    conn = connect()
    tx_row = conn.execute(
        "SELECT content_sha256 FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    doc_row = conn.execute(
        "SELECT * FROM contract_documents WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    conn.close()

    assert doc_row is not None
    assert doc_row["version"] == 1
    assert doc_row["status"] == "active"
    assert doc_row["content_sha256"] == tx_row["content_sha256"]
    assert doc_row["content_sha256"] == hashlib.sha256(_SAMPLE_MARKDOWN.encode()).hexdigest()

    from backend.app.config import Settings
    from backend.app.services.document_storage import make_document_storage_provider

    storage = make_document_storage_provider(Settings.from_env())
    assert storage.read_bytes(doc_row["storage_ref"]) == _SAMPLE_MARKDOWN.encode()


def test_normalized_markdown_hash_is_set_after_pipeline(client: TestClient, identity_keys) -> None:
    created = _account_transaction(client, identity_keys)
    conn = connect()
    doc_row = conn.execute(
        "SELECT normalized_markdown_sha256 FROM contract_documents WHERE transaction_id = ?",
        (created["id"],),
    ).fetchone()
    conn.close()
    assert doc_row["normalized_markdown_sha256"] == hashlib.sha256(
        _SAMPLE_MARKDOWN.encode("utf-8")
    ).hexdigest()


def test_extraction_run_provenance_fields_are_correct(client: TestClient, identity_keys) -> None:
    created = _account_transaction(client, identity_keys)
    conn = connect()
    run_row = conn.execute(
        "SELECT * FROM extraction_runs WHERE transaction_id = ?", (created["id"],)
    ).fetchone()
    conn.close()

    assert run_row is not None
    assert run_row["provider"] == "fake"
    assert run_row["model"] == "fake-extraction-v1"
    assert run_row["prompt_version"]
    assert run_row["schema_version"]
    assert run_row["status"] == "ok"
    assert run_row["failure_reason"] is None
    assert run_row["extraction_json"] is not None

    rag_provenance = json.loads(run_row["rag_provenance_json"])
    assert isinstance(rag_provenance, list)
    privacy_summary = json.loads(run_row["privacy_summary_json"])
    assert set(privacy_summary) == {
        "detected_types",
        "risk_flags",
        "blocking_finding_codes",
        "mapping_count",
    }


def test_provenance_never_contains_raw_document_text_or_prompt(
    client: TestClient, identity_keys
) -> None:
    created = _account_transaction(client, identity_keys)
    conn = connect()
    run_row = conn.execute(
        "SELECT rag_provenance_json, privacy_summary_json FROM extraction_runs "
        "WHERE transaction_id = ?",
        (created["id"],),
    ).fetchone()
    conn.close()

    combined = run_row["rag_provenance_json"] + run_row["privacy_summary_json"]
    # Sözleşme metnindeki ayırt edici cümle hiçbir provenance alanında olmamalı.
    assert "Tarafların onayıyla ödeme yapılır" not in combined
    assert "Endüstriyel Pompa" not in combined


def test_successful_account_pipeline_creates_ratifiable_initial_rule_set_version(
    client: TestClient, identity_keys
) -> None:
    created = _account_transaction(client, identity_keys)
    conn = connect()
    row = conn.execute(
        "SELECT * FROM rule_set_versions WHERE transaction_id = ?", (created["id"],)
    ).fetchone()
    run_row = conn.execute(
        "SELECT id FROM extraction_runs WHERE transaction_id = ?", (created["id"],)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["version"] == 1
    assert row["parent_version_id"] is None
    assert row["source_extraction_run_id"] == run_row["id"]
    assert row["created_by_actor_type"] == "system"
    assert row["validator_status"] == "PASS"
    assert row["status"] == "ratifiable"

    from backend.app.services.rule_versions import canonical_rules_json, compute_rules_hash

    expected_hash = compute_rules_hash(canonical_rules_json(json.loads(row["rules_json"])))
    assert row["rules_hash"] == expected_hash


def test_account_validator_needs_review_opens_blocking_review_case(
    client: TestClient, identity_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = contractual_video_contract()
    payload["payment_rules"][0]["confidence"] = 0.1
    patch_extraction(monkeypatch, payload)

    created = _account_transaction(client, identity_keys)
    conn = connect()
    rule_row = conn.execute(
        "SELECT id, validator_status FROM rule_set_versions WHERE transaction_id = ?",
        (created["id"],),
    ).fetchone()
    case_row = conn.execute(
        "SELECT * FROM review_cases WHERE transaction_id = ?",
        (created["id"],),
    ).fetchone()
    conn.close()

    assert rule_row["validator_status"] == "NEEDS_REVIEW"
    assert case_row["source_type"] == "validator"
    assert case_row["source_id"] == rule_row["id"]
    assert case_row["reason_code"] == "VALIDATOR_NEEDS_REVIEW"
    assert case_row["severity"] == "blocking"
    assert "LOW_CONFIDENCE" in case_row["description"]


def test_account_success_does_not_write_extracted_rules(client: TestClient, identity_keys) -> None:
    created = _account_transaction(client, identity_keys)
    conn = connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM extracted_rules WHERE transaction_id = ?", (created["id"],)
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_legacy_success_still_writes_extracted_rules(client: TestClient) -> None:
    response = client.post(
        "/api/transactions",
        files={"file": ("sozlesme.md", io.BytesIO(_SAMPLE_MARKDOWN.encode()), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    transaction_id = response.json()["id"]

    conn = connect()
    extracted_count = conn.execute(
        "SELECT COUNT(*) FROM extracted_rules WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    run_count = conn.execute(
        "SELECT COUNT(*) FROM extraction_runs WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    rule_version_count = conn.execute(
        "SELECT COUNT(*) FROM rule_set_versions WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    conn.close()

    assert extracted_count == 1
    assert run_count == 0
    assert rule_version_count == 0


def test_pipeline_failure_produces_safe_needs_review_outcome_for_account_mode(
    client: TestClient, identity_keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: _FailingExtractionService(),
    )
    created = _account_transaction(client, identity_keys)

    conn = connect()
    tx_row = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (created["id"],)
    ).fetchone()
    run_row = conn.execute(
        "SELECT * FROM extraction_runs WHERE transaction_id = ?", (created["id"],)
    ).fetchone()
    rule_version_count = conn.execute(
        "SELECT COUNT(*) FROM rule_set_versions WHERE transaction_id = ?", (created["id"],)
    ).fetchone()[0]
    conn.close()

    assert tx_row["state"] == "awaiting_review"
    assert run_row["status"] == "needs_review"
    assert run_row["extraction_json"] is None
    # Sağlayıcının ham hata mesajı DB'ye asla girmez — yalnız güvenli sabit kategori.
    assert run_row["failure_reason"] == "Extraction sağlayıcısı geçerli bir sonuç üretemedi."
    assert "stub" not in run_row["failure_reason"]
    assert rule_version_count == 0
