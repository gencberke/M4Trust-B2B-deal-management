"""Legal entity ve membership satır/sorgu erişimi (Faz 3A)."""

from __future__ import annotations

from sqlite3 import Connection, Row
from uuid import uuid4


def insert_entity(
    conn: Connection,
    *,
    entity_type: str,
    legal_name: str,
    tax_identifier_type: str,
    tax_identifier_ciphertext: str,
    tax_identifier_lookup_hmac: str,
    tax_identifier_last4: str,
    tax_office: str | None,
    address_json: str | None,
    verification_status: str,
    created_by_user_id: str,
    now: str,
) -> str:
    entity_id = uuid4().hex
    conn.execute(
        """INSERT INTO legal_entities
        (id, entity_type, legal_name, tax_identifier_type, tax_identifier_ciphertext,
         tax_identifier_lookup_hmac, tax_identifier_last4, tax_office, address_json,
         verification_status, created_by_user_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_id,
            entity_type,
            legal_name,
            tax_identifier_type,
            tax_identifier_ciphertext,
            tax_identifier_lookup_hmac,
            tax_identifier_last4,
            tax_office,
            address_json,
            verification_status,
            created_by_user_id,
            now,
            now,
        ),
    )
    return entity_id


def get_entity_by_id(conn: Connection, entity_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM legal_entities WHERE id = ?", (entity_id,)
    ).fetchone()


def update_entity_fields(
    conn: Connection, *, entity_id: str, fields: dict[str, object], now: str
) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{column} = ?" for column in fields)
    values = [*fields.values(), now, entity_id]
    conn.execute(
        f"UPDATE legal_entities SET {assignments}, updated_at = ? WHERE id = ?",
        values,
    )


def insert_membership(
    conn: Connection,
    *,
    user_id: str,
    legal_entity_id: str,
    role: str,
    now: str,
) -> str:
    membership_id = uuid4().hex
    conn.execute(
        """INSERT INTO memberships
        (id, user_id, legal_entity_id, role, status, created_at)
        VALUES (?, ?, ?, ?, 'active', ?)""",
        (membership_id, user_id, legal_entity_id, role, now),
    )
    return membership_id


def get_active_membership(
    conn: Connection, *, user_id: str, legal_entity_id: str
) -> Row | None:
    return conn.execute(
        """SELECT * FROM memberships
        WHERE user_id = ? AND legal_entity_id = ? AND status = 'active'""",
        (user_id, legal_entity_id),
    ).fetchone()


def list_entities_for_user(conn: Connection, user_id: str) -> list[Row]:
    return conn.execute(
        """SELECT legal_entities.*, memberships.role AS my_role
        FROM legal_entities
        JOIN memberships ON memberships.legal_entity_id = legal_entities.id
        WHERE memberships.user_id = ? AND memberships.status = 'active'
        ORDER BY legal_entities.created_at""",
        (user_id,),
    ).fetchall()
