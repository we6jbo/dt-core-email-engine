# web_worker.py
import textwrap
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests  # you may need: sudo apt-get install python3-requests

DB = Path("/var/lib/dt-core-database/")
MAX_BYTES = 100_000   # hard cap on body size
MAX_SNIPPET = 2000    # how much text to return per site


def _normalize_domain(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    # Accept plain domains like "ssa.gov" or full URLs
    if "://" in raw:
        host = urlparse(raw).hostname or ""
        return host.lower()
    return raw.lower()


def _url_for_domain(domain: str, query: str | None = None) -> str:
    """
    Very simple rule for now:
    - If query is provided, we just hit the root page and let the human read.
    Later you could plug in a proper site search or DuckDuckGo URL.
    """
    # Force https
    return f"https://{domain}/"


def _extract_text(html: str) -> str:
    """
    Super simple HTML stripper. Later you can use BeautifulSoup.
    """
    out = []
    inside = False
    for ch in html:
        if ch == "<":
            inside = True
        elif ch == ">":
            inside = False
        elif not inside:
            out.append(ch)
    return "".join(out)


def fetch_from_sites(
    allowed_sites: Iterable[str],
    requested_sites: Iterable[str],
    query: str | None = None,
) -> str:
    """
    Fetch from requested_sites ∩ allowed_sites and return a plain-text summary.
    """
    allowed_norm = {_normalize_domain(s) for s in allowed_sites}
    req_norm = [_normalize_domain(s) for s in requested_sites]

    lines: list[str] = []
    for dom in req_norm:
        if not dom:
            continue
        if dom not in allowed_norm:
            lines.append(f"[SKIP] {dom} is not in allowed sites.")
            continue

        url = _url_for_domain(dom, query=query)
        try:
            resp = requests.get(url, timeout=10, stream=True)
            content = resp.raw.read(MAX_BYTES, decode_content=True)
            if isinstance(content, bytes):
                content = content.decode(resp.encoding or "utf-8", errors="replace")

            text = _extract_text(str(content))
            snippet = text.strip().replace("\r", " ").replace("\n", " ")
            snippet = " ".join(snippet.split())  # collapse whitespace
            if len(snippet) > MAX_SNIPPET:
                snippet = snippet[:MAX_SNIPPET] + "..."
            lines.append(f"[{dom}] {snippet}")
        except Exception as e:
            lines.append(f"[ERROR] {dom}: {e!r}")

    if not lines:
        return "No internet results (no requested sites matched the allow list)."

    return "\n\n".join(textwrap.wrap("\n\n".join(lines), width=78))

