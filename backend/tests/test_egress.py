"""Tests for egress allowlist derivation."""
from __future__ import annotations

from app.config import BackendConfig, Settings
from app.services.egress import derive_egress_allowlist, render_allowlist


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_defaults_cover_github_and_anthropic() -> None:
    """Ensure the default config allowlists GitHub, codeload, and Anthropic."""
    hosts = derive_egress_allowlist(_settings())
    assert "github.com" in hosts
    assert "api.github.com" in hosts
    assert "codeload.github.com" in hosts  # github.com implies codeload
    assert "api.anthropic.com" in hosts


def test_backend_base_urls_are_included() -> None:
    """Ensure each configured backend's host joins the allowlist."""
    settings = _settings(
        backends=[
            BackendConfig(id="oc", type="opencode",
                          base_url="http://host.docker.internal:4096"),
            BackendConfig(id="llm", type="openai_compat",
                          base_url="https://llm.internal:8443/v1"),
        ]
    )
    hosts = derive_egress_allowlist(settings)
    assert "host.docker.internal" in hosts
    assert "llm.internal" in hosts


def test_operator_extra_hosts_and_ports_stripped() -> None:
    """Ensure operator extras are included and ports are dropped."""
    settings = _settings(egress_allowlist=["mcp.example.com", "Extra.Host"])
    hosts = derive_egress_allowlist(settings)
    assert "mcp.example.com" in hosts
    assert "extra.host" in hosts  # lowercased


def test_non_github_git_base_omits_codeload() -> None:
    """Ensure a GitHub Enterprise git_base does not pull in codeload."""
    settings = _settings(git_base="https://ghe.corp.example")
    hosts = derive_egress_allowlist(settings)
    assert "ghe.corp.example" in hosts
    assert "codeload.github.com" not in hosts


def test_render_is_sorted_and_newline_terminated() -> None:
    """Ensure the rendered ACL is deterministic (sorted, one host per line)."""
    text = render_allowlist(_settings())
    lines = text.splitlines()
    assert lines == sorted(lines)
    assert text.endswith("\n")
    assert "api.anthropic.com" in lines
