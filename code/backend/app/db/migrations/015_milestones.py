"""Plan 06A milestone persistence (additive, not yet registry-wired)."""

from __future__ import annotations

import sqlite3

VERSION = "015"
NAME = "milestones"

STATEMENTS = (
    """CREATE TABLE milestones (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        ratification_package_id TEXT NOT NULL,
        rule_set_version_id TEXT NOT NULL,
        rule_index INTEGER NOT NULL CHECK (rule_index >= 0),
        title TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        percentage_basis_points INTEGER NOT NULL
            CHECK (percentage_basis_points > 0 AND percentage_basis_points <= 10000),
        amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
        currency TEXT NOT NULL,
        required_evidence_json TEXT NOT NULL,
        release_mode TEXT NOT NULL
            CHECK (release_mode IN ('all_or_nothing', 'fixed_tranches')),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN (
                'pending', 'evidence_pending', 'eligible', 'held', 'release_pending',
                'partially_released', 'released', 'disputed', 'cancelled'
            )),
        released_amount_minor INTEGER NOT NULL DEFAULT 0
            CHECK (released_amount_minor >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(ratification_package_id, rule_index),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (ratification_package_id) REFERENCES ratification_packages(id),
        FOREIGN KEY (rule_set_version_id) REFERENCES rule_set_versions(id)
    )""",
    """CREATE INDEX idx_milestones_transaction_status
        ON milestones(transaction_id, status)""",
    """CREATE INDEX idx_milestones_package
        ON milestones(ratification_package_id, rule_index)""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
