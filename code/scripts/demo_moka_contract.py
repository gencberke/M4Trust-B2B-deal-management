"""Moka contract-faithful client + ayrı localhost mock server demo sürücüsü.

Terminal 1::

    cd code
    ./.venv/bin/uvicorn backend.mock_moka.app:app --port 8001

Terminal 2::

    cd code
    ./.venv/bin/python scripts/demo_moka_contract.py
    ./.venv/bin/python scripts/demo_moka_contract.py --fault

Normal akış create -> approve -> detail çalıştırır. ``--fault`` banka reddi
token'ını kullanır ve beklenen bank-level failure'ı gösterir. Stdout yalnızca
redacted request/response trace'leri ve normalize domain sonuçlarını içerir.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_SCRIPTS_ROOT = Path(__file__).resolve().parent
_CODE_ROOT = _SCRIPTS_ROOT.parent
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.services.payments.domain import (  # noqa: E402
    CreatePoolPaymentCommand,
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderPaymentStatus,
)
from backend.app.services.payments.moka.client import (  # noqa: E402
    MokaPaymentDealerClient,
)
from backend.app.services.payments.moka.errors import ProviderError  # noqa: E402

_LOCAL_DEMO_DEALER_CODE = "DEALER-DEMO-001"
_LOCAL_DEMO_USERNAME = "m4trust_demo"
_LOCAL_DEMO_PASSWORD = "demo-secret"
_SUCCESS_TOKEN = "DEMO-TOKEN-SUCCESS"
_DECLINE_TOKEN = "DEMO-TOKEN-BANK-DECLINE"


def _json_ready(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _json_ready(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _emit(payload: dict) -> None:
    print(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2))


def _demo_settings(*, base_url: str | None, fault: bool) -> Settings:
    load_dotenv(_CODE_ROOT / ".env", override=False)
    settings = Settings.from_env()
    return replace(
        settings,
        moka_base_url=base_url or settings.moka_base_url,
        moka_dealer_code=(
            settings.moka_dealer_code
            or os.environ.get("MOCK_MOKA_DEALER_CODE", _LOCAL_DEMO_DEALER_CODE)
        ),
        moka_username=(
            settings.moka_username
            or os.environ.get("MOCK_MOKA_USERNAME", _LOCAL_DEMO_USERNAME)
        ),
        moka_password=(
            settings.moka_password
            or os.environ.get("MOCK_MOKA_PASSWORD", _LOCAL_DEMO_PASSWORD)
        ),
        moka_card_token=(
            _DECLINE_TOKEN
            if fault
            else (settings.moka_card_token or _SUCCESS_TOKEN)
        ),
    )


def _record_step(
    records: list[dict],
    *,
    step: str,
    client: MokaPaymentDealerClient,
    result: object,
) -> None:
    records.append(
        {
            "step": step,
            "trace": client.last_trace,
            "result": result,
        }
    )


def run_demo(
    *,
    settings: Settings,
    amount_minor: int,
    currency: str,
    other_trx_code: str,
    fault: bool,
) -> int:
    records: list[dict] = []
    scenario = "bank_decline" if fault else "create_approve_detail"
    command = CreatePoolPaymentCommand(
        amount_minor=amount_minor,
        currency=currency,
        other_trx_code=other_trx_code,
        description="M4Trust contract-faithful demo",
    )

    try:
        with MokaPaymentDealerClient.from_settings(settings) as client:
            create_result = client.create_pool_payment(command)
            _record_step(records, step="create", client=client, result=create_result)

            if fault:
                expected_decline = (
                    create_result.outcome is ProviderOperationOutcome.FAILED
                    and create_result.provider_code == "BankDeclined"
                )
                _emit(
                    {
                        "scenario": scenario,
                        "success": expected_decline,
                        "other_trx_code": other_trx_code,
                        "steps": records,
                    }
                )
                return 0 if expected_decline else 2

            if (
                create_result.outcome is not ProviderOperationOutcome.SUCCESS
                or create_result.payment is None
            ):
                _emit(
                    {
                        "scenario": scenario,
                        "success": False,
                        "other_trx_code": other_trx_code,
                        "steps": records,
                    }
                )
                return 2

            identifier = create_result.payment.identifier
            approve_result = client.approve_pool_payment(identifier)
            _record_step(records, step="approve", client=client, result=approve_result)
            if approve_result.outcome is not ProviderOperationOutcome.SUCCESS:
                _emit(
                    {
                        "scenario": scenario,
                        "success": False,
                        "other_trx_code": other_trx_code,
                        "steps": records,
                    }
                )
                return 2

            detail_result = client.get_payment_detail(
                PaymentDetailQuery(identifier=identifier)
            )
            _record_step(records, step="detail", client=client, result=detail_result)
            success = (
                detail_result.outcome is ProviderOperationOutcome.SUCCESS
                and detail_result.payment is not None
                and detail_result.payment.status is ProviderPaymentStatus.APPROVED
            )
            _emit(
                {
                    "scenario": scenario,
                    "success": success,
                    "other_trx_code": other_trx_code,
                    "steps": records,
                }
            )
            return 0 if success else 2
    except ProviderError as exc:
        _emit(
            {
                "scenario": scenario,
                "success": False,
                "other_trx_code": other_trx_code,
                "steps": records,
                "error": {
                    "type": type(exc).__name__,
                    "result_code": exc.result_code,
                    "result_message": exc.result_message,
                },
            }
        )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Moka PaymentDealer client'ını ayrı localhost mock server'a karşı çalıştır."
    )
    parser.add_argument("--amount-minor", type=int, default=250_000)
    parser.add_argument("--currency", default="TRY")
    parser.add_argument("--other-trx-code")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--fault",
        action="store_true",
        help="DEMO-TOKEN-BANK-DECLINE ile beklenen banka reddi senaryosu.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    other_trx_code = args.other_trx_code or f"M4T-DEMO-{uuid4().hex[:12].upper()}"
    settings = _demo_settings(base_url=args.base_url, fault=args.fault)
    return run_demo(
        settings=settings,
        amount_minor=args.amount_minor,
        currency=args.currency,
        other_trx_code=other_trx_code,
        fault=args.fault,
    )


if __name__ == "__main__":
    raise SystemExit(main())
