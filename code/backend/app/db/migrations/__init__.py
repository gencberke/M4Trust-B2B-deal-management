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

__all__ = [
    "baseline_current_schema",
    "identity_sessions",
    "legal_entities_memberships",
]
