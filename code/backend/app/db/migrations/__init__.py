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
]
