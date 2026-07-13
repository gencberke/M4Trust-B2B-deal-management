# Legacy capability access removal readiness

> **Durum:** Planning — removal yapılmadı; `LEGACY_CAPABILITY_ACCESS_ENABLED=false` varsayılanı korunuyor.

This task deliberately does not remove legacy routes, columns or tokens. Removal may start only after all gates below have evidence:

- no active `legacy_v1` transactions requiring party/manager/delivery/evidence access;
- account onboarding and recovery cover every supported demo/business path;
- telemetry proves no capability endpoint use for an agreed deprecation window;
- every client uses session + CSRF + validated acting entity;
- encrypted raw/markdown migration and retention are complete for retained legacy records;
- evidence/export obligations and customer notification are approved;
- rollback backup and compatibility test fixture are archived;
- a separate migration removes routes first, then data/columns only after another release window.

Until then, compatibility code remains present but disabled by default. Capability tokens must never enter logs, events, bundles or screenshots.
