"""Account settlement runtime trigger seam (06X).

Router'lar provider veya release mantığı bilmez; başarılı evidence/review/dispute
mutasyonlarından sonra bu küçük orchestration kapısını çağırır. Asıl guard ve
idempotency ``services.settlement.evaluate_settlement`` ile coordinator'larda
kalır.
"""

from __future__ import annotations

from sqlite3 import Connection

from backend.app.config import Settings
from backend.app.repositories.transactions import load_transaction


def reevaluate_account_settlement(
    conn: Connection, transaction_id: str, settings: Settings | None = None
) -> dict | None:
    """Account işlemi için settlement'ı yeniden değerlendirir; commit etmez."""

    row = load_transaction(conn, transaction_id)
    if row is None or "lifecycle_version" not in row.keys() or row["lifecycle_version"] != "account_v2":
        return None
    from backend.app.services.settlement import evaluate_settlement

    return evaluate_settlement(conn, transaction_id, settings or Settings.from_env())
