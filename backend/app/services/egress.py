"""Egress allowlist derivation for the default-deny network design.

Kestrel runs an agent over untrusted issue text, so unrestricted outbound
network access is an exfiltration and SSRF risk. The deployment routes all
egress through a forward-proxy that permits only a known set of hosts; this
module derives that host set from the configuration kestrel already holds
(GitHub, Anthropic, and the configured backends) so the allowlist cannot
drift out of sync with what the app legitimately needs.

The derived list is rendered to a proxy ACL file (``python -m
app.services.egress <path>``) that an init step feeds to the proxy sidecar.
See ``docs/security.md``.
"""
from __future__ import annotations

import sys
from urllib.parse import urlparse

from app.config import Settings, get_settings

#: GitHub serves git clone/archive data from codeload.github.com in addition
#: to github.com, so a github.com git_base implies this host too.
_GITHUB_CODELOAD = "codeload.github.com"
_GITHUB_HOSTS = {"github.com", "www.github.com"}


def _host(url: str | None) -> str | None:
    """Return the lowercased hostname of a URL, or None if it has none."""
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower() if host else None


def derive_egress_allowlist(settings: Settings) -> set[str]:
    """Compute the set of hostnames egress must permit.

    Sourced entirely from existing configuration so the allowlist tracks
    what kestrel actually needs:

    - the git and GitHub-API hosts (plus codeload for github.com),
    - the Anthropic API host (the bundled ``claude`` CLI),
    - every configured backend's ``base_url`` host, and
    - any extra hosts an operator lists in ``egress_allowlist``.

    :param settings: The application settings.
    :returns: The set of allowed hostnames (no ports, lowercased).
    """
    hosts: set[str] = set()
    for url in (
        settings.git_base,
        settings.github_api_base,
        settings.anthropic_api_base,
    ):
        host = _host(url)
        if host:
            hosts.add(host)
    if _host(settings.git_base) in _GITHUB_HOSTS:
        hosts.add(_GITHUB_CODELOAD)
    for cfg in settings.backends:
        host = _host(cfg.base_url)
        if host:
            hosts.add(host)
    hosts.update(h.lower() for h in settings.egress_allowlist if h)
    return hosts


def render_allowlist(settings: Settings) -> str:
    """Render the allowlist as a newline-separated, sorted host list.

    Suitable as a squid ``dstdomain`` ACL file or any proxy allowlist that
    reads one host per line. Deterministic (sorted) so regenerating it
    produces a stable diff.
    """
    return "\n".join(sorted(derive_egress_allowlist(settings))) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the rendered allowlist to a file (or stdout with ``-``).

    Usage: ``python -m app.services.egress <path|->``.
    """
    args = sys.argv[1:] if argv is None else argv
    target = args[0] if args else "-"
    content = render_allowlist(get_settings())
    if target == "-":
        sys.stdout.write(content)
    else:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(content)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
