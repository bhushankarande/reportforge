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


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
