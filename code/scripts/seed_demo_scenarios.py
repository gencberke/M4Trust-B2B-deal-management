"""CLI: demo senaryo matrisini idempotent olarak üretir (Plan 14 / P1).

Önce `seed_demo_users.py`'ı çağırır (Berke/Yusuf + ABC/XYZ), sonra
`services/demo_scenarios.py` üzerinden YALNIZ gerçek servisleri kullanarak her
adlandırılmış state'te birer transaction kurar:

    awaiting_review · awaiting_ratification · active · active_partial ·
    settled · disputed

Deterministik transaction_id + başlıklarla idempotenttir: tekrar çalıştırma
duplicate üretmez, mevcut ilerlemeyi korur. Secret/token loglanmaz.

Kullanım (DEMO_TOOLS ortamında):
    cd code && ./.venv/bin/python scripts/seed_demo_scenarios.py
    (Windows: code\\.venv\\Scripts\\python scripts\\seed_demo_scenarios.py)

Gerekli env: `APP_ENCRYPTION_KEY` (+ identity için `APP_HMAC_KEY`) — storage ve
tax-id şifreleme fail-closed'dır; `seed_demo_users.py` zaten bunları ister.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_ROOT = Path(__file__).resolve().parent
_CODE_ROOT = _SCRIPTS_ROOT.parent
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

import seed_demo_users  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.db import connect, init_db  # noqa: E402
from backend.app.services import demo_scenarios  # noqa: E402

# (scenario, deterministik transaction_id, sözleşme başlığı)
# NOT: transaction_id'nin tire-siz ilk 8 karakteri OtherTrxCode türetiminin
# (`M4T-{tx8}-...`) parçasıdır ve funding_units'te globally UNIQUE olmalıdır;
# bu yüzden ID'ler `demo0N` numaralı ön ekle benzersiz kılınır.
_SCENARIO_MATRIX = (
    ("awaiting_review", "demo01-awaiting-review", "Demo — İnceleme bekliyor"),
    ("awaiting_ratification", "demo02-awaiting-ratification", "Demo — Onay bekliyor"),
    ("active", "demo03-active", "Demo — Aktif (fonlandı)"),
    ("active_partial", "demo04-active-partial", "Demo — Aktif + kısmi teslimat"),
    ("settled", "demo05-settled", "Demo — Kapandı (settled)"),
    ("disputed", "demo06-disputed", "Demo — İtirazlı (disputed)"),
)


def main() -> None:
    # 1) Kullanıcı/entity fixture'ları (idempotent).
    seed_demo_users.main()

    settings = Settings.from_env()
    conn = connect(settings)
    try:
        init_db(conn)

        parties = demo_scenarios.resolve_seeded_demo_parties(conn)

        for scenario, transaction_id, title in _SCENARIO_MATRIX:
            result = demo_scenarios.create_scenario(
                conn, settings,
                scenario=scenario,
                parties=parties,
                transaction_id=transaction_id,
                title=title,
            )
            print(
                f"[ok]   {scenario:<22} {transaction_id} -> state={result['state']}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
