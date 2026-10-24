from pathlib import Path

import pytest
from app.conflicts import detect
from app.store import db
from fastapi import HTTPException
from test_workflows import register, upload


def source(id, text, title=None):
    return {
        "document": id,
        "title": title or id,
        "version_id": "version-" + id,
        "version": 1,
        "uploaded": "2026-10-22T00:00:00Z",
        "pages": [text],
    }


def scan(client, documents):
    response = client.post("/api/v1/conflicts/scan", json={"documents": documents})
    assert response.status_code == 200, response.text
    return response.json()


def review_payload(finding, **changes):
    return {
        "left_version": finding["sources"][0]["version_id"],
        "right_version": finding["sources"][1]["version_id"],
        "fingerprint": finding["id"],
        "status": "authoritative",
        "preferred_version": finding["sources"][1]["version_id"],
        "note": "The updated policy applies to this review.",
        **changes,
    }


def test_quantities_permissions_spelled_numbers_and_reversed_order():
    a = source(
        "a",
        "Annual leave allowance is 20 days. Employees can work remotely two days per week. Remote work is allowed.",
    )
    b = source(
        "b",
        "Annual leave allowance is 24 days. Employees can work remotely three days per week. Remote work is not allowed.",
    )
    result = detect([a, b])
    assert result["total"] == 3
    assert {f["kind"] for f in result["findings"]} == {"quantity", "permission"}
    assert {f["id"] for f in detect([b, a])["findings"]} == {
        f["id"] for f in result["findings"]
    }
    assert any(
        [s["value"] for s in f["sources"]] == ["2", "3"] for f in result["findings"]
    )
    selected = result["findings"][2]
    assert detect([a, b], target=selected["id"])["findings"][0]["id"] == selected["id"]


def test_no_false_conflicts_for_same_values_units_or_unrelated_topics():
    assert (
        detect(
            [
                source("a", "Annual leave is 20.0 days."),
                source("b", "Annual leave is twenty days."),
            ]
        )["total"]
        == 0
    )
    assert (
        detect(
            [
                source("a", "Annual leave is 20 days."),
                source("b", "Expense claims must be submitted within 24 days."),
            ]
        )["total"]
        == 0
    )
    assert (
        detect(
            [
                source("a", "Remote work is allowed two days per week."),
                source("b", "Remote work is allowed three days per month."),
            ]
        )["total"]
        == 0
    )
    assert (
        detect(
            [
                source("a", "Annual leave is 20 business days."),
                source("b", "Annual leave is 24 days."),
            ]
        )["total"]
        == 0
    )
    assert (
        detect(
            [
                source("a", "Equipment budget is INR 5000."),
                source("b", "Equipment budget is USD 100."),
            ]
        )["total"]
        == 0
    )
    assert (
        detect(
            [
                source(
                    "a", "Annual leave is 20 days and remote work is 2 days per week."
                ),
                source(
                    "b", "Annual leave is 24 days and remote work is 3 days per week."
                ),
            ]
        )["total"]
        == 0
    )


def test_scope_years_and_permission_contexts_are_visible():
    result = detect(
        [
            source(
                "a",
                "Contractors receive an annual leave allowance of 20 days.",
                "Handbook 2025",
            ),
            source(
                "b",
                "Permanent employees receive an annual leave allowance of 24 days.",
                "Handbook 2026",
            ),
        ]
    )
    assert result["total"] == 1
    warnings = " ".join(result["findings"][0]["warnings"])
    assert (
        "different years" in warnings
        and "eligibility" in warnings
        and "contractors" in warnings
    )
    result = detect(
        [
            source("a", "Employees are permitted to upload customer data."),
            source("b", "Employees are not permitted to upload customer data."),
        ]
    )
    assert result["total"] == 1 and result["findings"][0]["kind"] == "permission"
    assert (
        detect(
            [
                source("a", "Remote work is allowed."),
                source("b", "Employees must not work remotely."),
            ]
        )["total"]
        == 1
    )


def test_detection_limits_and_no_agreement_claim():
    with pytest.raises(HTTPException) as caught:
        detect([source("a", "x" * 400_001), source("b", "Annual leave is 24 days.")])
    assert caught.value.status_code == 413
    a = source("a", "\n\n".join(f"Annual leave is {n} days." for n in range(12)))
    b = source("b", "\n\n".join(f"Annual leave is {n + 20} days." for n in range(12)))
    result = detect([a, b])
    assert (
        result["total"] == 144
        and result["truncated"]
        and len(result["findings"]) == 100
    )
    result = detect(
        [
            source("a", "An unrelated statement."),
            source("b", "Something else entirely."),
        ]
    )
    assert result["claims_checked"] == 0 and "does not prove" in result["notice"]


