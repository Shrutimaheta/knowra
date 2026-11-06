# Vercel deployment

Live application: https://knowra-ecru.vercel.app/

The public workspace runs the same FastAPI API, Gemini streaming, source previews,
version comparison and knowledge map as the lightweight Render profile. Its static
dashboard and browser assets are served by Vercel's CDN. Neon retains documents,
visitor sessions, conversations and question budgets across function instances.

Uploads, live OCR and account administration remain disabled in this public profile.
Use the full local/container deployment for ingestion and OCR workers.

## Prepare a deployment

Run `npm ci` and `npm run build` from the repository root, then:

```sh
python scripts/package_vercel.py
vercel link --cwd output/vercel-knowra
```

The packaging script allowlists application files and fictional sample documents.
It does not copy local environment files, databases, private files or test data.
Deploy this generated directory, not the entire repository.

Configure these server-only values in the Vercel project for Preview and Production:

- `DATABASE_URL`: the dedicated sample database's restricted runtime role, using
  the pooled Neon endpoint and TLS. Never use the original private workspace database.
- `DEMO_PASSWORD`: the existing private reviewer password; visitors do not need it.
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_PROVIDER=gemini`.
- `PUBLIC_URL`: the project's production HTTPS origin.

No credentials belong in `vercel.json`, source files or browser assets. Preview
origins are taken from Vercel's deployment environment. Mutation requests from
unrelated origins are rejected.

## Database release tasks

Before deployment, use the existing operator migration procedure to prepare schema
and fictional documents separately. The Vercel application deliberately disables
automatic migration, fixture bootstrap, model warmup and embedded workers. It uses
the existing SQLAlchemy/psycopg driver with Neon pooling and no persistent local pool.
Do not run the schema migrator with the restricted runtime role.

## Deploy and verify

```sh
vercel deploy --cwd output/vercel-knowra
```

Check dashboard entry, visitor isolation, source searches, cited streaming answers,
original PDFs, highlighted evidence, version comparison, knowledge map and insights
on the preview URL. Only then publish:

```sh
vercel deploy --prod --cwd output/vercel-knowra
```

Keep Render available until the new public deployment has passed these checks.
CDN delivery removes the Render wake-up wait for the page shell, but serverless
initialization, database wake-up and Gemini quotas can still affect API latency.

## Verification on 6 November 2026

Both the preview and public production deployments passed checks for direct
dashboard entry, secure visitor cookies, all 11 ready documents, source retrieval,
Atlas version comparison, original PDFs, page images, evidence highlighting,
Gemini streaming with citations, saved conversations, visitor isolation, knowledge
map and insights. Upload restrictions and cross-origin rejection were verified.
Temporary verification conversations were removed. Schema 0007 was already present;
the Vercel runtime performed no migration or fixture bootstrap.

The public dashboard HTML request took about 0.82 seconds in one measured request.
This is a single network-inclusive observation, not a guaranteed browser load time
or a benchmark for all regions or cold starts. The deployment uses the existing
free Hobby workspace; no paid plan was created. Render remains available.

The opening flow was subsequently reduced from five sequential API requests to
one authenticated dashboard-entry response. Three network-inclusive measurements
of the old API sequence were 4.01, 3.87 and 3.68 seconds; the optimized preview
measured 2.10, 1.62 and 1.52 seconds. These observations exclude page asset loading
and are not universal latency guarantees. Dashboard payloads remain uncached and
scoped to each authenticated visitor; returning visitors retain their own totals.
