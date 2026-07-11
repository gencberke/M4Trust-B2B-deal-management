"""CLI: demo user/entity/membership fixture'larını idempotent olarak üretir.

Üretilenler: Berke + Yusuf demo user'ları, ABC A.Ş. + XYZ Ltd. entity'leri ve
uygun owner membership'leri. Gerçek kişisel TCKN/VKN kullanılmaz — sadece
biçimsel olarak geçerli (haneli) sabit test numaraları. Secret veya raw
session token loglanmaz; yalnız e-posta/id gibi kimlik bilgisi stdout'a yazılır.

Kullanım:
    cd code && ./.venv/bin/python scripts/seed_demo_users.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_ROOT = Path(__file__).resolve().parent
_CODE_ROOT = _SCRIPTS_ROOT.parent
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from backend.app.config import Settings  # noqa: E402
from backend.app.db import connect, init_db  # noqa: E402
from backend.app.repositories import entities as entities_repo  # noqa: E402
from backend.app.repositories import users as users_repo  # noqa: E402
from backend.app.services import auth as auth_service  # noqa: E402
from backend.app.services import identity as identity_service  # noqa: E402

_DEMO_PASSWORD = "Demo12345!"

_DEMO_USERS = (
    {
        "email": "berke@m4trust.demo",
        "first_name": "Berke",
        "last_name": "Genç",
    },
    {
        "email": "yusuf@m4trust.demo",
        "first_name": "Yusuf",
        "last_name": "Ünlü",
    },
)

_DEMO_ENTITIES = (
    {
        "owner_email": "berke@m4trust.demo",
        "entity_type": "company",
        "legal_name": "ABC Sanayi ve Ticaret A.Ş.",
        "tax_identifier_type": "vkn",
        "tax_identifier": "1111111111",
        "tax_office": "Kadıköy Vergi Dairesi",
    },
    {
        "owner_email": "yusuf@m4trust.demo",
        "entity_type": "company",
        "legal_name": "XYZ Lojistik Ltd. Şti.",
        "tax_identifier_type": "vkn",
        "tax_identifier": "2222222222",
        "tax_office": "Konak Vergi Dairesi",
    },
)


def _ensure_user(conn, *, email: str, first_name: str, last_name: str) -> str:
    normalized = auth_service.normalize_email(email)
    existing = users_repo.get_user_by_email(conn, normalized)
    if existing is not None:
        print(f"[skip] user zaten var: {normalized}")
        return existing["id"]
    user_id = auth_service.register_user(
        conn,
        email=email,
        password=_DEMO_PASSWORD,
        first_name=first_name,
        last_name=last_name,
    )
    conn.commit()
    print(f"[ok]   user oluşturuldu: {normalized} ({user_id})")
    return user_id


def _ensure_entity(
    conn,
    *,
    owner_user_id: str,
    entity_type: str,
    legal_name: str,
    tax_identifier_type: str,
    tax_identifier: str,
    tax_office: str,
    settings: Settings,
) -> str:
    existing_rows = entities_repo.list_entities_for_user(conn, owner_user_id)
    for row in existing_rows:
        if row["legal_name"] == legal_name:
            print(f"[skip] entity zaten var: {legal_name} ({row['id']})")
            return row["id"]

    entity_id = identity_service.create_entity(
        conn,
        entity_type=entity_type,
        legal_name=legal_name,
        tax_identifier_type=tax_identifier_type,
        raw_tax_identifier=tax_identifier,
        tax_office=tax_office,
        address_json=None,
        created_by_user_id=owner_user_id,
        settings=settings,
    )
    conn.commit()
    print(f"[ok]   entity oluşturuldu: {legal_name} ({entity_id})")
    return entity_id


def main() -> None:
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        init_db(conn)

        user_ids: dict[str, str] = {}
        for demo_user in _DEMO_USERS:
            user_ids[demo_user["email"]] = _ensure_user(
                conn,
                email=demo_user["email"],
                first_name=demo_user["first_name"],
                last_name=demo_user["last_name"],
            )

        for demo_entity in _DEMO_ENTITIES:
            owner_user_id = user_ids[demo_entity["owner_email"]]
            _ensure_entity(
                conn,
                owner_user_id=owner_user_id,
                entity_type=demo_entity["entity_type"],
                legal_name=demo_entity["legal_name"],
                tax_identifier_type=demo_entity["tax_identifier_type"],
                tax_identifier=demo_entity["tax_identifier"],
                tax_office=demo_entity["tax_office"],
                settings=settings,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
