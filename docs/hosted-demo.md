# Hosted demo

Live address: https://knowra-demo.onrender.com

Deployed on 24 October 2026 using Render's Free Docker web service and a separate Neon demo database. This is the curated fictional-data profile, not the full production stack. The deployed application commit is `61e1a64`; subsequent documentation updates do not change its behavior.

## Verified on the hosted service

- PostgreSQL readiness at migration 0006; 11 ready documents and 13 immutable versions.
- Reviewer login, Secure/HttpOnly/SameSite session cookies, logout and protected access denial.
- All 20 expected source-page searches in the expanded fictional corpus.
- Original PDF checksum, source page preview and highlighted evidence.
- Atlas version comparison, conversation storage and Knowledge Map citation/version links.
- Public uploads, registration and invitations remain disabled.
- Gemini returned a cited annual-leave answer in about 3 seconds in one observed request. The initial hosted request returned explicitly labelled source excerpts during provider unavailability; a later request succeeded. This is a transient-provider fallback, not a claim that every question is AI-synthesized.
- Browser sign-in, library, requirements comparison, interactive map selection, streamed Gemini answer and citation opening were checked against the public HTTPS service.
- A controlled Render restart preserved the existing session, all 11 document identities and a temporary conversation. New instance startup was confirmed from lifecycle logs. The temporary restart-check conversation was removed.

The four GitHub verification jobs passed before deployment: SQLite, PostgreSQL, semantic retrieval and container checks. The container checks include the curated fixture bootstrap under a 512 MB memory limit.

During brief single-reviewer checks, Render reported memory below 165 MiB on the 512 MB instance. Twenty source searches measured a median network-inclusive response time of about 0.51 seconds from the development connection. These observations are not concurrent-load, cold-start or availability guarantees.

## Data and credentials

The demo uses a dedicated database and a DML-only application login. Its ability to read the original workspace's users and document versions was explicitly checked and denied. The original workspace was not imported. The application login cannot create databases, roles or schema objects.

The reviewer email is `demo@knowra.example`. The owner supplies the reviewer password privately. Never add passwords, database URLs, API keys or the local deployment settings file to this repository. The shared reviewer account can see shared conversations and review decisions; use fictional information only.

The operator prepared the current schema using the private migration connection before provisioning the restricted runtime login. Future schema revisions must be migrated separately with the operator connection before updating the hosted app. Do not grant the public app the original workspace's credentials to work around migration permissions.

## Operational limits

Render can sleep while idle; a wake-up can take longer than a warm request. Provider quotas and model availability apply. Uploads, live OCR, account administration and local semantic inference are disabled. The receipt is explicitly labelled pre-indexed sample text.

This service was created through Render's authenticated API using the Dockerfile and build context from the root Blueprint. Auto-deploy is off; reviewed updates require a manual Render deployment. No paid worker, Render database, persistent disk or billing upgrade was created. Neon storage and compute usage still share the existing project's free allowances.

No scheduled off-host backups, independent uptime monitor, custom domain or production SMTP service has been provisioned for this demo. Follow release-checklist.md for a full deployment with real users and documents.
