# Security and privacy operating baseline

M4Trust remains a hackathon/demo system, not a certified payment institution or PCI DSS-certified product. The baseline below is mandatory for any environment that handles non-synthetic documents.

## Secrets and identity

- `APP_ENCRYPTION_KEY` must be an independently generated 32-byte base64 key. It encrypts legal identifiers and every document blob; missing, malformed, or wrong keys fail closed.
- `APP_HMAC_KEY`, provider credentials, reset/verification tokens, session cookies, CSRF values and capability tokens must never be committed, logged, placed in URLs (except the single invitation route), or copied into reports.
- Production uses HTTPS and `SESSION_COOKIE_SECURE=true`. `TRUST_PROXY_HEADERS` stays false unless the proxy boundary is explicitly controlled.
- Login rate limiting is in-process and therefore per-process. Persistent lockout is stored in SQLite. A multi-instance deployment requires a shared rate-limit backend before release.
- Password reset and verification tokens are high entropy, hashed at rest, expiring, single-use and revoke existing sessions after password reset.

## Documents and privacy

- `LocalDocumentStorageProvider` uses AES-256-GCM with a fresh 96-bit nonce and storage reference as authenticated additional data. Normal reads reject legacy plaintext, corruption and wrong keys.
- Contract and evidence uploads are bounded by `MAX_CONTRACT_UPLOAD_BYTES` and `MAX_EVIDENCE_UPLOAD_BYTES` (25 MiB by default) before persistence or analyzer execution.
- Raw contract uploads, normalized markdown and masked markdown live only as encrypted blobs. Database columns hold references; pre-Plan-09 plaintext requires the explicit migration command.
- `extraction_runs` and immutable rule history may contain restored business data required for audit. Access is assignment/entity-scoped and the retention exception must be reviewed with counsel before real production use.
- Public projections exclude storage references, document text, source quotes (except the guarded legacy party view), request IP hashes, user-agent summaries, provider raw payloads and credentials.

## Logging and scans

Runtime logs are JSON and allowlist only: timestamp, level, logger, event, request ID, actor IDs/types, acting entity, action, outcome, status and duration. Arbitrary exception text, request bodies and filenames are not serialized.

CI runs `pip-audit`, high-severity Bandit, `npm audit`, a direct startup smoke and Gitleaks. Medium Bandit B608 candidates are reviewed separately because current occurrences construct identifiers/placeholders from fixed application allowlists while all values remain parameterized.

The external workstream report supplied for the final audit contained a plaintext provider credential outside the repository. It must be revoked/rotated and the report redacted before sharing. The repository and Git history scans did not find that credential.
