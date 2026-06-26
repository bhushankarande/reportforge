"""Streamlit frontend for ReportForge."""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
import os
import re
import time
from typing import Literal
from urllib.parse import urlparse

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
    "NVIDIA NIM": "nvidia",
    "Groq": "groq",
    "Ollama": "ollama",
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
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
CITATION_RE = re.compile(r"\[(?=[A-Za-z0-9])([A-Za-z0-9][A-Za-z0-9 _./:-]{0,40})\]")

THEME_CSS = """
<style>
:root {
  --rf-bg: #0c100e;
  --rf-surface: #121713;
  --rf-surface-2: #171d19;
  --rf-surface-3: #1d241f;
  --rf-border: #2b352f;
  --rf-border-strong: #3c493f;
  --rf-text: #f2f5f0;
  --rf-muted: #a5aea7;
  --rf-soft: #7e8a82;
  --rf-accent: #7dd8a8;
  --rf-accent-strong: #53c789;
  --rf-danger: #ff7a83;
  --rf-warning: #d6b46f;
  --rf-radius: 8px;
}

.stApp {
  background:
    linear-gradient(180deg, rgba(125, 216, 168, 0.06), transparent 280px),
    linear-gradient(135deg, #0c100e 0%, #0f1311 42%, #090c0b 100%);
  color: var(--rf-text);
}

header[data-testid="stHeader"],
.stAppHeader {
  background: rgba(12, 16, 14, 0.96) !important;
  border-bottom: 1px solid rgba(43, 53, 47, 0.72);
}

div[data-testid="stToolbar"],
div[data-testid="stToolbar"] * {
  color: var(--rf-muted) !important;
}

div[data-testid="stDecoration"] {
  display: none;
}

.block-container {
  max-width: 1480px;
  padding-top: 1.25rem;
  padding-bottom: 4rem;
}

section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #151a17 0%, #101411 100%);
  border-right: 1px solid var(--rf-border);
}

section[data-testid="stSidebar"] > div {
  padding-top: 1.4rem;
}

.rf-sidebar-title {
  color: var(--rf-text);
  font-size: 0.82rem;
  font-weight: 760;
  letter-spacing: 0.08em;
  margin: 0 0 1rem;
  text-transform: uppercase;
}

.rf-hero {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  padding: 1.25rem 1.35rem;
  margin-bottom: 1.25rem;
  background:
    linear-gradient(135deg, rgba(125, 216, 168, 0.12), rgba(125, 216, 168, 0.02) 48%, rgba(255, 255, 255, 0.03)),
    var(--rf-surface);
  box-shadow: 0 22px 70px rgba(0, 0, 0, 0.22);
}

.rf-hero h1 {
  margin: 0;
  color: var(--rf-text);
  font-size: 2.45rem;
  line-height: 1.05;
  letter-spacing: 0;
}

.rf-hero p {
  max-width: 760px;
  margin: 0.8rem 0 0;
  color: var(--rf-muted);
  font-size: 1rem;
  line-height: 1.6;
}

.rf-label {
  color: var(--rf-accent);
  font-size: 0.76rem;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.rf-section-heading {
  margin: 1.25rem 0 0.65rem;
  color: var(--rf-text);
  font-size: 1.08rem;
  font-weight: 760;
}

.rf-section-kicker {
  color: var(--rf-muted);
  font-size: 0.88rem;
  line-height: 1.55;
  margin: -0.3rem 0 0.85rem;
}

.rf-report-shell,
.rf-panel {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  background: rgba(18, 23, 19, 0.94);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035);
}

.rf-report-shell {
  padding: 1.15rem 1.2rem 1.35rem;
}

.rf-report-section {
  padding: 1.05rem 0 1.2rem;
  border-bottom: 1px solid rgba(43, 53, 47, 0.82);
}

.rf-report-section:first-child {
  padding-top: 0.25rem;
}

.rf-report-section:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.rf-report-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.65rem;
}

.rf-report-header h2 {
  margin: 0;
  color: var(--rf-text);
  font-size: 1.38rem;
  line-height: 1.25;
  letter-spacing: 0;
}

.rf-status-chip {
  flex: 0 0 auto;
  border: 1px solid var(--rf-border-strong);
  border-radius: var(--rf-radius);
  padding: 0.24rem 0.5rem;
  color: var(--rf-muted);
  background: var(--rf-surface-2);
  font-size: 0.74rem;
  font-weight: 720;
  text-transform: capitalize;
}

.rf-report-body {
  color: var(--rf-text);
  font-size: 1.02rem;
  line-height: 1.72;
}

.rf-report-body h2,
.rf-report-body h3,
.rf-report-body h4 {
  margin: 1.2rem 0 0.45rem;
  color: var(--rf-text);
  letter-spacing: 0;
  line-height: 1.25;
}

.rf-report-body h2 {
  font-size: 1.28rem;
}

.rf-report-body h3,
.rf-report-body h4 {
  font-size: 1.08rem;
}

.rf-report-body p {
  margin: 0.55rem 0 0.8rem;
  max-width: 82ch;
}

.rf-report-body ul,
.rf-report-body ol {
  margin: 0.55rem 0 0.95rem;
  padding-left: 1.35rem;
}

.rf-report-body li {
  margin: 0.38rem 0;
}

.rf-report-body blockquote {
  margin: 0.9rem 0;
  padding: 0.7rem 0.9rem;
  border-left: 3px solid var(--rf-accent);
  background: rgba(125, 216, 168, 0.06);
  color: var(--rf-muted);
}

.rf-report-body code {
  border: 1px solid var(--rf-border);
  border-radius: 6px;
  padding: 0.08rem 0.28rem;
  background: var(--rf-surface-2);
  color: var(--rf-accent);
}

.rf-report-body a,
.rf-source-card a {
  color: var(--rf-accent);
  text-decoration: none;
}

.rf-report-body a:hover,
.rf-source-card a:hover {
  text-decoration: underline;
}

.rf-citation {
  display: inline-block;
  border: 1px solid rgba(125, 216, 168, 0.35);
  border-radius: 6px;
  padding: 0.02rem 0.28rem;
  color: var(--rf-accent);
  background: rgba(125, 216, 168, 0.07);
  font-size: 0.84em;
  font-weight: 740;
  white-space: nowrap;
}

.rf-source-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

.rf-source-card,
.rf-export-panel,
.rf-empty {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  background: rgba(18, 23, 19, 0.92);
  padding: 0.9rem;
}

.rf-source-card h3 {
  margin: 0.35rem 0 0.45rem;
  color: var(--rf-text);
  font-size: 0.98rem;
  line-height: 1.35;
}

.rf-source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  color: var(--rf-soft);
  font-size: 0.75rem;
  font-weight: 700;
}

.rf-source-summary,
.rf-empty {
  color: var(--rf-muted);
  font-size: 0.9rem;
  line-height: 1.55;
}

.rf-source-summary {
  margin: 0;
}

.rf-export-panel {
  margin-top: 1rem;
}

.rf-export-title {
  color: var(--rf-text);
  font-size: 0.98rem;
  font-weight: 760;
  margin: 0 0 0.25rem;
}

.rf-export-copy {
  color: var(--rf-muted);
  font-size: 0.86rem;
  line-height: 1.5;
  margin: 0 0 0.85rem;
}

div[data-testid="stForm"] {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  padding: 1.25rem 1.35rem 1.35rem;
  background: rgba(18, 23, 19, 0.92);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035);
}

div[data-testid="stMetric"] {
  min-height: 118px;
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  padding: 1rem 1.05rem;
  background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.012)), var(--rf-surface);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

div[data-testid="stMetric"] label {
  color: var(--rf-muted) !important;
  font-size: 0.78rem !important;
  letter-spacing: 0.02em;
}

div[data-testid="stMetricValue"] {
  color: var(--rf-text);
  font-weight: 760;
}

.rf-progress-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.9rem;
  margin: 1.15rem 0 0.8rem;
}

.rf-progress-card {
  min-height: 112px;
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  padding: 0.95rem 1rem;
  background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.012)), var(--rf-surface);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.rf-progress-label {
  color: var(--rf-muted);
  font-size: 0.78rem;
  font-weight: 700;
  margin-bottom: 0.65rem;
}

.rf-progress-value {
  color: var(--rf-text);
  font-size: 2.15rem;
  font-weight: 760;
  letter-spacing: 0;
  line-height: 1.05;
  word-break: break-word;
}

.rf-progress-value.is-step {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 1.35rem;
  line-height: 1.16;
}

.rf-progress-card.is-running {
  border-color: rgba(125, 216, 168, 0.5);
}

.rf-progress-card.is-failed {
  border-color: rgba(255, 122, 131, 0.52);
}

.rf-progress-card.is-completed {
  border-color: rgba(125, 216, 168, 0.42);
}

.stProgress > div > div > div > div {
  background: linear-gradient(90deg, var(--rf-accent), #d7f7c5);
}

.stProgress > div > div > div {
  background: #1f2823;
}

.stTextInput input,
.stTextArea textarea,
div[data-baseweb="select"] > div {
  border: 1px solid var(--rf-border) !important;
  border-radius: var(--rf-radius) !important;
  background-color: var(--rf-surface-2) !important;
  color: var(--rf-text) !important;
}

.stTextInput label,
.stTextArea label,
.stSelectbox label,
.stFileUploader label,
.stSlider label,
.stToggle label,
div[data-testid="stWidgetLabel"],
div[data-testid="stWidgetLabel"] p {
  color: var(--rf-muted) !important;
  font-weight: 720 !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
  color: var(--rf-soft) !important;
  opacity: 1 !important;
}

.stTextInput input:focus,
.stTextArea textarea:focus,
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--rf-accent) !important;
  box-shadow: 0 0 0 2px rgba(125, 216, 168, 0.16) !important;
}

.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {
  min-height: 2.75rem;
  border: 1px solid rgba(125, 216, 168, 0.5) !important;
  border-radius: var(--rf-radius) !important;
  background: linear-gradient(180deg, var(--rf-accent), var(--rf-accent-strong)) !important;
  color: #07110c !important;
  font-weight: 800 !important;
  letter-spacing: 0;
  transition: transform 150ms ease, filter 150ms ease, box-shadow 150ms ease;
  box-shadow: 0 10px 26px rgba(83, 199, 137, 0.18);
}

.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {
  filter: brightness(1.04);
  transform: translateY(-1px);
}

.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active {
  transform: translateY(0);
}

button[kind="secondary"] {
  background: var(--rf-surface-2) !important;
  color: var(--rf-text) !important;
  border-color: var(--rf-border-strong) !important;
  box-shadow: none !important;
}

section[data-testid="stFileUploaderDropzone"],
div[data-testid="stFileUploaderDropzone"] {
  border: 1px dashed var(--rf-border-strong) !important;
  border-radius: var(--rf-radius) !important;
  background: var(--rf-surface-2) !important;
}

section[data-testid="stFileUploaderDropzone"] small,
section[data-testid="stFileUploaderDropzone"] span,
div[data-testid="stFileUploaderDropzone"] small,
div[data-testid="stFileUploaderDropzone"] span {
  color: var(--rf-muted) !important;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 0.4rem;
  border-bottom: 1px solid var(--rf-border);
}

.stTabs [data-baseweb="tab"] {
  border-radius: var(--rf-radius) var(--rf-radius) 0 0;
  color: var(--rf-muted);
  padding: 0.7rem 1rem;
}

.stTabs [aria-selected="true"] {
  color: var(--rf-accent) !important;
}

div[data-testid="stExpander"] {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  background: var(--rf-surface);
  overflow: hidden;
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--rf-border);
  border-radius: var(--rf-radius);
  overflow: hidden;
}

.stAlert {
  border-radius: var(--rf-radius);
}

@media (max-width: 900px) {
  .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
  }

  .rf-hero h1 {
    font-size: 2rem;
  }

  .rf-progress-value {
    font-size: 1.8rem;
  }

  .rf-progress-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .rf-report-header {
    display: block;
  }

  .rf-status-chip {
    display: inline-block;
    margin-top: 0.55rem;
  }
}

@media (max-width: 560px) {
  .rf-hero {
    padding: 1.25rem;
  }

  .rf-hero h1 {
    font-size: 1.65rem;
  }

  .rf-progress-grid {
    grid-template-columns: 1fr;
  }
}
</style>
"""


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
    _apply_theme(st)
    _init_session_state(st)

    backend_url, auto_refresh, refresh_seconds = _render_sidebar(st)

    _render_header(st)
    _render_job_submission(st, backend_url)

    selected_job = _active_job_id(st)
    if selected_job is None:
        st.markdown(
            '<div class="rf-empty">No active report jobs. Create a report to start.</div>',
            unsafe_allow_html=True,
        )
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

    report_column, support_column = st.columns([2.15, 1])
    with report_column:
        _render_sections(st, backend_url, selected_job)
    with support_column:
        _render_sources(st, backend_url, selected_job)
        _render_exports(st, backend_url, selected_job, str(progress.get("status", "")))

    if auto_refresh and str(progress.get("status", "")) in ACTIVE_STATUSES:
        time.sleep(refresh_seconds)
        st.rerun()


