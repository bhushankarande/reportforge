"""Streamlit frontend for ReportForge."""

from __future__ import annotations

from collections.abc import Iterable
import os
import time
from typing import Literal

import requests
from requests import HTTPError, RequestException, Response


API_BASE_URL = os.getenv("REPORTFORGE_API_URL", "http://localhost:8000")
REPORT_TYPES = {
    "Market Research": "market_research",
    "Company Profile": "company_profile",
    "Technical Report": "technical_report",
    "Investment Memo": "investment_memo",
    "Competitive Analysis": "competitive_analysis",
    "Policy Brief": "policy_brief",
    "Literature Review": "literature_review",
}
DEPTHS = {
    "Brief": "brief",
    "Standard": "standard",
    "Deep": "deep",
}
PROVIDERS = {
    "Gemini": "gemini",
    "Groq": "groq",
    "Ollama": "ollama",
    "Kimi": "kimi",
}
UPLOAD_TYPES = ["pdf", "docx", "csv", "xlsx", "xls", "txt", "md"]
ACTIVE_STATUSES = {"pending", "running"}
EXPORTS = {
    "markdown": ("Markdown", "text/markdown", "md"),
    "pdf": ("PDF", "application/pdf", "pdf"),
    "docx": (
        "DOCX",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
}

JsonObject = dict[str, object]
JsonList = list[dict[str, object]]
JsonData = JsonObject | JsonList
UploadFilePayload = tuple[str, tuple[str, bytes, str]]


class ApiClientError(RuntimeError):
    """User-visible backend/API error."""


def normalize_api_base(url: str) -> str:
    """Return a clean backend base URL."""
    return (url.strip() or API_BASE_URL).rstrip("/")


def parse_urls(raw_urls: str) -> list[str]:
    """Parse newline or comma separated URLs, preserving first-seen order."""
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in raw_urls.replace(",", "\n").splitlines():
        url = candidate.strip()
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def api_json(
    base_url: str,
    method: str,
    path: str,
    payload: JsonObject | None = None,
    params: dict[str, str] | None = None,
) -> JsonData:
    """Call the backend and return JSON data."""
    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            json=payload,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
    except HTTPError as exc:
        if exc.response is not None:
            raise ApiClientError(_response_detail(exc.response)) from exc
        raise ApiClientError(str(exc)) from exc
    except RequestException as exc:
        raise ApiClientError(f"Backend unavailable: {exc}") from exc

    return _response_json(response)


def api_bytes(base_url: str, path: str) -> bytes:
    """Download a binary export from the backend."""
    try:
        response = requests.get(f"{base_url}{path}", timeout=60)
        response.raise_for_status()
    except HTTPError as exc:
        if exc.response is not None:
            raise ApiClientError(_response_detail(exc.response)) from exc
        raise ApiClientError(str(exc)) from exc
    except RequestException as exc:
        raise ApiClientError(f"Backend unavailable: {exc}") from exc

    return response.content


def submit_job(
    base_url: str,
    topic: str,
    report_type: str,
    depth: str,
    provider: str,
    urls: list[str],
) -> str:
    """Submit a report job and return its id."""
    response = api_json(
        base_url,
        "POST",
        "/jobs",
        {
            "topic": topic,
            "type": report_type,
            "depth": depth,
            "provider": provider,
            "urls": urls,
        },
    )
    data = _expect_object(response, "Create job")
    job_id = data.get("job_id")
    if not isinstance(job_id, str):
        raise ApiClientError("Create job response did not include job_id.")
    return job_id


def upload_files(base_url: str, job_id: str, uploaded_files: Iterable[object]) -> JsonObject | None:
    """Send uploaded files to the job upload endpoint."""
    files = build_upload_payload(uploaded_files)
    if not files:
        return None

    try:
        response = requests.post(f"{base_url}/jobs/{job_id}/uploads", files=files, timeout=90)
        response.raise_for_status()
    except HTTPError as exc:
        if exc.response is not None:
            raise ApiClientError(_response_detail(exc.response)) from exc
        raise ApiClientError(str(exc)) from exc
    except RequestException as exc:
        raise ApiClientError(f"Backend unavailable: {exc}") from exc

    return _expect_object(_response_json(response), "Upload")


def build_upload_payload(uploaded_files: Iterable[object]) -> list[UploadFilePayload]:
    """Convert Streamlit UploadedFile objects into requests multipart payloads."""
    payload: list[UploadFilePayload] = []
    for uploaded_file in uploaded_files:
        filename = _uploaded_filename(uploaded_file)
        content = _uploaded_content(uploaded_file)
        mime_type = _uploaded_mime_type(uploaded_file)
        payload.append(("files", (filename, content, mime_type)))
    return payload


def main() -> None:
    """Run the Streamlit app."""
    try:
        import streamlit as st
    except ImportError:
        print("Streamlit is not installed. Run `uv sync` first.")
        return

    st.set_page_config(page_title="ReportForge", layout="wide")
    _init_session_state(st)

    backend_url, auto_refresh, refresh_seconds = _render_sidebar(st)

    st.title("ReportForge")
    _render_job_submission(st, backend_url)

    selected_job = _active_job_id(st)
    if selected_job is None:
        st.info("No active report jobs.")
        return

    try:
        progress = _expect_object(
            api_json(backend_url, "GET", f"/jobs/{selected_job}/progress"),
            "Progress",
        )
    except ApiClientError as exc:
        st.error(str(exc))
        return

    _render_progress(st, progress)
    _render_upload_result(st, selected_job)
    _render_job_actions(st, backend_url, selected_job, progress)

    source_tab, section_tab, export_tab = st.tabs(["Sources", "Sections", "Exports"])
    with source_tab:
        _render_sources(st, backend_url, selected_job)
    with section_tab:
        _render_sections(st, backend_url, selected_job)
    with export_tab:
        _render_exports(st, backend_url, selected_job, str(progress.get("status", "")))

    if auto_refresh and str(progress.get("status", "")) in ACTIVE_STATUSES:
        time.sleep(refresh_seconds)
        st.rerun()


def _render_sidebar(st):
    with st.sidebar:
        backend_url = normalize_api_base(st.text_input("Backend URL", value=API_BASE_URL))
        auto_refresh = st.toggle("Auto refresh", value=True)
        refresh_seconds = st.slider("Refresh seconds", 1, 10, 2)
        _render_job_picker(st)
        _render_quota(st, backend_url)
    return backend_url, auto_refresh, refresh_seconds


def _render_job_picker(st) -> None:
    jobs = st.session_state.jobs
    if not jobs:
        return

    active_job = st.session_state.active_job_id
    index = jobs.index(active_job) if active_job in jobs else 0
    picked_job = st.selectbox("Active job", jobs, index=index, key="job_picker")
    st.session_state.active_job_id = picked_job


def _render_quota(st, backend_url: str) -> None:
    try:
        quota = _expect_object(api_json(backend_url, "GET", "/costs/quota"), "Quota")
    except ApiClientError as exc:
        st.caption(str(exc))
        return

    st.metric("Gemini requests", quota.get("gemini_requests_remaining", 0))
    st.metric("Groq tokens", quota.get("groq_tokens_remaining", 0))


def _render_job_submission(st, backend_url: str) -> None:
    with st.form("create_report"):
        left, right = st.columns([2, 1])
        with left:
            topic = st.text_input("Topic", placeholder="AI-powered report automation market")
            url_text = st.text_area(
                "URLs",
                placeholder="https://example.com/report\nhttps://example.com/source",
                height=116,
            )
            uploaded_files = st.file_uploader(
                "Files",
                type=UPLOAD_TYPES,
                accept_multiple_files=True,
            )
        with right:
            report_type_label = st.selectbox("Report type", list(REPORT_TYPES))
            depth_label = st.selectbox("Depth", list(DEPTHS), index=1)
            provider_label = st.selectbox("Provider", list(PROVIDERS))

        submitted = st.form_submit_button("Generate report", type="primary")

    if not submitted:
        return

    if len(topic.strip()) < 3:
        st.error("Topic must be at least 3 characters.")
        return

    try:
        job_id = submit_job(
            backend_url,
            topic.strip(),
            REPORT_TYPES[report_type_label],
            DEPTHS[depth_label],
            PROVIDERS[provider_label],
            parse_urls(url_text),
        )
        _remember_job(st, job_id)
    except ApiClientError as exc:
        st.error(str(exc))
        return

    try:
        upload_result = upload_files(backend_url, job_id, uploaded_files)
    except ApiClientError as exc:
        st.warning(f"Job created, but upload failed: {exc}")
    else:
        if upload_result is not None:
            st.session_state.upload_results[job_id] = upload_result
        st.success(f"Submitted job {job_id}.")


def _render_progress(st, progress: JsonObject) -> None:
    columns = st.columns(5)
    columns[0].metric("Status", str(progress.get("status", "unknown")))
    columns[1].metric("Agent", str(progress.get("active_agent") or "idle"))
    columns[2].metric("Step", str(progress.get("current_step", "queued")))

    cost = progress.get("cost")
    if isinstance(cost, dict):
        tokens = _as_int(cost.get("prompt_tokens")) + _as_int(cost.get("completion_tokens"))
        kimi_cost = cost.get("estimated_kimi_cost_usd", "0.00")
    else:
        tokens = 0
        kimi_cost = "0.00"

    columns[3].metric("Tokens", tokens)
    columns[4].metric("Kimi estimate", f"${kimi_cost}")

    percent = _as_float(progress.get("percent_complete"))
    st.progress(max(0.0, min(percent, 100.0)) / 100.0)


def _render_upload_result(st, job_id: str) -> None:
    result = st.session_state.upload_results.get(job_id)
    if not isinstance(result, dict):
        return

    files = result.get("files", [])
    chunks = result.get("chunks_indexed", 0)
    if isinstance(files, list) and files:
        st.caption(f"Uploaded {len(files)} file(s), indexed {chunks} chunk(s).")


def _render_job_actions(st, backend_url: str, job_id: str, progress: JsonObject) -> None:
    status = str(progress.get("status", ""))
    if status == "awaiting_approval":
        st.warning("Approval required.")
        if st.button("Approve report", type="primary"):
            _run_action(st, lambda: api_json(backend_url, "POST", f"/jobs/{job_id}/approve"))
    elif status == "failed":
        st.error(str(progress.get("current_step", "Job failed.")))
        if st.button("Retry job", type="primary"):
            _run_action(st, lambda: api_json(backend_url, "POST", f"/jobs/{job_id}/retry"))


def _render_sources(st, backend_url: str, job_id: str) -> None:
    try:
        data = api_json(backend_url, "GET", f"/jobs/{job_id}/sources")
    except ApiClientError as exc:
        st.warning(str(exc))
        return

    if not isinstance(data, list) or not data:
        st.caption("No sources yet.")
        return

    rows = [
        {
            "Citation": _text(source.get("citation_key")),
            "Title": _text(source.get("title")),
            "Score": source.get("relevance_score", 0),
            "URL": _text(source.get("url")),
        }
        for source in data
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    for source in data:
        title = _text(source.get("title"), "Untitled source")
        citation = _text(source.get("citation_key"))
        with st.expander(f"{citation} {title}".strip()):
            url = _text(source.get("url"))
            if url:
                st.markdown(f"[{url}]({url})")
            summary = _text(source.get("summary"))
            if summary:
                st.write(summary)
            raw_text = _text(source.get("raw_text"))
            if raw_text:
                st.text_area("Raw text", raw_text[:3000], height=180, disabled=True)


def _render_sections(st, backend_url: str, job_id: str) -> None:
    try:
        data = api_json(backend_url, "GET", f"/jobs/{job_id}/sections")
    except ApiClientError as exc:
        st.warning(str(exc))
        return

    if not isinstance(data, list) or not data:
        st.caption("No sections yet.")
        return

    for section in sorted(data, key=_section_order):
        section_id = _text(section.get("id"))
        title = _text(section.get("title"), "Untitled section")
        status = _text(section.get("status"), "pending")
        order = _section_order(section) + 1
        with st.expander(f"{order}. {title} - {status}", expanded=True):
            content = _text(section.get("content"))
            if content:
                st.markdown(content)
            else:
                st.caption("No draft content yet.")

            _render_claims(st, section)
            feedback = st.text_area("Feedback", key=f"feedback_{section_id}", height=90)
            if st.button("Regenerate section", key=f"regen_{section_id}"):
                _regenerate_section(st, backend_url, job_id, section_id, feedback)


def _render_claims(st, section: JsonObject) -> None:
    claims = section.get("claims")
    if not isinstance(claims, list) or not claims:
        return

    rows = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        rows.append(
            {
                "Status": _text(claim.get("verification_status")),
                "Confidence": claim.get("confidence", 0),
                "Claim": _text(claim.get("text")),
                "Sources": ", ".join(str(source_id) for source_id in claim.get("source_ids", [])),
            }
        )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _regenerate_section(
    st,
    backend_url: str,
    job_id: str,
    section_id: str,
    feedback: str,
) -> None:
    if not section_id:
        st.error("Section id is missing.")
        return

    try:
        api_json(
            backend_url,
            "POST",
            f"/jobs/{job_id}/regenerate-section",
            params={"section_id": section_id, "feedback": feedback},
        )
    except ApiClientError as exc:
        st.error(str(exc))
    else:
        st.success("Section regenerated.")
        st.rerun()


def _render_exports(st, backend_url: str, job_id: str, status: str) -> None:
    if status != "completed":
        st.info("Exports are available after completion or approval.")
        return

    for export_format, (label, mime_type, extension) in EXPORTS.items():
        columns = st.columns([1, 3])
        export_key = (job_id, export_format)
        if columns[0].button(f"Prepare {label}", key=f"prepare_{job_id}_{export_format}"):
            try:
                st.session_state.exports[export_key] = api_bytes(
                    backend_url,
                    f"/jobs/{job_id}/export/{export_format}",
                )
            except ApiClientError as exc:
                columns[1].error(str(exc))

        data = st.session_state.exports.get(export_key)
        if data:
            columns[1].download_button(
                f"Download {label}",
                data=data,
                file_name=f"{job_id}.{extension}",
                mime=mime_type,
                key=f"download_{job_id}_{export_format}",
            )


def _run_action(st, action) -> None:
    try:
        action()
    except ApiClientError as exc:
        st.error(str(exc))
    else:
        st.rerun()


def _init_session_state(st) -> None:
    st.session_state.setdefault("jobs", [])
    st.session_state.setdefault("active_job_id", None)
    st.session_state.setdefault("upload_results", {})
    st.session_state.setdefault("exports", {})


def _remember_job(st, job_id: str) -> None:
    jobs = st.session_state.jobs
    if job_id in jobs:
        jobs.remove(job_id)
    jobs.insert(0, job_id)
    st.session_state.active_job_id = job_id
    st.session_state.exports = {
        key: value for key, value in st.session_state.exports.items() if key[0] != job_id
    }


def _active_job_id(st) -> str | None:
    jobs = st.session_state.jobs
    active_job = st.session_state.active_job_id
    if active_job in jobs:
        return active_job
    if jobs:
        st.session_state.active_job_id = jobs[0]
        return jobs[0]
    return None


def _response_json(response: Response) -> JsonData:
    try:
        data: object = response.json()
    except ValueError as exc:
        raise ApiClientError("Backend returned a non-JSON response.") from exc

    if isinstance(data, dict):
        return data
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return data
    raise ApiClientError("Backend returned an unexpected JSON response.")


def _response_detail(response: Response) -> str:
    try:
        data: object = response.json()
    except ValueError:
        message = response.text.strip() or response.reason
    else:
        if isinstance(data, dict):
            detail = data.get("detail", data)
            if isinstance(detail, list):
                message = "; ".join(_validation_message(item) for item in detail)
            else:
                message = str(detail)
        else:
            message = str(data)
    return f"{response.status_code}: {message}"


def _validation_message(item: object) -> str:
    if isinstance(item, dict) and "msg" in item:
        return str(item["msg"])
    return str(item)


def _expect_object(data: JsonData, label: str) -> JsonObject:
    if not isinstance(data, dict):
        raise ApiClientError(f"{label} returned an unexpected response.")
    return data


def _uploaded_filename(uploaded_file: object) -> str:
    filename = getattr(uploaded_file, "name", "upload.txt")
    if not isinstance(filename, str) or not filename.strip():
        return "upload.txt"
    return filename


def _uploaded_content(uploaded_file: object) -> bytes:
    getvalue = getattr(uploaded_file, "getvalue", None)
    if callable(getvalue):
        content = getvalue()
    else:
        read = getattr(uploaded_file, "read", None)
        if not callable(read):
            raise ApiClientError("Uploaded file cannot be read.")
        content = read()

    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    raise ApiClientError("Uploaded file returned unsupported content.")


def _uploaded_mime_type(uploaded_file: object) -> str:
    mime_type = getattr(uploaded_file, "type", None)
    if isinstance(mime_type, str) and mime_type:
        return mime_type
    return "application/octet-stream"


def _section_order(section: JsonObject) -> int:
    return _as_int(section.get("order"))


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extension(format_name: Literal["markdown", "pdf", "docx"]) -> str:
    """Return a file extension for an export format."""
    return "md" if format_name == "markdown" else format_name


if __name__ == "__main__":
    main()
