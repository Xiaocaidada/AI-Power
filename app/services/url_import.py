"""SSRF-safe URL document import with redirects, crawling and size limits."""

import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.config import Settings, get_settings
from app.services.outbound import OutboundError, validate_outbound_url

ALLOWED_CONTENT_TYPES = {
    "text/html": "text/html",
    "application/xhtml+xml": "text/html",
    "text/plain": "text/plain",
    "text/markdown": "text/markdown",
}
_EXTENSION_BY_MIME = {
    "text/html": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
_EXTENSION_MIME = {
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UrlImportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class FetchedUrl:
    content: bytes
    text: str
    mime: str
    filename: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    pages: list[FetchedUrl]
    failures: list[tuple[str, str]]


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and isinstance(value, str) and value.strip():
                self.links.append(value.strip())


def extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkExtractor()
    parser.feed(html)
    parser.close()
    links: list[str] = []
    seen: set[str] = set()
    for raw in parser.links:
        if raw.startswith(("#", "mailto:", "javascript:", "data:")):
            continue
        absolute = urljoin(base_url, raw).split("#", 1)[0]
        parsed = urlsplit(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def _safe_filename(url: str, mime: str) -> str:
    parsed = urlsplit(url)
    basename = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
    stem = _UNSAFE_NAME.sub("_", basename).strip("._")[:160]
    if not stem:
        stem = "index"
    suffix = _EXTENSION_BY_MIME[mime]
    current = stem.lower()
    if not current.endswith(suffix):
        stem = f"{stem}{suffix}"
    host = _UNSAFE_NAME.sub("_", parsed.hostname or "page").strip("._")[:80]
    return f"{host}-{stem}" if stem else host


def _content_type_mime(raw: str, url: str) -> str:
    declared = raw.split(";", 1)[0].strip().lower()
    if declared in ALLOWED_CONTENT_TYPES:
        return ALLOWED_CONTENT_TYPES[declared]
    suffix = ""
    path = urlsplit(url).path.lower()
    for candidate in _EXTENSION_MIME:
        if path.endswith(candidate):
            suffix = candidate
            break
    if declared in {"", "application/octet-stream"} and suffix:
        return _EXTENSION_MIME[suffix]
    raise UrlImportError(
        "unsupported_content_type",
        f"URL content type is not supported: {declared or 'unknown'}",
    )


def _fetch_client(current: Settings, transport: httpx.AsyncBaseTransport | None):
    return httpx.AsyncClient(
        timeout=current.url_import_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )


async def fetch_url_document(
    url: str,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchedUrl:
    current = settings or get_settings()
    if not current.url_import_enabled:
        raise UrlImportError("url_import_disabled", "URL import is disabled")
    scoped = current.model_copy(
        update={
            "http_node_allowed_hosts": current.url_import_allowed_hosts,
            "http_node_allow_private_hosts": current.url_import_allow_private_hosts,
        }
    )
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise UrlImportError("invalid_url", "URL must not contain credentials")

    headers = {
        "Accept": "text/html, application/xhtml+xml, text/plain, text/markdown, */*;q=0.1",
        "User-Agent": "AI-Power-URL-Importer/1.0",
    }
    current_url = url
    redirects = 0
    try:
        async with _fetch_client(current, transport) as client:
            while True:
                try:
                    await validate_outbound_url(current_url, scoped)
                except OutboundError as exc:
                    raise UrlImportError(exc.code, exc.message) from None
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise UrlImportError(
                                "http_status",
                                f"URL redirected without a Location header "
                                f"(HTTP {response.status_code})",
                            )
                        if redirects >= current.url_import_max_redirects:
                            raise UrlImportError(
                                "too_many_redirects",
                                "URL exceeded the redirect limit",
                            )
                        current_url = urljoin(current_url, location)
                        redirects += 1
                        continue
                    if response.status_code >= 300:
                        raise UrlImportError(
                            "http_status",
                            f"URL returned HTTP {response.status_code}",
                        )
                    mime = _content_type_mime(
                        response.headers.get("content-type", ""), current_url
                    )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > current.url_import_max_bytes:
                            raise UrlImportError(
                                "url_too_large",
                                f"URL content exceeds "
                                f"{current.url_import_max_bytes} bytes",
                            )
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    break
    except UrlImportError:
        raise
    except httpx.TimeoutException:
        raise UrlImportError("http_timeout", "URL request timed out") from None
    except httpx.HTTPError as exc:
        raise UrlImportError(
            "http_unreachable", f"URL unreachable: {type(exc).__name__}"
        ) from None

    if not content:
        raise UrlImportError("empty_url", "URL returned an empty body")
    return FetchedUrl(
        content=content,
        text=content.decode(encoding, errors="replace"),
        mime=mime,
        filename=_safe_filename(current_url, mime),
        url=current_url,
    )


async def crawl_site(
    start_url: str,
    *,
    max_pages: int,
    same_origin: bool = True,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CrawlOutcome:
    current = settings or get_settings()
    limit = max(1, min(max_pages, current.url_import_crawl_max_pages))
    origin = urlsplit(start_url).netloc.lower()
    queue: list[str] = [start_url]
    seen: set[str] = set()
    pages: list[FetchedUrl] = []
    failures: list[tuple[str, str]] = []
    while queue and len(pages) < limit:
        page_url = queue.pop(0)
        if page_url in seen:
            continue
        seen.add(page_url)
        try:
            page = await fetch_url_document(
                page_url, settings=current, transport=transport
            )
        except UrlImportError as exc:
            failures.append((page_url, exc.code))
            continue
        page = replace(page, url=page.url or page_url)
        pages.append(page)
        if page.mime != "text/html":
            continue
        for link in extract_links(page.text, page.url or page_url):
            if same_origin and urlsplit(link).netloc.lower() != origin:
                continue
            if link not in seen and link not in queue:
                queue.append(link)
    return CrawlOutcome(pages=pages, failures=failures)