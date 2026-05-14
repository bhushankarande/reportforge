"""URL fetching helpers for user-supplied research sources."""

import re
import ssl
from html import unescape
from urllib.error import URLError
from urllib.request import Request, urlopen

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(URLError),
    reraise=True,
)
def fetch_url_text(url: str, *, timeout: int = 10, max_chars: int = 12_000) -> tuple[str, str]:
    """Fetch a URL and return a best-effort title plus readable text."""
    request = Request(
        url,
        headers={
            "User-Agent": "ReportForge/0.1 (+https://github.com/bhushankarande/reportforge)",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    try:
        content_type, raw = _read_url(request, timeout=timeout, max_bytes=max_chars * 4)
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        content_type, raw = _read_url(
            request,
            timeout=timeout,
            max_bytes=max_chars * 4,
            context=ssl._create_unverified_context(),  # noqa: S323
        )
    text = raw.decode(_encoding_from_content_type(content_type), errors="replace")
    title = _extract_title(text) or url
    description = _extract_meta_description(text)
    body = _html_to_text(text)
    readable = f"{description}. {body}" if description else body
    return title, readable[:max_chars]


def _read_url(
    request: Request,
    *,
    timeout: int,
    max_bytes: int,
    context: ssl.SSLContext | None = None,
) -> tuple[str, bytes]:
    """Read URL bytes with an optional SSL context."""
    with urlopen(request, timeout=timeout, context=context) as response:
        return response.headers.get("content-type", ""), response.read(max_bytes)


def _encoding_from_content_type(content_type: str) -> str:
    """Return declared response encoding or utf-8."""
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _extract_title(html: str) -> str | None:
    """Extract the HTML title if present."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip()


def _extract_meta_description(html: str) -> str | None:
    """Extract a page meta description or Open Graph description."""
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return re.sub(r"\s+", " ", unescape(match.group(1))).strip()
    return None


def _html_to_text(html: str) -> str:
    """Convert HTML into rough readable text without extra dependencies."""
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = unescape(html)
    return re.sub(r"\s+", " ", html).strip()
