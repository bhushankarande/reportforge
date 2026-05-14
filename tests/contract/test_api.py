from fastapi.testclient import TestClient

from app.main import create_app


def test_create_job_endpoint_returns_job_id():
    client = TestClient(create_app())

    response = client.post(
        "/jobs",
        json={"topic": "AI reporting", "type": "market_research", "depth": "standard", "provider": "gemini"},
    )

    assert response.status_code == 202
    assert response.json()["job_id"]


def test_get_job_progress_endpoint_returns_status():
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={"topic": "AI reporting", "type": "market_research", "depth": "standard", "provider": "gemini"},
    ).json()

    response = client.get(f"/jobs/{created['job_id']}/progress")

    assert response.status_code == 200
    assert response.json()["job_id"] == created["job_id"]


def test_job_outputs_sources_sections_and_markdown_export(monkeypatch):
    def fake_fetch(url):
        return (
            "AI Reporting Source",
            (
                "The central takeaway is that AI reporting is moving from a research idea toward "
                "usable planning and control patterns. From a market perspective, the important "
                "signal is that language interfaces can lower the friction of programming and "
                "operating reports. Technically, the relevant shift is the connection between "
                "language understanding, task decomposition, and report action selection. The main "
                "risk is that impressive demonstrations can overstate readiness unless they are tied "
                "to reliable execution evidence. "
                "AI reporting systems use language models to gather source evidence, draft "
                "structured report sections, and verify claims against citations. The reporting "
                "workflow depends on source-grounded generation, traceable claims, cost tracking, "
                "and reviewable exports for business users. "
            )
            * 4,
        )

    monkeypatch.setattr("agents.research_agent.fetch_url_text", fake_fetch)
    client = TestClient(create_app())
    created = client.post(
        "/jobs",
        json={
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "gemini",
            "urls": ["https://example.com/ai-reporting?utm_source=test"],
        },
    ).json()

    sections = client.get(f"/jobs/{created['job_id']}/sections")
    sources = client.get(f"/jobs/{created['job_id']}/sources")
    export = client.get(f"/jobs/{created['job_id']}/export/markdown")

    assert sections.status_code == 200
    assert sections.json()
    assert len(sections.json()) >= 2
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
