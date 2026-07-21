from pathlib import Path

from fastapi.testclient import TestClient

from backend.pecker.main import create_app


REVIEW_TEXT = """# Synthetic Search Notes
## Goal
Improve search.
## Scope
TBD before implementation.
"""


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_path=tmp_path / "api.db",
        samples_directory=Path(__file__).parents[1] / "samples",
    )
    return TestClient(app)


def _create_review(client: TestClient) -> dict:
    response = client.post(
        "/api/reviews",
        json={"title": "Synthetic Search Notes", "content": REVIEW_TEXT},
    )
    assert response.status_code == 201
    return response.json()


def test_health_exposes_deterministic_demo_mode(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "deterministic-demo"}


def test_app_uses_pecker_db_path_for_persistence(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "configured" / "demo.db"
    monkeypatch.setenv("PECKER_DB_PATH", str(database))
    app = create_app(samples_directory=Path(__file__).parents[1] / "samples")

    response = TestClient(app).post(
        "/api/reviews",
        json={"title": "Synthetic Search Notes", "content": REVIEW_TEXT},
    )

    assert response.status_code == 201
    assert database.is_file()


def test_samples_endpoint_returns_both_synthetic_samples(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/samples")

    assert response.status_code == 200
    payload = response.json()
    assert [sample["id"] for sample in payload["samples"]] == [
        "export-center",
        "team-notes-search",
    ]
    assert all(sample["synthetic"] for sample in payload["samples"])


def test_create_and_get_review_endpoints_return_the_persisted_snapshot(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    created = _create_review(client)
    fetched = client.get(f"/api/reviews/{created['review_id']}")

    assert created["status"] == "completed"
    assert created["mode"] == "deterministic-demo"
    assert all("status" in run for run in created["worker_runs"].values())
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_unknown_review_ids_return_404_for_all_review_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/reviews/review-missing").status_code == 404
    assert (
        client.post("/api/reviews/review-missing/decisions", json=[]).status_code
        == 404
    )
    assert client.get("/api/reviews/review-missing/report").status_code == 404


def test_decision_endpoint_accepts_partial_lists_and_report_returns_markdown(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    review = _create_review(client)
    accepted, rejected = review["findings"][:2]

    updated = client.post(
        f"/api/reviews/{review['review_id']}/decisions",
        json=[
            {"finding_id": accepted["id"], "action": "accept"},
            {"finding_id": rejected["id"], "action": "reject"},
        ],
    )
    report = client.get(f"/api/reviews/{review['review_id']}/report")

    assert updated.status_code == 200
    assert updated.json()["findings"][0]["decision"] == {"action": "accept"}
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert accepted["title"] in report.text
    assert rejected["title"] not in report.text


def test_invalid_decisions_return_422(tmp_path: Path) -> None:
    client = _client(tmp_path)
    review = _create_review(client)
    finding_id = review["findings"][0]["id"]
    endpoint = f"/api/reviews/{review['review_id']}/decisions"

    missing_edit = client.post(
        endpoint,
        json=[{"finding_id": finding_id, "action": "edit"}],
    )
    blank_title_with_valid_recommendation = client.post(
        endpoint,
        json=[
            {
                "finding_id": finding_id,
                "action": "edit",
                "edited_title": "   ",
                "edited_recommendation": "A valid edited recommendation.",
            }
        ],
    )
    edit_on_accept = client.post(
        endpoint,
        json=[
            {
                "finding_id": finding_id,
                "action": "accept",
                "edited_title": "Not allowed",
            }
        ],
    )
    unknown_finding = client.post(
        endpoint,
        json=[{"finding_id": "finding-missing", "action": "reject"}],
    )

    assert missing_edit.status_code == 422
    assert blank_title_with_valid_recommendation.status_code == 422
    assert edit_on_accept.status_code == 422
    assert unknown_finding.status_code == 422


def test_create_review_rejects_blank_input(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/reviews", json={"title": " ", "content": "\n"}
    )

    assert response.status_code == 422


def test_cors_allows_localhost_development_origins_only(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }

    allowed = client.options(
        "/api/reviews",
        headers={**headers, "Origin": "http://localhost:3000"},
    )
    denied = client.options(
        "/api/reviews",
        headers={**headers, "Origin": "https://portfolio.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers
