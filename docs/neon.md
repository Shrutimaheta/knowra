# Optional Neon backend

The application keeps its FastAPI, SQLAlchemy, psycopg and Alembic architecture. Neon can provide PostgreSQL, managed authentication, private original-file storage and a server-authenticated source-integrity Function. These services do not host the Python website by themselves.

## Configuration

Install the official Neon CLI, sign in, and initialize your own project using its current official instructions. This repository deliberately excludes the `.neon` account context and all credentials. Inspect `neon.ts` before deploying: it declares Auth, a private assets bucket and the hello Function; AI Gateway is disabled. Confirm available services and costs for your account, and do not enable a paid feature unintentionally.

Use the pooled `DATABASE_URL` for app requests and `DATABASE_URL_UNPOOLED` for migrations. Keep both in private `.env` or host secret settings. The CLI supplies Auth, Function and S3-compatible service endpoints and credentials. Set `AUTH_PROVIDER=neon`, `ORIGINAL_STORAGE=neon`, and `NEON_STORAGE_BUCKET=assets` to opt in. Generate a private `KNOWRA_FUNCTION_SECRET` before deployment. It authenticates the backend's integrity calls and must never appear in browser code.

```sh
npm ci
npm run build
npm run neon:deploy
```

The deploy wrapper reads private local settings into the child process environment without printing them. Register only the exact frontend origin with Neon Auth. Managed account identities are mapped by verified subject; existing local accounts are not automatically linked by email or migrated. Signup, sign-in, sign-out and token restoration are integrated. Managed recovery, OTP and social-login screens are not implemented.

Immutable originals can be stored in the private bucket while SQL retains version IDs, checksums and sizes. The source-integrity Function rechecks document access and verifies the original checksum. Backups materialize referenced originals so a snapshot does not depend on live object keys. A retention and orphan-object cleanup policy remains required for a larger deployment.

`python scripts/neon_e2e.py` is an **opt-in live check**. Read it before running: it starts a temporary configured app and needs real service access, creates a reserved test identity and fictional policy, calls the configured AI provider, and removes its generated test data. Provider quotas apply. The normal test suite needs no Neon account.

For the curated Render demo, follow render-demo.md instead. That profile uses automatic isolated visitor sessions and database-backed fictional originals, regardless of the full app's optional managed-service settings.
