# Aster Vale demonstration document set

Eight professionally formatted, three-page PDFs describe **Aster Vale Technologies, a fictional company**, and its fictional Atlas customer portal. All approvals, transactions, policies and dates are invented. Every page is labelled accordingly; the files contain no real employee or customer data.

The set uses selectable native text, clear headings, document IDs, version numbers, effective dates, owners, small tables and cross-references. It is meant to exercise realistic retrieval and version workflows, not guarantee correct answers to arbitrary questions.

## Documents

| File | Document ID | What to demonstrate |
| --- | --- | --- |
| employee-handbook-2026.pdf | AV-HR-001 | Leave, probation, carryover, owner and scope |
| hybrid-work-2026.pdf | AV-HR-002 | Remote days, office days, equipment and exceptions |
| travel-expenses-2026.pdf | AV-FIN-001 | Deadlines, approvals, limits, receipt arithmetic |
| information-security-2026.pdf | AV-SEC-001 | MFA, reporting, classification and scoped retention |
| employee-onboarding-2026.pdf | AV-OPS-001 | First-week tasks and probation checkpoints |
| customer-onboarding-2026.pdf | AV-CS-001 | Readiness, implementation, acceptance and handover |
| atlas-requirements-v1.pdf | AV-PRD-001 v1.0 | Original requirements baseline |
| atlas-requirements-v2.pdf | AV-PRD-001 v2.0 | Approved CR-014 and updated acceptance criteria |

Canonical files are under `apps/api/app/static/demo/business/`. Two Atlas files represent **versions of one document**, not two independent current policies. Version 2 is current; version 1 remains available for comparison and old citations. The version-1 PDF preserves its original scope and does not invent knowledge of a later approval.

## Load into Knowra

In the full app, choose **Load sample data** as a workspace owner. It retains the original four lightweight fictional samples and adds seven document entries backed by these eight PDFs. The real ingestion worker extracts the PDFs and indexes their pages. Wait until the entries show Ready. Loading again skips existing sample titles; it does not erase documents or conversations.

The curated Render demo indexes these repository-owned PDFs at startup, alongside its existing two-year policy comparison and labelled image sample. It has 11 document entries, including the Atlas pair as two versions. This profile still does not run live OCR or permit public uploads. Native PDF extraction is not an OCR demonstration.

For a manual upload demonstration, upload `atlas-requirements-v1.pdf` first, then use **Add version** on that same document to upload version 2. Do not upload them as two separate current documents and then ask which requirement is current. Upload the remaining six PDFs as ordinary sources. Use a separate test workspace to avoid mixing the demonstration with unrelated files.

## Suggested question flow

| Question | Expected evidence |
| --- | --- |
| How many annual leave days do full-time employees receive? | Handbook p1: 24 working days per calendar year |
| How many unused days carry over, and until when? | Handbook p1: up to 5 days, used by 31 March |
| Which days are office collaboration days? | Hybrid work p1: Tuesday and Thursday |
| What equipment allowance remains after the fictional INR 4130 receipt? | Expenses p3: INR 870, assuming no earlier claims |
| When must I submit a purchase made on 10 October? | Expenses p1: by 25 October; 15 calendar days |
| When must a suspected security incident be reported? | Security p3: within 1 hour of discovery |
| When must a new hire finish security training? | Employee onboarding p2: by working day 5 |
| When does the customer implementation target start? | Customer onboarding p1: after the readiness gate is complete |
| What changed after CR-014? | Atlas v2 p3: XLSX added, retention 90 to 180 days, response 4 hours to 1 hour |
| What is the revised Atlas go-live date? | Atlas v2 p3: 07 July 2026, previously 30 June |

Open each citation and show the actual page. Compare Atlas versions 1 and 2; REQ-101 customer isolation is unchanged while REQ-102, REQ-103 and REQ-104 change. Then open the Knowledge Map to explore the indexed connections. Use the original 2025/2026 handbook fixtures for the existing possible-conflict demonstration; a superseded version is a change-history example, not automatically a current policy conflict.

The financial example is consistent across the hybrid and expense policies and the existing fictional receipt: INR 3500 + INR 630 = INR 4130; INR 5000 - INR 4130 = INR 870. Security-log retention and Atlas operational-request retention are explicitly different scopes, even when both currently use 180 days.

## Missing-evidence checks

Ask about parental leave, Atlas subscription pricing or a guaranteed uptime SLA. The documents explicitly do not define those commitments. A useful answer should acknowledge the missing policy or agreement rather than invent a value. Ask for the CEO's personal phone number to check an unsupported question. The documents contain no such number.

## Rebuild and verify

The committed PDFs do not require an authoring dependency at runtime. To rebuild their content/layout, install the optional authoring dependency `reportlab>=4,<5`, then run:

```sh
python scripts/create_demo_documents.py
python scripts/evaluate_demo_documents.py
```

`evals/demo-corpus.json` records 20 questions, exact source pages and evidence fragments, three missing-evidence questions and the expected version comparison. The evaluator checks extracted text and top-five source-page keyword retrieval on the current corpus; it does not call an AI provider or measure generated-answer truth. Integration tests also exercise the full sample-ingestion path, curated bootstrap, immutable originals and current-version-only retrieval.

Before sharing a hosted demo, repeat the question flow on that host, inspect citations and compare the two versions. Provider quotas, parsing failures, retrieval scope and input quality still affect results.
