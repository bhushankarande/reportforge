"""Streamlit frontend for ReportForge."""

import json
import os
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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
DEPTHS = {"Brief (2-3 pages)": "brief", "Standard (5-8 pages)": "standard", "Deep (10-15 pages)": "deep"}
PROVIDERS = {
    "Gemini Flash": "gemini",
    "Groq": "groq",
    "Ollama": "ollama",
}


def api_json(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    """Call the FastAPI backend and return a JSON object."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def api_bytes(path: str) -> bytes:
    """Download a binary export from the backend."""
    with urlopen(f"{API_BASE_URL}{path}", timeout=20) as response:
        return response.read()


def safe_api_json(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    """Call the API and convert HTTP errors into user-visible payloads."""
    try:
        return api_json(method, path, payload)
    except HTTPError as exc:
        return {"error": f"{exc.code}: {exc.read().decode('utf-8')}"}
    except URLError as exc:
        return {"error": f"Backend unavailable: {exc.reason}"}


def submit_job(topic: str, report_type: str, depth: str, urls: list[str]) -> tuple[str | None, str | None]:
    """Submit a report job and return its id or an error message."""
    payload = {"topic": topic, "type": report_type, "depth": depth, "urls": urls}
    response = safe_api_json("POST", "/jobs", payload)
    if "error" in response:
        return None, str(response["error"])
    return str(response["job_id"]), None


def poll_job(job_id: str) -> dict[str, object]:
    """Fetch current job progress."""
    return safe_api_json("GET", f"/jobs/{job_id}/progress")


def main() -> None:
    """Run the Streamlit app."""
    try:
        import streamlit as st
    except ImportError:
        print("Streamlit is not installed. Run `uv sync` first.")
        return

    st.set_page_config(page_title="ReportForge", layout="wide")
    st.title("ReportForge")

    if "jobs" not in st.session_state:
        st.session_state.jobs = []

    with st.sidebar:
        report_type_label = st.selectbox("Report type", list(REPORT_TYPES))
        depth_label = st.selectbox("Depth", list(DEPTHS), index=1)
        provider_label = st.selectbox("LLM provider", list(PROVIDERS))
        if provider_label == "Gemini Flash":
            st.caption("Free-tier guardrail: 1,500 requests/day.")
        elif provider_label == "Groq":
            st.caption("Debug fallback guardrail: 1M tokens/day.")
        else:
            st.caption("Local fallback; quota is not enforced.")
        st.file_uploader(
            "Upload documents",
            type=["pdf", "docx", "csv", "xlsx"],
            accept_multiple_files=True,
        )
        url_text = st.text_area("URLs", placeholder="https://example.com/report\nhttps://example.com/source")
        quota = safe_api_json("GET", "/costs/quota")
        if "error" not in quota:
            st.metric("Gemini requests left", quota.get("gemini_requests_remaining", 0))
            st.metric("Groq tokens left", quota.get("groq_tokens_remaining", 0))

    topic = st.text_input("Research topic", placeholder="AI-powered report automation market")
    urls = [line.strip() for line in url_text.splitlines() if line.strip()]
    cost_preview = "Actual test cost: $0.00. Kimi estimate is tracked after generation."
    st.caption(cost_preview)

    if st.button("Generate report", disabled=len(topic.strip()) < 3):
        job_id, error = submit_job(topic, REPORT_TYPES[report_type_label], DEPTHS[depth_label], urls)
        if job_id:
            st.session_state.jobs.insert(0, job_id)
            st.success(f"Submitted job {job_id}")
        else:
            st.error(f"Unable to submit job. {error or 'Unknown backend error.'}")

    if not st.session_state.jobs:
        st.info("Submit a topic to start a report.")
        return

    selected_job = st.selectbox("Active job", st.session_state.jobs)
    progress = poll_job(selected_job)
    if "error" in progress:
        st.error(str(progress["error"]))
        return

    render_progress(st, progress)
    if progress.get("status") == "awaiting_approval":
        st.warning("Human approval is required before final export.")
        if st.button("Approve report"):
            safe_api_json("POST", f"/jobs/{selected_job}/approve")
            st.rerun()

    if progress.get("status") in {"running", "pending"}:
        time.sleep(2)
        st.rerun()

    render_sources(st, selected_job)
    render_report(st, selected_job)
    render_exports(st, selected_job)
    render_section_editor(st, selected_job)


def render_progress(st: object, progress: dict[str, object]) -> None:
    """Render progress, active agent, and cost metrics."""
    columns = st.columns(4)
    columns[0].metric("Status", str(progress.get("status", "unknown")))
    columns[1].metric("Agent", str(progress.get("active_agent") or "idle"))
    columns[2].metric("Step", str(progress.get("current_step", "queued")))
    cost = progress.get("cost", {})
    kimi_cost = cost.get("estimated_kimi_cost_usd", "0.00") if isinstance(cost, dict) else "0.00"
    columns[3].metric("Cost", f"$0.00 / Kimi ${kimi_cost}")
    st.progress(float(progress.get("percent_complete", 0.0)) / 100.0)


def render_sources(st: object, job_id: str) -> None:
    """Render report sources."""
    sources = safe_api_json("GET", f"/jobs/{job_id}/sources")
    st.subheader("Sources")
    if "error" in sources:
        st.warning(str(sources["error"]))
        return
    for source in sources if isinstance(sources, list) else []:
        title = source.get("title", "Untitled source")
        score = source.get("relevance_score", 0)
        with st.expander(f"{title} ({score})"):
            st.write(source.get("summary", ""))
            st.code(source.get("citation_key", ""))


def render_report(st: object, job_id: str) -> None:
    """Render Markdown preview with simple claim highlighting."""
    st.subheader("Report")
    try:
        markdown = api_bytes(f"/jobs/{job_id}/export/markdown").decode("utf-8")
    except (HTTPError, URLError) as exc:
        st.warning(f"Report preview unavailable: {exc}")
        return
    highlighted = markdown.replace("[SourceID]", "**[SourceID]**")
    st.markdown(highlighted)


def render_exports(st: object, job_id: str) -> None:
    """Render export download buttons."""
    st.subheader("Exports")
    for fmt, mime in [
        ("markdown", "text/markdown"),
        ("pdf", "application/pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]:
        try:
            data = api_bytes(f"/jobs/{job_id}/export/{fmt}")
        except (HTTPError, URLError):
            continue
        st.download_button(
            fmt.upper(),
            data=data,
            file_name=f"{job_id}.{_extension(fmt)}",
            mime=mime,
        )


def render_section_editor(st: object, job_id: str) -> None:
    """Render section regeneration controls."""
    st.subheader("Section editor")
    sections = safe_api_json("GET", f"/jobs/{job_id}/sections")
    if not isinstance(sections, list) or not sections:
        st.caption("No sections available yet.")
        return
    labels = {f"{section['order'] + 1}. {section['title']}": section["id"] for section in sections}
    label = st.selectbox("Section", list(labels))
    feedback = st.text_area("Regeneration feedback")
    if st.button("Regenerate section"):
        query = urlencode({"section_id": labels[label], "feedback": feedback})
        response = safe_api_json("POST", f"/jobs/{job_id}/regenerate-section?{query}")
        if "error" in response:
            st.error(str(response["error"]))
        else:
            st.success("Section regenerated.")
            st.rerun()


def _extension(format_name: Literal["markdown", "pdf", "docx"]) -> str:
    """Return a file extension for an export format."""
    return "md" if format_name == "markdown" else format_name


if __name__ == "__main__":
    main()
