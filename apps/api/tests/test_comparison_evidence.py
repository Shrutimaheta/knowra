import base64
import io
from pathlib import Path

import numpy as np
import pytest
from app.comparison import compare_pages
from app.evidence import locate
from fastapi import HTTPException
from PIL import Image
from test_image_uploads import picture
from test_workflows import register, upload


def versions(client):
    sample = Path(__file__).parents[1] / "app/static/demo"
    old = (sample / "policy-2025.pdf").read_bytes()
    new = (sample / "policy-2026.pdf").read_bytes()
    response = client.post(
        "/api/v1/documents", files={"file": ("policy.pdf", old, "application/pdf")}
    )
    assert response.status_code == 201
    created = response.json()
    response = client.post(
        f"/api/v1/documents/{created['id']}/versions",
        files={"file": ("policy-2026.pdf", new, "application/pdf")},
    )
    assert response.status_code == 201
    return created["id"], created["version_id"], response.json()["version_id"], old


def test_comparison_tracks_changed_values_additions_removals_and_line_wraps():
    result = compare_pages(
        ["Annual leave is 20 days.\nRemote work is allowed."],
        ["Annual leave is 24 days.\nRemote work is allowed."],
    )
    assert result["counts"] == {"modified": 1, "added": 0, "removed": 0}
    change = result["changes"][0]
    assert any(
        s["text"].strip() == "20" and s["changed"] for s in change["before"]["segments"]
    )
    assert any(
        s["text"].strip() == "24" and s["changed"] for s in change["after"]["segments"]
    )
    assert (
        compare_pages(["Annual leave is 24\ndays."], ["Annual leave is 24 days."])[
            "total"
        ]
        == 0
    )
    assert (
        compare_pages(
            ["Keep this sentence."], ["Keep this sentence.\nAdd another sentence."]
        )["counts"]["added"]
        == 1
    )
    assert (
        compare_pages(
            ["Keep this sentence.\nRemove this sentence."], ["Keep this sentence."]
        )["counts"]["removed"]
        == 1
    )


def test_identical_documents_limits_and_truncated_results_are_explicit():
    assert compare_pages(["Same text."], ["Same text."])["changes"] == []
    result = compare_pages(
        ["Keep."], ["Keep. " + " ".join(f"Addition {n}." for n in range(210))]
    )
    assert result["truncated"] and len(result["changes"]) == 200
    assert result["counts"]["added"] == 210
    with pytest.raises(HTTPException) as caught:
        compare_pages(["a" * 400_001], ["b"])
    assert caught.value.status_code == 413


