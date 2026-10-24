# Deployment and operations

## Prerequisites

- A server with Docker and Compose 2.24.4+ (the production override uses `!reset`).
- A domain pointing at that server, with inbound ports 80 and 443 available.
- Independent URL-safe migrator and runtime database passwords, and SMTP credentials.
- A plan for private encrypted backups and restoring into an isolated environment.

No server, domain, external mail account or public deployment is configured by this repository. Docker is absent from the development computer, so the Compose topology remains unexecuted locally.

## Deploy

1. Copy `.env.example` to `.env`. Replace both database passwords. Set `DOMAIN`, `PUBLIC_URL=https://your-domain`, `APP_ENV=production`, `COOKIE_SECURE=true`, and SMTP values. Configure an AI key only if approved for your documents.
2. Set BACKUP_RECIPIENT to your age PUBLIC recipient and keep the private identity off the server. Run `docker compose -f compose.yaml -f compose.production.yaml -f compose.operations.yaml config --quiet` to validate without printing secrets.
3. Run `docker compose -f compose.yaml -f compose.production.yaml -f compose.operations.yaml up --build -d`.
4. Confirm the migration service completed, the API is healthy and the worker is running. Caddy provisions HTTPS for the configured domain.
5. Create the owner account, upload a fictional test source, confirm indexing, ask a question, open the immutable source and test an invitation/recovery message before uploading real documents.

The initial database startup creates a runtime role with DML rights; migrations use a separate privileged role. The initialization script runs only for a new database volume. Upgrading an existing PostgreSQL volume requires provisioning that runtime role separately; do not delete the volume to rerun initialization.

The production API has no published host port. Only the reverse proxy accepts public traffic. Its trusted forwarded headers apply only on this private deployment network. Do not expose the API directly with unrestricted forwarded-header trust. The exact PUBLIC_URL is used for Origin checking. Internal readiness details are hidden by Caddy.

The API and worker refuse production startup without a PostgreSQL connection with a non-placeholder password, an HTTPS origin, secure cookies, SMTP delivery settings, and separate migration/worker operation. These checks validate configuration, not provider connectivity: test actual email delivery and database access as part of release acceptance. The release migrator intentionally runs separately from application startup.

## Monitor

- `/api/v1/health` is a liveness endpoint. The internal `/api/v1/health/ready` verifies database access and reports migration revision, pending work and failed jobs. It is blocked at the public proxy.
- Request logs carry request ID, method, route, status and elapsed time without bodies or query strings. Model text is not logged by request middleware.
- Caddy access logging is disabled; use the application's structured request log to avoid retaining URL query parameters.
- Worker failures log job IDs; failed/retrying documents are visible in the library. Alert on sustained failed jobs, pending backlog, 5xx rates, database disk space and backup age.
- Configure your hosting platform's log retention and alerts. No external monitoring account has been provisioned.

## Back up and restore

Use managed PostgreSQL backups or schedule a native export. Example for the provided Compose database:

```sh
docker compose exec -T db pg_dump -U knowra_migrator -d knowra -Fc > knowra.dump
```

Save originals and identity data on private encrypted storage with access restricted to operators. Keep the application image and migration revision with each backup. Restore into an empty, isolated database and verify account counts, original checksums, source links and indexing before switching traffic. Never restore over the only running copy.

`scripts/backup.py` provides a portable gzip/JSON snapshot and refuses overwriting a backup or restoring into a populated target. It supports transferring a matching-revision SQLite database into PostgreSQL, including regenerating native vector values. This cross-backend restore path is implemented but has not been exercised locally against PostgreSQL. A SQLite round trip is tested.

The pre-upgrade SQLite copy is `apps/api/data/pre-upgrade.backup.db`. It is private and ignored by version control. Restored running ingestion leases are requeued; active chat leases and request-limit windows are discarded. Do not back up or publish development mail-outbox files as ordinary documentation.

## Release and rollback

CI contains SQLite integration tests, real PostgreSQL/pgvector workflows in isolated schemas, a container migration smoke check and report artifacts. Run those jobs before a release. Pin image digests and dependency locks in your deployment pipeline after the verified build; tags/ranges in this development repository are not a locked release manifest.

Run only one migrator per release, then start runtime services with AUTO_MIGRATE=false. Application shutdown does not erase jobs. Rollback should use a tested database backup and matching previous image because destructive schema downgrades are intentionally disabled.

## Remaining work before a larger customer rollout

The production override now includes ClamAV scanning and a restricted internal parser service; the operations override adds age-encrypted daily backups. Host monitoring units and a native restore drill are supplied. Execute these services on the actual host, verify signature updates, off-host retention/restores, load-test the real corpus and model under expected concurrency, run adversarial retrieval and claim-grounding evaluations, validate SMTP/LLM integrations, perform an access-control/security review, and provision host-level secret management. Originals use the database by default; optional private Neon storage is described in neon.md. Portable snapshots materialize external originals. This code is not a security certification or availability guarantee.

See [the free-hosting handoff](free-hosting.md) for the free-tier route, restricted parser details, monitoring activation and account-side prerequisites. The Gemini 3.5 Flash endpoint returned a cited live answer using the existing key during verification; no billing settings were changed.
