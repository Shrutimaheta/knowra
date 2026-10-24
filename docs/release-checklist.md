# Knowra release acceptance

Use this alongside deployment.md for the first public release. Configuration checks and local tests do not establish availability or security on a public host.

## Before starting public traffic

- Choose a Docker-capable host and domain, set DNS, and restrict inbound traffic to HTTPS, HTTP for certificate issuance, and operator access.
- Store real database, mail and model credentials privately. Use distinct migrator and runtime database passwords. Keep existing development data and backups private.
- Run all CI jobs: SQLite workflows, PostgreSQL/pgvector workflows, container migrations, JavaScript syntax checks and semantic retrieval evaluation.
- Build and retain a versioned application image. Record its digest, schema revision and dependency inventory for rollback. Current dependency ranges and image tags still require a verified release lock.
- Start the migration service once, then the API, worker and HTTPS proxy using the production override. Check service health and that port 8000 is not exposed publicly.
- Confirm worker processing and model availability with a fictional PDF, scanned page, image, table and a new document version. Check answers, citations, evidence highlighting, comparisons, conflicts and Knowledge Map links.
- Verify cross-workspace isolation with two accounts, including original files, private documents and historical source links.
- Send and redeem a real invitation and password-reset email. Confirm secure session cookies and logout/session revocation over the final HTTPS domain.
- Enable private encrypted database backups and perform an isolated restore drill. Originals live in the database and are included. Record recovery time and backup retention.
- Configure alerts for database storage, failed ingestion, queue backlog, repeated server failures and stale backups. Confirm a responsible operator receives them.
- Load-test the actual host and expected document sizes. Evaluate retrieval and grounded answers on representative documents; the six-question fictional suite is only a regression check.

## First release scope

Start with a controlled pilot and trusted uploads. Untrusted public document ingestion needs parser isolation and malware scanning before unrestricted rollout. External SMTP, LLM availability, PostgreSQL restore, Docker topology and host monitoring must be verified in the target environment.

## Rollback

Retain the previous image and matching pre-migration backup. Stop traffic before restoring into a new empty database, verify sources and permissions, then switch traffic. Do not downgrade a running database or overwrite the only copy.