def test_pdf_comparison_links_immutable_pages_and_highlights_original(client):
    register(client)
    document, before, after, original = versions(client)
    path = f"/api/v1/documents/{document}"
    response = client.get(path + f"/compare?from_version={before}&to_version={after}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["before"]["id"] == before and result["after"]["number"] == 2
    changed = next(
        c for c in result["changes"] if c["before"] and "30 days" in c["before"]["text"]
    )
    assert changed["before"]["page"] == 2
    assert "15 days" in changed["after"]["text"]
    evidence_path = path + f"/versions/{before}/evidence"
    response = client.post(
        evidence_path, json={"page": 2, "text": changed["before"]["text"]}
    )
    assert response.status_code == 200
    evidence = response.json()
    assert evidence["ranges"][0]["exact"] and evidence["boxes"]
    image = Image.open(io.BytesIO(base64.b64decode(evidence["image"].split(",", 1)[1])))
    pixels = np.asarray(image.convert("RGB"))
    assert (
        (pixels[:, :, 0] > 200) & (pixels[:, :, 1] > 150) & (pixels[:, :, 2] < 200)
    ).any()
    assert client.get(path + f"/versions/{before}/original").content == original
    assert (
        client.post(
            evidence_path,
            json={"page": 1, "text": "an unrelated nonexistent zookeeper statement"},
        ).json()["ranges"]
        == []
    )
    assert (
        client.post(evidence_path, json={"page": 3, "text": "something"}).status_code
        == 404
    )
    assert (
        client.get(
            path + f"/compare?from_version={before}&to_version={before}"
        ).status_code
        == 422
    )
    reverse = client.get(
        path + f"/compare?from_version={after}&to_version={before}"
    ).json()
    assert reverse["before"]["number"] == 2 and reverse["after"]["number"] == 1
    client.post("/api/v1/auth/logout")
    register(client, "another-workspace@example.test")
    assert (
        client.get(
            path + f"/compare?from_version={before}&to_version={after}"
        ).status_code
        == 404
    )
    assert (
        client.post(
            evidence_path, json={"page": 2, "text": "Expense deadline"}
        ).status_code
        == 404
    )


def test_wrong_version_and_pending_versions_do_not_compare(client, monkeypatch):
    register(client)
    first = upload(client, "First document.")
    other = upload(client, "Another document.")
    a = client.get(f"/api/v1/documents/{first}/versions").json()[0]["id"]
    b = client.get(f"/api/v1/documents/{other}/versions").json()[0]["id"]
    assert (
        client.get(
            f"/api/v1/documents/{first}/compare?from_version={a}&to_version={b}"
        ).status_code
        == 404
    )
    monkeypatch.setenv("EAGER_INGESTION", "false")
    pending = client.post(
        f"/api/v1/documents/{first}/versions",
        files={"file": ("pending.txt", b"New version.", "text/plain")},
    ).json()["version_id"]
    assert (
        client.get(
            f"/api/v1/documents/{first}/compare?from_version={a}&to_version={pending}"
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/documents/{first}/versions/{pending}/evidence",
            json={"page": 1, "text": "New version."},
        ).status_code
        == 409
    )


def test_private_sources_are_hidden_from_other_members(client):
    register(client)
    document = upload(client, "Private policy has 20 days.", visibility="private")
    before = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]
    after = client.post(
        f"/api/v1/documents/{document}/versions",
        files={"file": ("new.txt", b"Private policy has 24 days.", "text/plain")},
    ).json()["version_id"]
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
        client.get(
            f"/api/v1/documents/{document}/compare?from_version={before}&to_version={after}"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/documents/{document}/versions/{before}/evidence",
            json={"page": 1, "text": "Private policy"},
        ).status_code
        == 404
    )


def test_scan_evidence_is_highlighted_locally_and_never_fabricated(client):
    register(client)
    response = client.post(
        "/api/v1/documents", files={"file": ("icmp.png", picture(), "image/png")}
    )
    created = response.json()
    path = f"/api/v1/documents/{created['id']}/versions/{created['version_id']}"
    evidence = client.post(
        path + "/evidence",
        json={"page": 1, "text": "ICMP reports network errors and supports ping"},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["boxes"] and evidence.json()["image"].startswith(
        "data:image/png;base64,"
    )
    missing = client.post(
        path + "/evidence",
        json={
            "page": 1,
            "text": "A totally unsupported unrelated explanation about elephants",
        },
    ).json()
    assert missing["image"] is None and missing["ranges"] == []


def test_unicode_offsets_and_partial_evidence_are_honest():
    text = "Straße: Die jährliche Urlaubszeit beträgt 24 Tage."
    ranges = locate(text, "Die jährliche Urlaubszeit beträgt 24 Tage")
    assert (
        text[ranges[0]["start"] : ranges[0]["end"]]
        == "Die jährliche Urlaubszeit beträgt 24 Tage"
    )
    partial = locate(
        "A leave allowance is twenty four days per year.",
        "A leave allowance is twenty four days per year plus some invented words",
    )
    assert partial and not partial[0]["exact"]
    assert (
        locate(
            "Annual leave is 20 days.",
            "An unrelated paragraph containing leave and days in a different order",
        )
        == []
    )
