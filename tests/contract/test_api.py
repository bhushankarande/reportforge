from fastapi.testclient import TestClient

from app.main import create_app


def test_create_job_endpoint_returns_job_id():
    client = TestClient(create_app())

    response = client.post(
        "/jobs",
        json={"topic": "AI reporting", "type": "market_research", "depth": "standard"},
    )

    assert response.status_code == 202
    assert response.json()["job_id"]


def test_get_job_progress_endpoint_returns_status():
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={"topic": "AI reporting", "type": "market_research", "depth": "standard"},
    ).json()

    response = client.get(f"/jobs/{created['job_id']}/progress")

    assert response.status_code == 200
    assert response.json()["job_id"] == created["job_id"]


def test_job_outputs_sources_sections_and_markdown_export():
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={"topic": "AI reporting", "type": "market_research", "depth": "standard"},
    ).json()

    sections = client.get(f"/jobs/{created['job_id']}/sections")
    sources = client.get(f"/jobs/{created['job_id']}/sources")
    export = client.get(f"/jobs/{created['job_id']}/export/markdown")

    assert sections.status_code == 200
    assert sections.json()
    assert sources.status_code == 200
    assert sources.json()
    assert export.status_code == 200
    assert "# AI reporting" in export.text


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model_ready"] is True


def test_quota_endpoint_returns_remaining_counts():
    client = TestClient(create_app())

    response = client.get("/costs/quota")

    assert response.status_code == 200
    assert "gemini_requests_remaining" in response.json()