def _apply_theme(st) -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def _render_header(st) -> None:
    st.markdown(
        """
        <section class="rf-hero">
          <div class="rf-label">Evidence workbench</div>
          <h1>ReportForge</h1>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _progress_cards_markup(*, status: str, agent: str, step: str, tokens: int) -> str:
    status_class = _status_class(status)
    return f"""
    <div class="rf-progress-grid">
      <div class="rf-progress-card {status_class}">
        <div class="rf-progress-label">Status</div>
        <div class="rf-progress-value">{escape(status)}</div>
      </div>
      <div class="rf-progress-card">
        <div class="rf-progress-label">Agent</div>
        <div class="rf-progress-value">{escape(agent)}</div>
      </div>
      <div class="rf-progress-card">
        <div class="rf-progress-label">Progress</div>
        <div class="rf-progress-value is-step">{escape(step)}</div>
      </div>
      <div class="rf-progress-card">
        <div class="rf-progress-label">Cumulative tokens</div>
        <div class="rf-progress-value">{tokens}</div>
      </div>
    </div>
    """


def _status_class(status: str) -> str:
    normalized = status.lower().replace("_", "-")
    if normalized in {"running", "failed", "completed"}:
        return f"is-{normalized}"
    return ""


def _render_sidebar(st):
    with st.sidebar:
        st.markdown('<div class="rf-sidebar-title">Run controls</div>', unsafe_allow_html=True)
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

    st.metric("NVIDIA RPM", _quota_remaining(quota.get("nvidia_requests_per_minute_remaining")))
    st.metric("Groq RPM", _quota_remaining(quota.get("groq_requests_per_minute_remaining")))
    st.metric("Groq requests", _quota_remaining(quota.get("groq_requests_remaining")))
    st.metric("Groq tokens", _quota_remaining(quota.get("groq_tokens_remaining")))


def _render_job_submission(st, backend_url: str) -> None:
    st.markdown('<div class="rf-section-heading">Create report</div>', unsafe_allow_html=True)
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
    cost = progress.get("cost")
    if isinstance(cost, dict):
        tokens = _as_int(cost.get("prompt_tokens")) + _as_int(cost.get("completion_tokens"))
    else:
        tokens = 0

    st.markdown(
        _progress_cards_markup(
            status=str(progress.get("status", "unknown")),
            agent=str(progress.get("active_agent") or "idle"),
            step=str(progress.get("current_step", "queued")),
            tokens=tokens,
        ),
        unsafe_allow_html=True,
    )

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
    st.markdown('<div class="rf-section-heading">Evidence</div>', unsafe_allow_html=True)
    try:
        data = api_json(backend_url, "GET", f"/jobs/{job_id}/sources")
    except ApiClientError as exc:
        st.warning(str(exc))
        return

    if not isinstance(data, list) or not data:
        st.markdown(
            '<div class="rf-empty">Sources will appear here as research and uploads are processed.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(_sources_markup(data), unsafe_allow_html=True)


def _render_sections(st, backend_url: str, job_id: str) -> None:
    st.markdown('<div class="rf-section-heading">Generated report</div>', unsafe_allow_html=True)
    try:
        data = api_json(backend_url, "GET", f"/jobs/{job_id}/sections")
    except ApiClientError as exc:
        st.warning(str(exc))
        return

    if not isinstance(data, list) or not data:
        st.markdown(
            '<div class="rf-empty">The report draft will appear here as sections are generated.</div>',
            unsafe_allow_html=True,
        )
        return

    sections = sorted(data, key=_section_order)
    st.markdown(_report_markup(sections), unsafe_allow_html=True)

    st.markdown('<div class="rf-section-heading">Section revision</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="rf-section-kicker">Add focused feedback to regenerate one section without hiding the report.</div>',
        unsafe_allow_html=True,
    )
    for section in sections:
        section_id = _text(section.get("id"))
        title = _text(section.get("title"), "Untitled section")
        with st.expander(f"Revise {title}"):
            feedback = st.text_area(
                "Feedback",
                key=f"feedback_{section_id}",
                height=90,
                placeholder="Example: make the market sizing more concrete and keep the citations.",
            )
            if st.button("Regenerate section", key=f"regen_{section_id}"):
                _regenerate_section(st, backend_url, job_id, section_id, feedback)


def _report_markup(sections: list[JsonObject]) -> str:
    body = "\n".join(_report_section_markup(section) for section in sections)
    return f'<section class="rf-report-shell">{body}</section>'


def _report_section_markup(section: JsonObject) -> str:
    title = _text(section.get("title"), "Untitled section")
    status = _text(section.get("status"), "pending")
    content = _clean_section_content(_text(section.get("content")), title)
    if content:
        section_body = _markdown_to_report_html(content)
    else:
        section_body = '<p class="rf-source-summary">No draft content yet.</p>'
    return f"""
    <article class="rf-report-section">
      <div class="rf-report-header">
        <h2>{escape(title)}</h2>
        <span class="rf-status-chip">{escape(status.replace("_", " "))}</span>
      </div>
      <div class="rf-report-body">{section_body}</div>
    </article>
    """


def _sources_markup(sources: list[JsonObject]) -> str:
    cards = "\n".join(_source_card_markup(source) for source in sources)
    return f'<div class="rf-source-grid">{cards}</div>'


def _source_card_markup(source: JsonObject) -> str:
    title = _text(source.get("title"), "Untitled source")
    citation = _text(source.get("citation_key"))
    summary = _truncate(_text(source.get("summary")), 220)
    url = _text(source.get("url"))
    score = _score_label(source.get("relevance_score"))
    origin = _source_origin(url)
    link = _source_link(url)
    summary_html = (
        f'<p class="rf-source-summary">{escape(summary)}</p>'
        if summary
        else '<p class="rf-source-summary">No summary available yet.</p>'
    )
    return f"""
    <article class="rf-source-card">
      <div class="rf-source-meta">
        <span>{escape(citation or "Source")}</span>
        <span>{escape(score)}</span>
      </div>
      <h3>{escape(title)}</h3>
      <div class="rf-source-meta">{link or escape(origin)}</div>
      {summary_html}
    </article>
    """


def _markdown_to_report_html(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    html_parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            if text:
                html_parts.append(f"<p>{_format_inline(text)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items and list_tag:
            html_parts.append(f"<{list_tag}>{''.join(list_items)}</{list_tag}>")
            list_items.clear()
            list_tag = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            level = min(len(heading.group(1)) + 1, 4)
            html_parts.append(f"<h{level}>{_format_inline(heading.group(2))}</h{level}>")
            continue

        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if unordered or ordered:
            flush_paragraph()
            item_text = (unordered or ordered).group(1)
            next_tag = "ul" if unordered else "ol"
            if list_tag and list_tag != next_tag:
                flush_list()
            list_tag = next_tag
            list_items.append(f"<li>{_format_inline(item_text)}</li>")
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<blockquote>{_format_inline(stripped.lstrip('> '))}</blockquote>")
            continue

        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    return "\n".join(html_parts)


def _format_inline(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in MARKDOWN_LINK_RE.finditer(text):
        parts.append(_format_inline_plain(text[cursor : match.start()]))
        label = _format_inline_plain(match.group(1))
        url = match.group(2)
        if _is_safe_http_url(url):
            parts.append(
                f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                f"{label}</a>"
            )
        else:
            parts.append(label)
        cursor = match.end()
    parts.append(_format_inline_plain(text[cursor:]))
    return "".join(parts)


def _format_inline_plain(text: str) -> str:
    formatted = escape(text)
    formatted = re.sub(r"`([^`]+)`", r"<code>\1</code>", formatted)
    formatted = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", formatted)
    return CITATION_RE.sub(r'<span class="rf-citation">[\1]</span>', formatted)


def _clean_section_content(content: str, title: str) -> str:
    lines = content.strip().splitlines()
    if not lines:
        return ""
    first_heading = re.match(r"^#{1,6}\s+(.+)$", lines[0].strip())
    if first_heading and _normalize_heading(first_heading.group(1)) == _normalize_heading(title):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _source_link(url: str) -> str:
    if not _is_safe_http_url(url):
        return ""
    origin = escape(_source_origin(url))
    safe_url = escape(url, quote=True)
    return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{origin}</a>'


def _source_origin(url: str) -> str:
    if not url:
        return "Uploaded evidence"
    parsed = urlparse(url)
    return parsed.netloc or "Uploaded evidence"


def _is_safe_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _score_label(value: object) -> str:
    score = max(0.0, min(_as_float(value), 1.0))
    return f"Score {score:.0%}"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}..."


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
    st.markdown('<div class="rf-section-heading">Exports</div>', unsafe_allow_html=True)
    if status != "completed":
        st.markdown(
            '<div class="rf-export-panel">'
            '<p class="rf-export-title">Not ready yet</p>'
            '<p class="rf-export-copy">Exports unlock after the report is completed or approved.</p>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="rf-export-panel">'
        '<p class="rf-export-title">Download report</p>'
        '<p class="rf-export-copy">Prepare the format you need, then download the generated file.</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    for export_format, (label, mime_type, extension) in EXPORTS.items():
        export_key = (job_id, export_format)
        if st.button(
            f"Prepare {label}",
            key=f"prepare_{job_id}_{export_format}",
            use_container_width=True,
        ):
            try:
                st.session_state.exports[export_key] = api_bytes(
                    backend_url,
                    f"/jobs/{job_id}/export/{export_format}",
                )
            except ApiClientError as exc:
                st.error(str(exc))

        data = st.session_state.exports.get(export_key)
        if data:
            st.download_button(
                f"Download {label}",
                data=data,
                file_name=f"{job_id}.{extension}",
                mime=mime_type,
                key=f"download_{job_id}_{export_format}",
                use_container_width=True,
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


def _quota_remaining(value: object) -> str:
    remaining = _as_int(value)
    if remaining < 0:
        return "Not capped"
    return str(remaining)


def _extension(format_name: Literal["markdown", "pdf", "docx"]) -> str:
    """Return a file extension for an export format."""
    return "md" if format_name == "markdown" else format_name


if __name__ == "__main__":
    main()