def test_scan_pdf_pages_and_personal_review_survive_rescan(client):
    register(client)
    folder = Path(__file__).parents[1] / "app/static/demo"
    docs = []
    for year in (2025, 2026):
        response = client.post(
            "/api/v1/documents",
            files={
                "file": (
                    f"Handbook {year}.pdf",
                    (folder / f"policy-{year}.pdf").read_bytes(),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 201
        docs.append(response.json()["id"])
    result = scan(client, docs)
    assert result["total"] == 3 and result["review_scope"] == "personal"
    finding = next(
        f for f in result["findings"] if f["topic"] == "Expense claim deadline"
    )
    assert all(
        s["page"] == 2 and s["uploaded"] and s["version"] == 1
        for s in finding["sources"]
    )
    source_b = finding["sources"][1]
    evidence = client.post(
        f"/api/v1/documents/{source_b['document']}/versions/{source_b['version_id']}/evidence",
        json={"page": source_b["page"], "text": source_b["text"]},
    )
    assert evidence.status_code == 200 and evidence.json()["boxes"]
    payload = review_payload(finding)
    response = client.post("/api/v1/conflicts/review", json=payload)
    assert response.status_code == 200, response.text
    saved = next(
        f
        for f in scan(client, list(reversed(docs)))["findings"]
        if f["id"] == finding["id"]
    )["review"]
    assert (
        saved["preferred_version"] == payload["preferred_version"]
        and saved["note"] == payload["note"]
    )
    payload.update(
        status="dismissed",
        preferred_version=None,
        note="Different policy years explain this difference.",
    )
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 200
    assert (
        next(f for f in scan(client, docs)["findings"] if f["id"] == finding["id"])[
            "review"
        ]["status"]
        == "dismissed"
    )
    payload.update(status="open", preferred_version=None)
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 200
    with db() as c:
        assert (
            c.execute("SELECT COUNT(*) AS n FROM conflict_reviews").fetchone()["n"] == 1
        )


def test_old_preferences_and_stale_review_do_not_apply_to_new_versions(client):
    register(client)
    docs = [
        upload(client, "Annual leave is 20 days."),
        upload(client, "Annual leave is 24 days."),
    ]
    finding = scan(client, docs)["findings"][0]
    payload = review_payload(finding)
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 200
    client.post(
        f"/api/v1/documents/{docs[1]}/versions",
        files={"file": ("new.txt", b"Annual leave is 30 days.", "text/plain")},
    )
    changed = scan(client, docs)["findings"][0]
    assert changed["id"] != finding["id"] and changed["review"]["status"] == "open"
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 409


def test_reviews_are_personal_and_all_source_permissions_are_checked(client):
    register(client)
    public = upload(client, "Annual leave is 20 days.")
    private = upload(client, "Annual leave is 24 days.", visibility="private")
    finding = scan(client, [public, private])["findings"][0]
    payload = review_payload(finding)
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 200
    second_public = upload(client, "Annual leave is 28 days.")
    visible_finding = scan(client, [public, second_public])["findings"][0]
    assert (
        client.post(
            "/api/v1/conflicts/review", json=review_payload(visible_finding)
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/members",
        json={
            "name": "Reader",
            "email": "reader@example.test",
            "password": "reader-safe-password",
            "role": "viewer",
        },
    )
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.test", "password": "reader-safe-password"},
    )
    assert (
        client.post(
            "/api/v1/conflicts/scan", json={"documents": [public, private]}
        ).status_code
        == 404
    )
    assert client.post("/api/v1/conflicts/review", json=payload).status_code == 404
    own = scan(client, [public, second_public])["findings"][0]
    assert own["review"]["status"] == "open" and own["review"]["note"] == ""
    assert (
        client.post(
            "/api/v1/conflicts/review",
            json=review_payload(own, status="dismissed", preferred_version=None),
        ).status_code
        == 200
    )
    client.post("/api/v1/auth/logout")
    register(client, "outside@example.test")
    assert (
        client.post(
            "/api/v1/conflicts/scan", json={"documents": [public, second_public]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/conflicts/review", json=review_payload(visible_finding)
        ).status_code
        == 404
    )


def test_invalid_reviews_scans_and_pending_documents_are_actionable(
    client, monkeypatch
):
    register(client)
    docs = [
        upload(client, "Annual leave is 20 days."),
        upload(client, "Annual leave is 24 days."),
    ]
    finding = scan(client, docs)["findings"][0]
    assert (
        client.post(
            "/api/v1/conflicts/scan", json={"documents": [docs[0], docs[0]]}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/conflicts/scan", json={"documents": [docs[0]]}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/conflicts/review",
            json=review_payload(finding, preferred_version="not-a-source"),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/conflicts/review",
            json=review_payload(finding, fingerprint="0" * 64),
        ).status_code
        == 409
    )
    monkeypatch.setenv("EAGER_INGESTION", "false")
    client.post(
        f"/api/v1/documents/{docs[1]}/versions",
        files={"file": ("pending.txt", b"Annual leave is 30 days.", "text/plain")},
    )
    assert (
        client.post("/api/v1/conflicts/scan", json={"documents": docs}).status_code
        == 409
    )


def test_deleting_a_source_cleans_up_its_reviews(client):
    register(client)
    docs = [
        upload(client, "Annual leave is 20 days."),
        upload(client, "Annual leave is 24 days."),
    ]
    finding = scan(client, docs)["findings"][0]
    assert (
        client.post(
            "/api/v1/conflicts/review", json=review_payload(finding)
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/documents/{docs[0]}").status_code == 200
    with db() as c:
        assert (
            c.execute("SELECT COUNT(*) AS n FROM conflict_reviews").fetchone()["n"] == 0
        )
