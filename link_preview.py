"""
Fetches basic Open Graph / HTML metadata for a URL, so the UI can render a
Notion-style link preview card (title, description, image) for links pasted
into a trade's notes.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; TradingJournalLinkPreview/1.0)"

# Local, in-memory only - a personal single-user tool doesn't need this to
# survive a restart, and it keeps re-pasting the same link from re-fetching it.
_cache = {}


def _is_fetchable(url: str) -> bool:
    """Only follows plain http(s) links to public hosts - guards against a
    pasted note URL being used to probe the machine's own loopback/private
    network (SSRF) via this server-side fetch."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        ip = socket.gethostbyname(parsed.hostname)
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_reserved or addr.is_multicast or addr.is_unspecified)
    except Exception:
        return False


def _meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def fetch_preview(url: str) -> dict:
    """Returns a preview dict for `url`. Never raises - on any failure (bad
    URL, unreachable host, non-HTML response...) falls back to a bare-link
    preview using just the hostname, so the UI always has something to show."""
    if url in _cache:
        return _cache[url]

    parsed = urlparse(url)
    fallback = {
        "url": url, "title": parsed.hostname or url, "description": None,
        "image": None, "site_name": parsed.hostname, "favicon": None,
    }

    if not _is_fetchable(url):
        _cache[url] = fallback
        return fallback

    try:
        resp = httpx.get(url, timeout=6, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("content-type", ""):
            raise ValueError("not html")
        html = resp.text[:1_000_000]
        final_url = str(resp.url)
    except Exception:
        _cache[url] = fallback
        return fallback

    soup = BeautifulSoup(html, "html.parser")
    title = (_meta(soup, "og:title")
             or (soup.title.string.strip() if soup.title and soup.title.string else None)
             or fallback["title"])
    description = _meta(soup, "og:description", "description")
    image = _meta(soup, "og:image")
    site_name = _meta(soup, "og:site_name") or parsed.hostname

    icon_tag = soup.find("link", rel=lambda r: r and "icon" in r.lower())
    favicon = urljoin(final_url, icon_tag["href"]) if icon_tag and icon_tag.get("href") else None
    if image:
        image = urljoin(final_url, image)

    result = {
        "url": url, "title": title, "description": description,
        "image": image, "site_name": site_name, "favicon": favicon,
    }
    _cache[url] = result
    return result
