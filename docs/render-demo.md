# Render + Neon curated demo

This profile is a free-tier public demonstration, not the full production deployment. The laptop is not needed after the cloud deployment starts. Render can sleep after inactivity and take time to wake. Neon retains the demo database independently of Render restarts, within its free-plan limits.

## Included and limited

- Includes 11 fictional document entries: the existing two-year handbook/policy examples and labelled receipt, plus six detailed business guides and two immutable Atlas requirements versions. The eight new PDFs total 24 pages; see demo-documents.md for the question flow.
- Supports keyword retrieval, Gemini cited answers, source previews, comparisons, conflict reviews and Knowledge Map links.
- No local semantic model, live OCR, public file uploads, signup, invitations or account administration. The memory-limited image omits PyTorch and the OCR runtime. Image extraction is labelled as a pre-indexed sample; it does not pretend to perform live OCR.
- Visitors open directly on the dashboard without credentials. A random, HttpOnly session identifies a separate viewer account; chats, feedback and review decisions are private to that visitor. Sessions expire after 24 hours. Do not enter private data. Questions are capped at 8 per visitor per UTC day, 3 per minute and 60 for the whole demo per UTC day, including failed attempts. Search and document browsing remain available after the question budget is exhausted. Clearing cookies does not reset the shared budget.
- At most 250 visitor records are admitted. Expired visitors and their conversations/reviews are cleaned as new visitors arrive, in batches of 25. This is bounded demonstration access, not an abuse-proof public identity system.
- The full production Compose deployment keeps its existing separate worker, scanning, parser and semantic-model configuration.

## Account setup and deploy

1. Create free Render and Neon accounts yourself. Select Free plans; do not add paid services. Current limits: https://render.com/docs/free and https://neon.com/pricing .
2. Create a NEW, dedicated Neon project/database for this fictional demo. Do not use your real workspace database. Copy its DIRECT PostgreSQL connection string with `sslmode=require` (or stronger) and the provider's channel binding option. A direct connection is used because startup performs migrations. Keep credentials private.
3. Publish this repository to GitHub with the root `render.yaml` and `apps/api/Dockerfile.demo` intact. Do not commit .env, databases, uploads or backups. The full repository includes the lightweight profile, so no separate demo repository is needed. For a minimal source-only handoff, `python scripts/package_render_demo.py` can alternatively produce an allowlisted demo zip.
4. In Render, create a Blueprint from that repository using `render.yaml`. It specifies one FREE Docker web service and creates no paid worker or Render database.
5. Enter DATABASE_URL (the new Neon URL), DEMO_PASSWORD (a unique 12–128 character reviewer password), and GEMINI_API_KEY privately in Render. The working default is `gemini-3.5-flash`; quota/availability can change. Do not commit secrets to Git or paste them in chat.
6. Render supplies RENDER_EXTERNAL_URL and PORT. The entry point sets HTTPS cookies, the exact public origin, one web process, automatic migrations, disabled embeddings and no embedded ingestion worker. Startup creates only fictional sources and accepts only the dedicated source owner plus registered visitor records; unrelated workspaces are refused.
7. Once deployed, open the Render HTTPS address: it automatically creates or resumes a private visitor session and opens Overview. No credentials or Try demo button are needed. DEMO_PASSWORD remains a private bootstrap-owner secret for compatibility and must not be published. Set DEMO_PUBLIC_DASHBOARD=false to restore the password-gated profile. The full application outside APP_ENV=demo keeps its existing authentication.

## Acceptance checks

Open the library and all 11 document entries. Ask “How many annual leave days are allowed in 2026?” and open its citation. Compare Workplace policy versions 1/2. Scan Handbook 2025/2026 for possible conflicts and save a personal decision. Inspect the receipt and its labelled extracted text. Open Knowledge Map, then create an answer and reopen its source link. Restart the service and verify conversations/sources still exist in Neon. Confirm signup, uploads, document deletion and invitations return 403. Use two separate browser profiles to verify that chats, feedback and conflict reviews are not shared. Verify reload resumes the same visitor and that exhausted question budgets never invoke the provider.

The 512 MB container profile and Neon connectivity were verified on Render/CI for the initial release; repeat these checks for each relevant change. A successful local test does not prove memory capacity or external-provider uptime. If the free instance runs out of memory, keep it offline while adjusting the demo; do not silently upgrade to a paid plan or describe the full production stack as verified.

Keep usage within both providers' free allowances. No off-host backup schedule, SMTP, public account or cloud service is provisioned merely by preparing this bundle. Export private database backups before deleting a Neon project. Follow the separate production release checklist for real customers.
