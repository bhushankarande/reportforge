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
