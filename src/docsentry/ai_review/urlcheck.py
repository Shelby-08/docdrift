"""Loopback-only validation for the Ollama base URL."""

import ipaddress
from urllib.parse import urlsplit


class UnsafeOllamaUrl(ValueError):
    pass


def validate_ollama_base_url(url: str) -> str:
    """Return the normalized base URL (no trailing slash) or raise UnsafeOllamaUrl."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UnsafeOllamaUrl("invalid_url") from exc
    if parts.scheme != "http" or host is None:
        raise UnsafeOllamaUrl("scheme_or_host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeOllamaUrl("userinfo")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise UnsafeOllamaUrl("query_or_fragment")
    if parts.path not in ("", "/"):
        raise UnsafeOllamaUrl("path")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise UnsafeOllamaUrl("dns_name") from exc
    if str(ip) not in ("127.0.0.1", "::1"):
        raise UnsafeOllamaUrl("not_loopback")
    shown = f"[{ip}]" if ip.version == 6 else str(ip)
    return f"http://{shown}:{port if port is not None else 11434}"
