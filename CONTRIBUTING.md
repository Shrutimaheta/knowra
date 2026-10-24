# Contributing

Open an issue describing a reproducible problem or proposed improvement before a large change. Keep pull requests focused and describe the behavior change, validation and remaining limitations.

Follow the local setup in README.md. Run the build, Ruff and tests before submitting. Use fictional test data and isolated temporary databases. Do not run destructive tests against an existing workspace or post private documents, credentials, real connection strings or mail-outbox files in issues.

Database changes belong in a new Alembic revision; preserve immutable source versions and existing citation links. Recheck workspace and private-document permissions whenever adding retrieval, preview or export paths. Describe UI changes with screenshots made from fictional fixtures only.

Cloud-dependent checks are opt-in. Never require a contributor's production credentials to run the ordinary test suite. Do not commit generated workspaces, local evaluation reports or provider responses containing private information.
