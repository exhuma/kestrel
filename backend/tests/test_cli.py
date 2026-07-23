"""Tests for the CLI entrypoint: serve dispatch and the poll dry-run (004)."""
from __future__ import annotations

import pytest

from app import cli
from app.ports import WorkItem


class _FakePollSource:
    def __init__(self, name, items) -> None:
        self.name = name
        self._items = items

    async def list_work_items(self):
        return self._items


def test_poll_lists_items_from_all_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """Ensure poll prints each source's items and exits 0."""
    sources = [
        _FakePollSource(
            "github [o/r]", [WorkItem("github-issue", "o/r#5", "Fix", "o/r")]
        ),
        _FakePollSource(
            "jira [j]", [WorkItem("jira-issue", "RFC-9", "Cache", None)]
        ),
    ]
    monkeypatch.setattr(cli, "get_settings", object)
    monkeypatch.setattr(cli, "configured_poll_sources", lambda _s: sources)
    assert cli.main(["poll"]) == 0
    out = capsys.readouterr().out
    assert "o/r#5" in out and "Fix" in out and "o/r" in out
    assert "RFC-9" in out and "unresolved repository" in out


def test_poll_with_no_sources_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """Ensure poll reports and exits 0 when nothing is configured."""
    monkeypatch.setattr(cli, "get_settings", object)
    monkeypatch.setattr(cli, "configured_poll_sources", lambda _s: [])
    assert cli.main(["poll"]) == 0
    assert "No task sources configured" in capsys.readouterr().out


def test_serve_is_the_default_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure no subcommand dispatches to serve."""
    called: dict[str, bool] = {}
    monkeypatch.setattr(cli, "get_settings", object)
    monkeypatch.setattr(
        cli, "cmd_serve", lambda _s: called.update(serve=True) or 0
    )
    assert cli.main([]) == 0
    assert called.get("serve") is True
