"""Message / CTA-link validation rules, kept framework-agnostic so they can be
unit-tested and reused outside the HTTP layer."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_MESSAGE_LENGTH = 200
MAX_URL_LENGTH = 2048

# Anything that *looks* like a link: explicit scheme, or a bare "www." host.
# Bare-"www." matches are counted so "two links" is detected, then rejected
# by validate_url because they lack a scheme.
LINK_PATTERN = re.compile(r"(?:\b[a-z][a-z0-9+.-]*://|\bwww\.)[^\s<>\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}'\""

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$", re.IGNORECASE)


def extract_links(message: str) -> list[str]:
    """Return every link-like token in ``message`` (trailing punctuation removed)."""
    return [m.group(0).rstrip(TRAILING_PUNCTUATION) for m in LINK_PATTERN.finditer(message)]


def validate_url(url: str) -> None:
    """Raise ``ValueError`` with a human-readable reason if ``url`` is not a
    valid, publicly-routable http(s) CTA link."""
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"CTA link must not exceed {MAX_URL_LENGTH} characters.")

    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on a malformed port
    except ValueError as exc:
        raise ValueError(f"CTA link is not a valid URL: {exc}.") from None

    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("CTA link must start with http:// or https://.")
    if parts.username or parts.password:
        raise ValueError("CTA link must not contain embedded credentials.")
    if port is not None and not 0 < port < 65536:
        raise ValueError("CTA link has an invalid port.")

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise ValueError("CTA link is missing a host name.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not ip.is_global:
            raise ValueError("CTA link must point to a public address.")
        return

    labels = host.split(".")
    if host.lower() == "localhost" or len(labels) < 2:
        raise ValueError("CTA link must use a public domain name (e.g. example.com).")
    if not all(_HOST_LABEL.match(label) for label in labels) or not _TLD.match(labels[-1]):
        raise ValueError(f"CTA link has an invalid domain name: '{host}'.")


def validate_message(message: str) -> str:
    """Apply all business rules; return the normalised (stripped) message."""
    message = message.strip()
    if not message:
        raise ValueError("Message must not be empty.")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(
            f"Message must not exceed {MAX_MESSAGE_LENGTH} characters "
            f"(got {len(message)})."
        )

    links = extract_links(message)
    if not links:
        raise ValueError("Message must include exactly one CTA link; none was found.")
    if len(links) > 1:
        raise ValueError(
            f"Message must include exactly one CTA link; found {len(links)}: {', '.join(links)}."
        )

    validate_url(links[0])
    return message
