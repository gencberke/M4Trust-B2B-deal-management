"""Frozen `RuleVersionService` (Plan 04 / Faz 4A, v2 §8.2).

```python
create_initial_from_extraction(conn, *, transaction_id, extraction_run_id, rules_payload,
                                created_by_actor_type="system", created_by_user_id=None) -> RuleSetVersion
create_revision(conn, *, transaction_id, parent_version_id, rules_payload, actor_context) -> RuleSetVersion
validate_version(conn, *, version_id, confidence_threshold) -> RuleSetVersion
get_current(conn, transaction_id) -> CurrentRuleSet | None
supersede(conn, *, version_id, reason_code) -> RuleSetVersion
```

Bu beş imza PR sonunda donar. Servis kendi commit'ini atmaz; transaction
sınırı çağıranındır (router/pipeline). `get_current` burada saf
`rule_set_versions` okuyucusudur (legacy `extracted_rules` fallback'i
BİLMEZ) — lifecycle-bağımsız merkezi okuma kapısı
`repositories/rule_sets.py::get_current`'tadır (v2 §11); bu iki fonksiyon
aynı satır->`CurrentRuleSet` dönüştürücüsünü (`rule_set_version_row_to_current`)
paylaşır.

Canonical hash (v2 §2.15): `rules_json`, `ExtractionJSON` ile birebir
doğrulanmış payload'ın `sort_keys=True, separators=(",", ":"),
ensure_ascii=False` ile üretilmiş UTF-8 string'idir; `rules_hash` bu saklanan
string'in byte'larından SHA-256'dır. Hash her okumada yeniden üretilmez —
saklanan string üzerinden hesaplanıp bir kez yazılır.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from uuid import uuid4

from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.schemas.rule_sets import CurrentRuleSet, RuleSetVersion
from backend.app.services.access_control import ActorContext
from backend.app.services.validator import validate


class RuleSetVersionNotFoundError(Exception):
    """Beklenen `rule_set_versions` satırı yok (tutarsız çağrı sırası)."""


def canonical_rules_json(payload: dict) -> str:
    """v2 §2.15 kanonik JSON string'i — dict key sırasından bağımsız, deterministik."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_rules_hash(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_rule_set_version(row: Row) -> RuleSetVersion:
    validator_report = row["validator_report_json"]
    if validator_report:
        validator_report = json.loads(validator_report)
    return RuleSetVersion(
        id=row["id"],
        transaction_id=row["transaction_id"],
        version=row["version"],
        parent_version_id=row["parent_version_id"],
        source_extraction_run_id=row["source_extraction_run_id"],
        extraction=ExtractionJSON.model_validate(json.loads(row["rules_json"])),
        rules_hash=row["rules_hash"],
        validator_status=row["validator_status"],
        validator_report=validator_report,
        status=row["status"],
        created_by_user_id=row["created_by_user_id"],
        created_by_actor_type=row["created_by_actor_type"],
        created_at=row["created_at"],
    )


def _get_or_raise(conn: Connection, version_id: str) -> Row:
    row = rule_sets_repo.get_by_id(conn, version_id)
    if row is None:
        raise RuleSetVersionNotFoundError(version_id)
    return row


def create_initial_from_extraction(
    conn: Connection,
    *,
    transaction_id: str,
    extraction_run_id: str,
    rules_payload: dict,
    created_by_actor_type: str = "system",
    created_by_user_id: str | None = None,
) -> RuleSetVersion:
    """Bir extraction run'dan transaction'ın 1 numaralı (ilk) rule-set version'ını üretir."""
    extraction = ExtractionJSON.model_validate(rules_payload)
    canonical = canonical_rules_json(extraction.model_dump(mode="json"))
    rules_hash = compute_rules_hash(canonical)
    version_id = uuid4().hex
    now = _utc_now_iso()

    rule_sets_repo.insert_rule_set_version(
        conn,
        version_id=version_id,
        transaction_id=transaction_id,
        version=1,
        parent_version_id=None,
        source_extraction_run_id=extraction_run_id,
        rules_json=canonical,
        rules_hash=rules_hash,
        status="draft",
        created_by_user_id=created_by_user_id,
        created_by_actor_type=created_by_actor_type,
        now=now,
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def create_revision(
    conn: Connection,
    *,
    transaction_id: str,
    parent_version_id: str,
    rules_payload: dict,
    actor_context: ActorContext,
) -> RuleSetVersion:
    """Eski içeriği DEĞİŞTİRMEDEN yeni, immutable bir revizyon satırı üretir."""
    extraction = ExtractionJSON.model_validate(rules_payload)
    canonical = canonical_rules_json(extraction.model_dump(mode="json"))
    rules_hash = compute_rules_hash(canonical)
    version_id = uuid4().hex
    next_version = rule_sets_repo.get_max_version(conn, transaction_id) + 1
    now = _utc_now_iso()

    rule_sets_repo.insert_rule_set_version(
        conn,
        version_id=version_id,
        transaction_id=transaction_id,
        version=next_version,
        parent_version_id=parent_version_id,
        source_extraction_run_id=None,
        rules_json=canonical,
        rules_hash=rules_hash,
        status="draft",
        created_by_user_id=actor_context.user_id,
        created_by_actor_type="user",
        now=now,
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def validate_version(
    conn: Connection, *, version_id: str, confidence_threshold: float
) -> RuleSetVersion:
    """Mevcut deterministik validator'ı bu version üzerinde çalıştırır ve sonucu yazar."""
    row = _get_or_raise(conn, version_id)
    extraction = ExtractionJSON.model_validate(json.loads(row["rules_json"]))
    report = validate(extraction, confidence_threshold=confidence_threshold)
    findings_payload = [
        {"code": f.code, "severity": f.severity, "message": f.message} for f in report.findings
    ]
    new_status = "ratifiable" if report.status == "PASS" else "validated"

    rule_sets_repo.update_validation(
        conn,
        version_id=version_id,
        status=new_status,
        validator_status=report.status,
        validator_report_json=json.dumps(findings_payload, ensure_ascii=False),
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def get_current(conn: Connection, transaction_id: str) -> CurrentRuleSet | None:
    """Saf `rule_set_versions` okuyucusu — en yeni non-superseded version (legacy fallback YOK)."""
    row = rule_sets_repo.get_latest_non_superseded(conn, transaction_id)
    return None if row is None else rule_sets_repo.rule_set_version_row_to_current(row)


def supersede(conn: Connection, *, version_id: str, reason_code: str) -> RuleSetVersion:
    """Version'ı `superseded` yapar; içerik alanları değişmez (DB trigger'ı garanti eder).

    `reason_code` bu fazda kalıcı bir alana yazılmaz (şema kapsamında yer
    almıyor) — çağıranın kendi audit/event kaydı için taşıdığı bağlamdır.
    """
    _get_or_raise(conn, version_id)
    rule_sets_repo.mark_superseded(conn, version_id=version_id)
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))
