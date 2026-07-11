"""Rule-set version değer tipleri (Plan 04 / Faz 4A, v2 §5.10/§8.2).

`ExtractionJSON` şeması genişletilmez; `rules_json`/`extraction` bu şemayla
birebir doğrulanabilir bir payload'dır. Bu modül yalnızca donmuş
`RuleVersionService` (`services/rule_versions.py`) ve merkezi current-rule
okuma kapısının (`repositories/rule_sets.py::get_current`) döndürdüğü değer
tiplerini taşır — DB/IO içermez.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.extraction import ExtractionJSON

RuleSetStatus = Literal["draft", "validated", "ratifiable", "superseded", "ratified"]
CreatedByActorType = Literal["user", "system"]


@dataclass(frozen=True, slots=True)
class RuleSetVersion:
    """Tek bir `rule_set_versions` satırının tipli görünümü."""

    id: str
    transaction_id: str
    version: int
    parent_version_id: str | None
    source_extraction_run_id: str | None
    extraction: ExtractionJSON
    rules_hash: str
    validator_status: str | None
    validator_report: list[dict] | None
    status: RuleSetStatus
    created_by_user_id: str | None
    created_by_actor_type: CreatedByActorType
    created_at: str


@dataclass(frozen=True, slots=True)
class CurrentRuleSet:
    """Bir işlem için "şu an geçerli" kural kümesinin lifecycle-bağımsız görünümü.

    `account_v2` kaynaklı ise `rule_set_id`/`version`/`rules_hash`/`status`
    doludur; `legacy_v1` fallback'ten geliyorsa bunlar `None`'dır (legacy'de
    versiyonlu bir kural kümesi kavramı yoktur — yalnızca en son extraction
    denemesi vardır). `extraction`, extraction hiç üretilememişse (ör. legacy
    pipeline hata/blocking yolu) `None` olabilir; `validator_status`/
    `validator_report` bu durumda da bir satır var olduğu sürece doludur.
    """

    rule_set_id: str | None
    version: int | None
    rules_hash: str | None
    status: RuleSetStatus | None
    extraction: ExtractionJSON | None
    validator_status: str | None
    validator_report: object


class RuleSetVersionPublicView(BaseModel):
    """Rule revision uçlarının PII'siz version görünümü.

    Revision isteği tam `ExtractionJSON` alır; cevap ise public projection'dır.
    Vergi numarası ve source quote bu session-authenticated uçta dönmez.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    version: int
    parent_version_id: str | None
    extraction: dict
    rules_hash: str
    validator_status: str | None
    validator_report: list[dict] | None
    status: RuleSetStatus
    created_by_user_id: str | None
    created_at: str
