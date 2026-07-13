"""Gizli demo araçları (Plan 14 / D3) — YALNIZ `DEMO_TOOLS_ENABLED=true` iken mount edilir.

`main.py` bu router'ı yalnız flag açıkken include eder; kapalıyken OpenAPI'de ve
saldırı yüzeyinde hiç yoktur (uçlar 404). Bu 404, frontend'in demo UI gate'idir
(`GET /api/demo/status` → 404 ise hiçbir demo UI render edilmez).

Güvenlik (ARCHITECTURE §6): demo uçları asla payment provider'ı doğrudan çağırmaz,
`funding_units`/pool payment satırı elle yazmaz, validator/policy-lock/ratification
gate'lerini bypass etmez; `settled`'a yalnız `settlement.evaluate_settlement`
üzerinden ulaşılır. Tüm mutation'lar `demo_scenarios` (gerçek servisler) üzerinden
akar ve authenticated session + CSRF ister; guard ihlali gerçek 409/exception
olarak yüzer. Bu router seed'li Berke/Yusuf demo taraflarını kullanır.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.services import demo_scenarios
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(prefix="/api/demo", tags=["demo-tools"])


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_state: str


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str
    transaction_id: str | None = None
    title: str | None = None


@router.get("/status")
def demo_status(
    _actor: Annotated[ActorContext, Depends(require_authenticated_user)],
) -> dict:
    """Flag açıkken `{demo_tools_enabled: true}`; kapalıyken router mount edilmez → 404."""
    return {"demo_tools_enabled": True}


@router.post("/transactions/{transaction_id}/advance")
def advance_transaction(
    transaction_id: str,
    body: AdvanceRequest,
    _actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    """Var olan bir demo işlemini seed'li taraflar adına `target_state`'e ilerletir."""
    parties = demo_scenarios.resolve_seeded_demo_parties(conn)
    try:
        return demo_scenarios.advance(
            conn,
            Settings.from_env(),
            transaction_id=transaction_id,
            target_state=body.target_state,
            parties=parties,
        )
    except demo_scenarios.DemoScenarioError as exc:
        raise ApiError(status_code=400, code="DEMO_ADVANCE_FAILED", message=str(exc)) from exc


@router.post("/scenarios")
def create_scenario(
    body: ScenarioRequest,
    _actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    """Seed'li taraflarla taze bir işlem oluşturup adlandırılmış state'e ilerletir."""
    parties = demo_scenarios.resolve_seeded_demo_parties(conn)
    try:
        return demo_scenarios.create_scenario(
            conn,
            Settings.from_env(),
            scenario=body.scenario,
            parties=parties,
            transaction_id=body.transaction_id,
            title=body.title,
        )
    except demo_scenarios.DemoScenarioError as exc:
        raise ApiError(status_code=400, code="DEMO_SCENARIO_FAILED", message=str(exc)) from exc
