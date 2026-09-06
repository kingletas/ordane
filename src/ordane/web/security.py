"""Refuses any request that did not come from this console's own page.

There is no login, and that is deliberate: anything that can reach the port
can already run `make` as this user. What must not happen is a page on the
open internet reaching it, so every state-changing request is checked against
the origin it claims and the host it was addressed to. Unknown means refused.
"""

from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def host_is_loopback(host_header: str, expected_port: int) -> bool:
    """True when the Host header names loopback on the port this console serves."""
    if not host_header:
        return False
    host, _, port = host_header.rpartition(":")
    if not host:
        host, port = host_header, ""
    if host.lower() not in LOOPBACK_HOSTS:
        return False
    if port and port != str(expected_port):
        return False
    return True


def origin_is_allowed(origin: str, expected_port: int) -> bool:
    """True when the Origin header is this console's own loopback origin."""
    if not origin or origin == "null":
        return False
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https"):
        return False
    if parts.hostname is None or parts.hostname.lower() not in LOOPBACK_HOSTS:
        return False
    return (parts.port or (443 if parts.scheme == "https" else 80)) == expected_port


def check(method: str, headers, expected_port: int) -> str:
    """Returns an empty string when the request may proceed, or the refusal reason."""
    host = headers.get("host", "")
    if not host_is_loopback(host, expected_port):
        return f"Host header {host!r} is not this console's loopback address"

    if method.upper() in SAFE_METHODS:
        return ""

    origin = headers.get("origin", "")
    if origin:
        if not origin_is_allowed(origin, expected_port):
            return f"Origin {origin!r} is not permitted"
        return ""

    # No Origin on a write is only acceptable from a same-origin form post,
    # which browsers still label with Sec-Fetch-Site.
    site = headers.get("sec-fetch-site", "")
    if site and site != "same-origin":
        return f"Sec-Fetch-Site {site!r} is not same-origin"
    if not site:
        return "a state-changing request must carry an Origin header"
    return ""
