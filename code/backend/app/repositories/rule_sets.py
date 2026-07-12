"""`rule_set_versions` satır/sorgu erişimi + merkezi current-rule okuma kapısı.

`get_current()` (v2 §11 "Merkezi current-rule seam") bu dosyanın tek genel
amaçlı okuma ucudur: transactions/approvals/delivery/evidence/settlement
okuyucuları kendi "latest-by-rowid" `extracted_rules` sorgularını burada
birleştirir. Davranış lifecycle'a göre dallanır —
`account_v2` yalnız `rule_set_versions`'tan okur (satır yoksa `None`; legacy
tabloya yanlışlıkla düşülmez), `legacy_v1` (ve tanınmayan/eski satırlar)
mevcut `extracted_rules` "latest-by-rowid" davranışını korur.

Immutable içerik alanlarını (rules_json/rules_hash/transaction_id/version)
update eden fonksiyon sunulmaz — yalnızca `status`/`validator_status`/
`validator_report_json` güncellemesi vardır (DB trigger'ı bunun dışını zaten
reddeder, bkz. migration 009).
"""

from __future__ import annotations

import json
from sqlite3 import Connection, Row

from backend.app.schemas.extraction import ExtractionJSON
from backend.app.schemas.rule_sets import CurrentRuleSet


def insert_rule_set_version(
    conn: Connection,
    *,
    version_id: str,
    transaction_id: str,
    version: int,
    parent_version_id: str | None,
    source_extraction_run_id: str | None,
    rules_json: str,
    rules_hash: str,
    status: str,
    created_by_user_id: str | None,
    created_by_actor_type: str,
    now: str,
) -> None:
    conn.execute(
        """INSERT INTO rule_set_versions
        (id, transaction_id, version, parent_version_id, source_extraction_run_id,
         rules_json, rules_hash, validator_status, validator_report_json, status,
         created_by_user_id, created_by_actor_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)""",
        (
            version_id,
            transaction_id,
            version,
            parent_version_id,
            source_extraction_run_id,
            rules_json,
            rules_hash,
            status,
            created_by_user_id,
            created_by_actor_type,
            now,
        ),
    )


def get_by_id(conn: Connection, version_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM rule_set_versions WHERE id = ?", (version_id,)
    ).fetchone()


def get_max_version(conn: Connection, transaction_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM rule_set_versions WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    return row[0]


def get_latest_non_superseded(conn: Connection, transaction_id: str) -> Row | None:
    return conn.execute(
        """SELECT * FROM rule_set_versions
        WHERE transaction_id = ? AND status != 'superseded'
        ORDER BY version DESC LIMIT 1""",
        (transaction_id,),
    ).fetchone()


def list_for_transaction(conn: Connection, transaction_id: str) -> list[Row]:
    """Return the complete immutable version history in version order."""

    return conn.execute(
        "SELECT * FROM rule_set_versions WHERE transaction_id = ? "
        "ORDER BY version ASC, id ASC",
        (transaction_id,),
    ).fetchall()


def update_validation(
    conn: Connection,
    *,
    version_id: str,
    status: str,
    validator_status: str,
    validator_report_json: str,
) -> None:
    conn.execute(
        "UPDATE rule_set_versions SET status = ?, validator_status = ?, "
        "validator_report_json = ? WHERE id = ?",
        (status, validator_status, validator_report_json, version_id),
    )


def mark_superseded(conn: Connection, *, version_id: str) -> None:
    conn.execute("UPDATE rule_set_versions SET status = 'superseded' WHERE id = ?", (version_id,))


def mark_superseded_if_current(
    conn: Connection, *, transaction_id: str, version_id: str
) -> bool:
    """Current version'ı tek SQL koşuluyla superseded yapar.

    Revision endpoint'inin optimistic-concurrency kapısıdır: iki manager aynı
    parent'a eşzamanlı revision başlatırsa yalnızca current satırı ilk isteğin
    transaction'ında supersede edilebilir; diğer istek `False` alıp stale
    conflict döner. İçerik alanları değil, yalnızca izinli status alanı değişir.
    """
    cursor = conn.execute(
        """UPDATE rule_set_versions SET status = 'superseded'
        WHERE id = ? AND transaction_id = ? AND status != 'superseded'
          AND id = (
              SELECT id FROM rule_set_versions
              WHERE transaction_id = ? AND status != 'superseded'
              ORDER BY version DESC LIMIT 1
          )""",
        (version_id, transaction_id, transaction_id),
    )
    return cursor.rowcount == 1


def rule_set_version_row_to_current(row: Row) -> CurrentRuleSet:
    """`rule_set_versions` satırından `CurrentRuleSet` üretir (repo + service ortak kullanır)."""
    validator_report = row["validator_report_json"]
    if validator_report:
        validator_report = json.loads(validator_report)
    return CurrentRuleSet(
        rule_set_id=row["id"],
        version=row["version"],
        rules_hash=row["rules_hash"],
        status=row["status"],
        extraction=ExtractionJSON.model_validate(json.loads(row["rules_json"])),
        validator_status=row["validator_status"],
        validator_report=validator_report,
    )


def _legacy_current(conn: Connection, transaction_id: str) -> CurrentRuleSet | None:
    row = conn.execute(
        "SELECT extraction_json, validator_status, validator_report FROM extracted_rules "
        "WHERE transaction_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None:
        return None
    extraction = (
        ExtractionJSON.model_validate(json.loads(row["extraction_json"]))
        if row["extraction_json"] is not None
        else None
    )
    findings = row["validator_report"]
    if findings:
        try:
            findings = json.loads(findings)
        except (TypeError, ValueError):
            pass  # düz metin gerekçe (pipeline hata/needs_review yolu) — olduğu gibi bırak
    return CurrentRuleSet(
        rule_set_id=None,
        version=None,
        rules_hash=None,
        status=None,
        extraction=extraction,
        validator_status=row["validator_status"],
        validator_report=findings,
    )


def get_current(conn: Connection, transaction_id: str) -> CurrentRuleSet | None:
    """Merkezi current-rule okuma kapısı — çağıran `lifecycle_version`'ı bilmek zorunda değildir."""
    tx = conn.execute(
        "SELECT lifecycle_version FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if tx is None:
        return None
    if tx["lifecycle_version"] == "account_v2":
        row = get_latest_non_superseded(conn, transaction_id)
        return None if row is None else rule_set_version_row_to_current(row)
    return _legacy_current(conn, transaction_id)
