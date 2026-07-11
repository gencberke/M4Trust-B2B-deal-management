"""Sıralı uygulama migration'ları."""

from importlib import import_module

baseline_current_schema = import_module(
    "backend.app.db.migrations.001_baseline_current_schema"
)
identity_sessions = import_module(
    "backend.app.db.migrations.003_identity_sessions"
)
legal_entities_memberships = import_module(
    "backend.app.db.migrations.004_legal_entities_memberships"
)
participants_invitations = import_module(
    "backend.app.db.migrations.005_participants_invitations"
)
audit_events = import_module("backend.app.db.migrations.006_audit_events")
transaction_lifecycle_v2 = import_module(
    "backend.app.db.migrations.007_transaction_lifecycle_v2"
)
documents_extraction_runs = import_module(
    "backend.app.db.migrations.008_documents_extraction_runs"
)
rule_set_versions = import_module(
    "backend.app.db.migrations.009_rule_set_versions"
)
review_cases = import_module("backend.app.db.migrations.010_review_cases")
ratification_packages = import_module(
    "backend.app.db.migrations.011_ratification_packages"
)
ratifications = import_module("backend.app.db.migrations.012_ratifications")
evidence_records = import_module("backend.app.db.migrations.013_evidence_records")
disputes = import_module("backend.app.db.migrations.014_disputes")
milestones = import_module("backend.app.db.migrations.015_milestones")
funding_units_provider_payments = import_module(
    "backend.app.db.migrations.016_funding_units_provider_payments"
)
release_instructions = import_module(
    "backend.app.db.migrations.017_release_instructions"
)
plan05_remediation_constraints = import_module(
    "backend.app.db.migrations.023_plan05_remediation_constraints"
)

__all__ = [
    "baseline_current_schema",
    "identity_sessions",
    "legal_entities_memberships",
    "participants_invitations",
    "audit_events",
    "transaction_lifecycle_v2",
    "documents_extraction_runs",
    "rule_set_versions",
    "review_cases",
    "ratification_packages",
    "ratifications",
    "evidence_records",
    "disputes",
    "milestones",
    "funding_units_provider_payments",
    "release_instructions",
    "plan05_remediation_constraints",
]
