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
        "gemini",
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
            "provider": "gemini",
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
