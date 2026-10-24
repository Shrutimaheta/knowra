# Free demo hosting

The supported lightweight demo route is Render with a dedicated Neon PostgreSQL database. Follow [render-demo.md](render-demo.md). The root Blueprint declares one free web service and no paid worker or database.

The demo excludes uploads, live OCR and local semantic inference, and only seeds fictional fixtures. The full production stack has separate worker, parser, scanner and operational resource requirements; do not describe the free demo as a complete production deployment.

Check the host's current free-plan limits, cold starts, storage and service availability before deploying. Never upgrade billing automatically. Validate the deployed service and its memory usage before sharing a public URL.
