"""Sıralı uygulama migration'ları."""

from importlib import import_module

baseline_current_schema = import_module(
    "backend.app.db.migrations.001_baseline_current_schema"
)

__all__ = ["baseline_current_schema"]
