"""Explicit allowlist of repository-owned fictional business documents."""

from pathlib import Path

DIRECTORY = Path(__file__).parent / "static/demo/business"
DOCUMENTS = (
    ("Employee handbook 2026.pdf", "People", ("employee-handbook-2026.pdf",)),
    ("Hybrid work policy 2026.pdf", "People", ("hybrid-work-2026.pdf",)),
    ("Travel and expenses 2026.pdf", "Finance", ("travel-expenses-2026.pdf",)),
    ("Information security standard.pdf", "Security", ("information-security-2026.pdf",)),
    ("Employee onboarding playbook.pdf", "People", ("employee-onboarding-2026.pdf",)),
    ("Customer onboarding playbook.pdf", "Operations", ("customer-onboarding-2026.pdf",)),
    ("Atlas portal requirements.pdf", "Engineering", ("atlas-requirements-v1.pdf", "atlas-requirements-v2.pdf")),
)
PDF_NAMES = frozenset(name for _, _, versions in DOCUMENTS for name in versions)
