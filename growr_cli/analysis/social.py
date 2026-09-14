"""Normalize reported links and score observable social presence."""

import re
from ipaddress import IPv6Address
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

PLATFORM_HOSTS = {
    "x.com": "twitter",
    "twitter.com": "twitter",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "discord.gg": "discord",
    "discord.com": "discord",
    "reddit.com": "reddit",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "tiktok.com": "tiktok",
    "linkedin.com": "linkedin",
    "github.com": "github",
}
PROVIDER_HOSTS = {"stonkfun.xyz"}


def _matches_host(host, domain) -> bool:
    return host == domain or host.endswith(".%s" % domain)


def _ascii_host(host) -> str:
    """Normalize DNS names and retain required IPv6 brackets."""

    if ":" in host:
        return "[%s]" % IPv6Address(host)
    host = host.encode("idna").decode("ascii").lower().rstrip(".")
    labels = host.split(".")
    if len(host) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("Invalid URL host")
    return host.removeprefix("www.")


def _parse_link(value) -> tuple[Any, str, int | None] | None:
    """Reject malformed URLs before they can earn social points."""

    if not isinstance(value, str) or any(not c.isprintable() for c in value):
        return None
    value = value.strip()
    if any(c.isspace() for c in value) or re.search(
        r"%(?![0-9a-fA-F]{2})", value
    ):
        return None
    try:
        parts = urlsplit(value)
        host = _ascii_host(parts.hostname or "")
        port = parts.port
    except (ValueError, UnicodeError):
        return None
    if (
        parts.scheme not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
        or port == 0
        or any(_matches_host(host, domain) for domain in PROVIDER_HOSTS)
    ):
        return None
    return parts, host, port


def normalize_link(candidate) -> dict[str, Any] | None:
    """Validate explicit links without contacting their destinations."""

    parsed = _parse_link(candidate.get("url"))
    if parsed is None:
        return None
    parts, host, port = parsed
    platform = next(
        (
            name
            for domain, name in PLATFORM_HOSTS.items()
            if _matches_host(host, domain)
        ),
        None,
    )
    if platform is None and candidate.get("kind") != "website":
        return None
    path = parts.path.rstrip("/")
    # A social platform homepage is not a project account or community.
    if platform and not path:
        return None
    scheme = parts.scheme
    if platform == "twitter":
        host = "x.com"
        path = path.lower()
        scheme = "https"
    if port is not None and (parts.scheme, port) not in {
        ("http", 80),
        ("https", 443),
    }:
        host = "%s:%s" % (host, port)
    # Encode Unicode and unsafe URI characters without changing valid
    # escapes or the meaning of query separators.
    path = quote(path, safe="/:@!$&'()*+,;=-._~%")
    query = quote(parts.query, safe="/?:@!$&'()*+,;=-._~%")
    return {
        "kind": "social" if platform else "website",
        "platform": platform,
        "url": urlunsplit((scheme, host, path, query, "")),
        "sources": [candidate["source"]],
    }


def social_presence(candidates, coverage) -> dict[str, Any]:
    """Award presence points once per category, retaining provenance."""

    links = {}
    for candidate in candidates:
        link = normalize_link(candidate)
        if link is None:
            continue
        if link["url"] not in links:
            links[link["url"]] = link
        sources = links[link["url"]]["sources"]
        if candidate["source"] not in sources:
            sources.append(candidate["source"])
    values = list(links.values())
    platforms = sorted(
        {link["platform"] for link in values if link["platform"]}
    )
    has_website = any(link["kind"] == "website" for link in values)
    score = (40 if has_website else 0) + (40 if platforms else 0)
    score += 20 if len(platforms) > 1 else 0
    return {
        "score": score,
        "max_score": 100,
        "has_website": has_website,
        "platforms": platforms,
        "links": values,
        "coverage": coverage,
    }
