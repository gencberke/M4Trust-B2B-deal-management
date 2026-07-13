# M4Trust backend

Python 3.12 + FastAPI + versioned SQLite migrations. Run commands from `code/` so the packaged `backend` and `scripts` modules resolve exactly as they do in CI.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ci.txt
Copy-Item backend\.env.example .env
```

Generate independent 32-byte base64 values for `APP_ENCRYPTION_KEY` and `APP_HMAC_KEY`; never commit `.env`. Then:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Startup applies migrations `001, 003–025` in registry order (`002` is intentionally unused), marks stale operational jobs recoverable without calling providers, and exposes `GET /health`. Use one application worker while SQLite is the runtime database.

## Local demo tools

Demo router production yüzeyinden ayrıdır ve varsayılan olarak kapalıdır. Yerel gösterim için `code/.env` içinde `DEMO_TOOLS_ENABLED=true` ve `SESSION_COOKIE_SECURE=false` kullanın, ardından `python scripts/seed_demo_scenarios.py` çalıştırın. Bu script demo kullanıcı/entity fixture'larını ve altı adlandırılmış transaction state'ini idempotent üretir. `SESSION_COOKIE_SECURE=true` ile demo router mount edilmez; flag kapalıyken `/api/demo/*` OpenAPI'de de bulunmaz. Demo araçları business state'i ham SQL ile zorlamaz ve yalnız gerçek servis orkestrasyonunu kullanır.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp "$env:LOCALAPPDATA\Temp\m4trust-pytest"
.\.venv\Scripts\python.exe -m pip_audit -r requirements-ci.txt
.\.venv\Scripts\python.exe -m bandit -r backend\app scripts -x tests -lll
```

Direct startup smoke (not affected by `tests/conftest.py` path setup):

```powershell
.\.venv\Scripts\python.exe -c "from backend.app.main import create_app; assert create_app().title == 'M4Trust API'"
```

Operational procedures are in [retention and backup](../../docs/operations-retention-backup.md), [security/privacy](../../docs/security-and-privacy.md), and [PostgreSQL readiness](../../docs/postgresql-readiness.md).
