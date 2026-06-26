from frontend import streamlit_app as ui


class FakeUpload:
    def __init__(
        self,
        name: str = "notes.txt",
        content: bytes = b"source-grounded evidence",
        mime_type: str = "text/plain",
    ) -> None:
        self.name = name
        self._content = content
        self.type = mime_type

    def getvalue(self) -> bytes:
        return self._content


class FakeResponse:
    status_code = 201
    reason = "Created"
    text = ""
    content = b""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "job_id": "job-1",
            "files": ["notes.txt"],
            "source_ids": ["job-1-upload-source-1"],
            "chunks_indexed": 1,
        }


class FakeMetricColumn:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, object]] = []

    def metric(self, label: str, value: object) -> None:
        self.metrics.append((label, value))


class FakeStreamlit:
    def __init__(self) -> None:
        self.metric_columns = [FakeMetricColumn() for _ in range(4)]
        self.markdown_calls: list[tuple[str, bool]] = []
        self.progress_value: float | None = None

    def columns(self, count: int):
        assert count == 4
        return self.metric_columns

    def progress(self, value: float) -> None:
        self.progress_value = value

    def markdown(self, body: str, unsafe_allow_html: bool = False) -> None:
        self.markdown_calls.append((body, unsafe_allow_html))


def test_parse_urls_accepts_newlines_commas_and_deduplicates() -> None:
    urls = ui.parse_urls(
        "https://example.com/a\n"
        "https://example.com/b, https://example.com/a\n"
        "\n"
        "https://example.com/c"
    )

    assert urls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_submit_job_posts_stable_backend_contract(monkeypatch) -> None:
    captured = {}

    def fake_api_json(base_url, method, path, payload=None, params=None):
        captured.update(
            {
                "base_url": base_url,
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
            }
        )
        return {"job_id": "job-1", "status": "pending"}

    monkeypatch.setattr(ui, "api_json", fake_api_json)

    job_id = ui.submit_job(
        "http://backend",
        "AI reporting",
        "market_research",
        "standard",
        "nvidia",
        ["https://example.com/source"],
    )

    assert job_id == "job-1"
    assert captured == {
        "base_url": "http://backend",
        "method": "POST",
        "path": "/jobs",
        "payload": {
            "topic": "AI reporting",
            "type": "market_research",
            "depth": "standard",
            "provider": "nvidia",
            "urls": ["https://example.com/source"],
        },
        "params": None,
    }


def test_upload_files_posts_multipart_files(monkeypatch) -> None:
    captured = {}

    def fake_post(url, files, timeout):
        captured["url"] = url
        captured["files"] = files
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ui.requests, "post", fake_post)

    result = ui.upload_files("http://backend", "job-1", [FakeUpload()])

    assert result == {
        "job_id": "job-1",
        "files": ["notes.txt"],
        "source_ids": ["job-1-upload-source-1"],
        "chunks_indexed": 1,
    }
    assert captured["url"] == "http://backend/jobs/job-1/uploads"
    assert captured["timeout"] == 90
    assert captured["files"] == [
        ("files", ("notes.txt", b"source-grounded evidence", "text/plain"))
    ]


def test_render_progress_keeps_operational_metrics() -> None:
    st = FakeStreamlit()

    ui._render_progress(
        st,
        {
            "status": "running",
            "active_agent": "WriterAgent",
            "current_step": "drafting section",
            "percent_complete": 45,
            "cost": {"prompt_tokens": 120, "completion_tokens": 30},
        },
    )

    markup, unsafe = st.markdown_calls[0]
    assert unsafe is True
    assert "Status" in markup
    assert "running" in markup
    assert "Agent" in markup
    assert "WriterAgent" in markup
    assert "Progress" in markup
    assert "drafting section" in markup
    assert "Cumulative tokens" in markup
    assert "150" in markup
    assert st.progress_value == 0.45


def test_progress_cards_escape_backend_text() -> None:
    markup = ui._progress_cards_markup(
        status="failed",
        agent="<script>alert(1)</script>",
        step="collecting <evidence>",
        tokens=9,
    )

    assert "<script>" not in markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markup
    assert "collecting &lt;evidence&gt;" in markup


def test_report_markup_renders_continuous_report_without_claim_table() -> None:
    markup = ui._report_markup(
        [
            {
                "title": "Summary",
                "status": "drafted",
                "content": (
                    "## Summary\n\n"
                    "AI reporting is accelerating planning. [Web1]\n\n"
                    "- Faster synthesis\n"
                    "- Better evidence trails"
                ),
                "claims": [
                    {
                        "text": "AI reporting is accelerating planning.",
                        "confidence": 0.92,
                        "verification_status": "SUPPORTED",
                    }
                ],
            },
            {
                "title": "Risks",
                "status": "drafted",
                "content": "Teams still need review gates. [Web2]",
            },
        ]
    )

    assert markup.count("rf-report-section") == 2
    assert "AI reporting is accelerating planning." in markup
    assert '<span class="rf-citation">[Web1]</span>' in markup
    assert "Faster synthesis" in markup
    assert "Confidence" not in markup
    assert "0.92" not in markup
    assert "SUPPORTED" not in markup


def test_source_cards_escape_content_and_reject_unsafe_links() -> None:
    markup = ui._sources_markup(
        [
            {
                "title": "<script>alert(1)</script>",
                "citation_key": "[Web1]",
                "summary": "Useful <evidence> summary",
                "url": "javascript:alert(1)",
                "relevance_score": 0.81,
            }
        ]
    )

    assert "<script>" not in markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markup
    assert "javascript:alert" not in markup
    assert "Score 81%" in markup
    assert "Useful &lt;evidence&gt; summary" in markup
