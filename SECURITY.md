# Security

This project is under active development. The public demo is for fictional data and is not a supported production service or security certification.

Do not put credentials, private documents or exploit details in a public issue. Use GitHub private vulnerability reporting if enabled for this repository. If it is unavailable, open a minimal issue requesting a private reporting channel without disclosing the vulnerability; wait for a private channel before sharing details.

For deployments, keep secrets outside Git, use HTTPS and secure cookies, follow docs/release-checklist.md, and verify tenant permissions, upload scanning, restricted parsing, backups and recovery on the actual host. Rotate any credential accidentally published; deleting it from the current file does not remove it from Git history.

Only test systems you control. Use fictional documents and disposable test identities for integration tests. The public workspace gives each visitor a separate expiring session; fictional source documents are shared, while conversations and reviews are scoped to each visitor. Never submit confidential information. Uploads, account administration and live OCR are disabled in the public profile.
