"""
Safe URL fetcher for research sources.

Handles URL normalization, SSRF protection, redirect checks, bounded downloads,
HTML extraction, PDF extraction, and text/plain extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import ipaddress
import re
import socket
from typing import Final
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


class URLFetchError(RuntimeError):
    """Raised when a URL cannot be safely fetched or parsed."""


@dataclass(frozen=True)
class FetchedURL:
    """Parsed result from a fetched URL."""

    url: str
    final_url: str
    title: str
    text: str
    content_type: str


@dataclass(frozen=True)
class FetchConfig:
    """Configuration for safe URL fetching."""

    timeout_seconds: float = 15.0
    max_bytes: int = 5_000_000
    max_redirects: int = 5
    max_pdf_pages: int = 30
    user_agent: str = (
        "ReportForgeResearchAgent/1.0 (safe URL fetcher; contact: local-development)"
    )


BLOCKED_HOSTNAMES: Final[set[str]] = {
    "localhost",
    "localhost.localdomain",
}

HTML_CONTENT_TYPES: Final[set[str]] = {
    "text/html",
    "application/xhtml+xml",
}

TEXT_CONTENT_TYPES: Final[set[str]] = {
    "text/plain",
    "text/markdown",
}

PDF_CONTENT_TYPES: Final[set[str]] = {
    "application/pdf",
}


def fetch_url_text(url: str, config: FetchConfig | None = None) -> tuple[str, str]:
    """
    Fetch a public URL and return its title plus extracted text.

    This wrapper is kept for the existing ResearchAgent call site.
    """
    result = fetch_url(url=url, config=config)
    return result.title, result.text


def fetch_url(url: str, config: FetchConfig | None = None) -> FetchedURL:
    """Fetch and extract readable text from a public URL."""
    config = config or FetchConfig()
    original_url = normalize_url(url)

    with requests.Session() as session:
        response, final_url = _safe_get_with_redirects(
            session=session,
            url=original_url,
            config=config,
        )
        content_type = _clean_content_type(response.headers.get("content-type", ""))
        raw_bytes = _read_limited_response(response, max_bytes=config.max_bytes)

    if content_type in HTML_CONTENT_TYPES or _looks_like_html(raw_bytes):
        title, text = _extract_html(raw_bytes, fallback_title=final_url)
    elif content_type in PDF_CONTENT_TYPES or final_url.lower().endswith(".pdf"):
        title, text = _extract_pdf(
            raw_bytes,
            fallback_title=final_url,
            max_pages=config.max_pdf_pages,
        )
    elif content_type in TEXT_CONTENT_TYPES:
        title = _title_from_url(final_url)
        text = _decode_bytes(raw_bytes)
    else:
        raise URLFetchError(f"Unsupported content type: {content_type or 'unknown'} for {final_url}")

    text = _normalize_text(text)

    if len(text) < 500:
        raise URLFetchError(
            f"Extracted text too short from {final_url}. Only {len(text)} characters found."
        )

    if _looks_like_blocked_page(text):
        raise URLFetchError(f"Fetched page appears blocked, paywalled, or JavaScript-only: {final_url}")

    return FetchedURL(
        url=original_url,
        final_url=final_url,
        title=title.strip() or _title_from_url(final_url),
        text=text,
        content_type=content_type,
    )


def normalize_url(url: str) -> str:
    """Normalize and validate a URL string."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise URLFetchError(f"Only http/https URLs are allowed: {url}")

    if not parsed.hostname:
        raise URLFetchError(f"URL is missing a hostname: {url}")

    if parsed.hostname.lower() in BLOCKED_HOSTNAMES:
        raise URLFetchError(f"Blocked hostname: {parsed.hostname}")

    _assert_public_hostname(parsed.hostname)

    path = parsed.path or "/"

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def _assert_public_hostname(hostname: str) -> None:
    """Block private, loopback, link-local, multicast, reserved, and unspecified IPs."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise URLFetchError(f"Could not resolve hostname: {hostname}") from exc

    resolved_ips: set[str] = {item[4][0] for item in addr_infos}

    if not resolved_ips:
        raise URLFetchError(f"No IPs resolved for hostname: {hostname}")

    for ip_text in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise URLFetchError(f"Invalid resolved IP for {hostname}: {ip_text}") from exc

        if not ip.is_global:
            raise URLFetchError(f"Blocked non-public IP for {hostname}: {ip_text}")


def _safe_get_with_redirects(
    session: requests.Session,
    url: str,
    config: FetchConfig,
) -> tuple[requests.Response, str]:
    """Perform GET manually so every redirect target is safety-checked."""
    current_url = normalize_url(url)
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
    }

    for _ in range(config.max_redirects + 1):
        response = session.get(
            current_url,
            headers=headers,
            timeout=config.timeout_seconds,
            allow_redirects=False,
            stream=True,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            if not location:
                raise URLFetchError(f"Redirect without Location header: {current_url}")

            next_url = urljoin(current_url, location)
            current_url = normalize_url(next_url)
            continue

        if response.status_code >= 400:
            raise URLFetchError(f"HTTP {response.status_code} while fetching {current_url}")

        return response, current_url

    raise URLFetchError(f"Too many redirects while fetching {url}")


def _read_limited_response(response: requests.Response, max_bytes: int) -> bytes:
    """Read response body while enforcing a maximum byte limit."""
    chunks: list[bytes] = []
    total = 0

    for chunk in response.iter_content(chunk_size=64_000):
        if not chunk:
            continue

        total += len(chunk)
        if total > max_bytes:
            raise URLFetchError(f"Response exceeded maximum allowed size of {max_bytes} bytes")

        chunks.append(chunk)

    return b"".join(chunks)


def _clean_content_type(value: str) -> str:
    """Return content type without charset."""
    return value.split(";", 1)[0].strip().lower()


def _looks_like_html(raw_bytes: bytes) -> bool:
    """Best-effort HTML sniffing."""
    sample = raw_bytes[:500].lower()
    return b"<html" in sample or b"<!doctype html" in sample or b"<body" in sample


def _extract_html(raw_bytes: bytes, fallback_title: str) -> tuple[str, str]:
    """Extract main readable text from HTML."""
    html = _decode_bytes(raw_bytes)
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "form",
            "iframe",
            "canvas",
            "button",
            "nav",
            "footer",
            "header",
            "aside",
        ]
    ):
        tag.decompose()

    title = _extract_html_title(soup) or _title_from_url(fallback_title)
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )

    blocks: list[str] = []
    for element in main.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        text = _normalize_inline_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"} or len(text) >= 40:
            blocks.append(text)

    text = "\n".join(_dedupe_preserve_order(blocks))
    if len(text) < 500:
        text = main.get_text("\n", strip=True)

    return title, text


def _extract_html_title(soup: BeautifulSoup) -> str:
    """Extract best available HTML title."""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return str(og_title["content"]).strip()

    twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
    if twitter_title and twitter_title.get("content"):
        return str(twitter_title["content"]).strip()

    if soup.title and soup.title.string:
        return soup.title.string.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)

    return ""


def _extract_pdf(raw_bytes: bytes, fallback_title: str, max_pages: int) -> tuple[str, str]:
    """Extract text from a PDF."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise URLFetchError("PDF URL detected, but pypdf is not installed. Run: pip install pypdf") from exc

    try:
        reader = PdfReader(BytesIO(raw_bytes))
    except Exception as exc:
        raise URLFetchError("Could not parse PDF bytes") from exc

    pages: list[str] = []
    for page_index, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""

        page_text = _normalize_text(page_text)
        if page_text:
            pages.append(f"[Page {page_index}]\n{page_text}")

    title = ""
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title).strip()

    if not title:
        title = _title_from_url(fallback_title)

    return title, "\n\n".join(pages)


def _decode_bytes(raw_bytes: bytes) -> str:
    """Decode bytes robustly."""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    """Normalize whitespace while preserving paragraph breaks."""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_inline_text(text: str) -> str:
    """Normalize a single text block."""
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    """Remove duplicate text blocks while preserving order."""
    seen: set[str] = set()
    output: list[str] = []

    for item in items:
        key = item.lower()
        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def _title_from_url(url: str) -> str:
    """Create a readable fallback title from URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")[-1]
    raw = path or parsed.hostname or "Untitled source"
    raw = re.sub(r"[-_]+", " ", raw)
    raw = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", raw)
    return raw.strip().title() or "Untitled source"


def _looks_like_blocked_page(text: str) -> bool:
    """Detect common bad extraction cases."""
    lower = text.lower()
    blocked_markers = [
        "enable javascript",
        "access denied",
        "checking your browser",
        "verify you are human",
        "captcha",
        "cloudflare",
        "subscribe to continue",
        "sign in to continue",
        "403 forbidden",
        "request blocked",
    ]

    return any(marker in lower for marker in blocked_markers)
