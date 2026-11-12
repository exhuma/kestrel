"""A change request follows every later round: new commits or a comment
saying why there are none, and kestrel's section of the description kept
up to date without touching what people wrote (#93 follow-up)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.document_formats.markdown import render_markdown
from app.documents import Text, document, paragraph
from app.services.board.delivery import deliver
from app.services.board.delivery_rounds import RoundHistory, RoundWork
from app.services.board.workspace import SCRATCH_DIR
from app.services.change_requests import splice_section
from app.services.github import GitHubClient, GitHubCodeHost
from app.services.gitlab import GitLabCodeHost
from tests.test_board_delivery import (
    _FakeCodeHost,
    _provisioned_workspace,
    _workflow,
)

_SECTION = "## Maintained by kestrel\n\nnew text\n\nEnd of the section."


_NUMBER = 7


def _with_number(workflow):
    return replace(workflow, change_request_number=_NUMBER)


def _git(dest: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=dest, check=True,
        capture_output=True, text=True,
    ).stdout


_ROUND = RoundHistory(
    lines=(),
    current=(RoundWork("impl-2", "Requested changes: bigger font",
                       "Raised the heading size to 2rem."),),
)


def test_the_section_is_replaced_and_the_rest_kept() -> None:
    """Ensure a reviewer's text around kestrel's section survives."""
    old = (
        "Reviewer notes on top.\n\n## Maintained by kestrel\n\nold text\n\n"
        "End of the section.\n\nMore notes below."
    )

    new = splice_section(old, _SECTION)

    assert new == (
        "Reviewer notes on top.\n\n" + _SECTION + "\n\nMore notes below."
    )


def test_a_removed_section_is_appended() -> None:
    """Ensure the section comes back when someone deleted it."""
    assert splice_section("Only notes.", _SECTION) == (
        "Only notes.\n\n" + _SECTION + "\n"
    )


@pytest.mark.asyncio
async def test_a_later_round_with_commits_says_what_was_pushed(
    tmp_path: Path,
) -> None:
    """Ensure new commits are listed with the coder's summary, and the
    section records the round."""
    svc = await _provisioned_workspace(tmp_path)
    host = _FakeCodeHost()
    await svc.push("wf-1", None)
    dest = svc.workspace_dir("wf-1")
    Path(dest, "style.css").write_text("h1 { font-size: 2rem }\n")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-m", "Bigger heading")

    delivered = await deliver(_with_number(_workflow()), host, svc, _ROUND)

    assert delivered.line == "Requested changes: bigger font: 1 commit(s)"
    ((number, comment),) = host.comments
    text = render_markdown(comment)
    assert number == _NUMBER
    assert "Changes pushed for: Requested changes: bigger font." in text
    assert "Bigger heading" in text
    assert "Raised the heading size to 2rem." in text
    ((_n, section),) = host.sections
    assert "bigger font: 1 commit(s)" in render_markdown(section)


@pytest.mark.asyncio
async def test_a_later_round_without_commits_says_why(tmp_path: Path) -> None:
    """Ensure a round that changed nothing still says so, with the reason."""
    svc = await _provisioned_workspace(tmp_path)
    host = _FakeCodeHost()
    await svc.push("wf-1", None)

    delivered = await deliver(_with_number(_workflow()), host, svc, _ROUND)

    assert delivered.line.endswith("no code changes were needed")
    text = render_markdown(host.comments[0][1])
    assert "No code changes were needed for: Requested changes" in text
    assert "Raised the heading size to 2rem." in text


@pytest.mark.asyncio
async def test_agent_scratch_files_are_never_committed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure the scratch area is ignored by ``git add -A``, and anything
    else under .kestrel/ that is not a screenshot is reported."""
    svc = await _provisioned_workspace(tmp_path)
    dest = svc.workspace_dir("wf-1")
    for name in (f"{SCRATCH_DIR}/shoot.js", ".kestrel/check.js",
                 ".kestrel/screenshots/home.png"):
        Path(dest, name).parent.mkdir(parents=True, exist_ok=True)
        Path(dest, name).write_text("x")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-m", "work")

    committed = _git(dest, "ls-tree", "-r", "--name-only", "HEAD")
    assert "shoot.js" not in committed
    assert await svc.stray_kestrel_files("wf-1", "main") == [
        ".kestrel/check.js"
    ]
    await deliver(_workflow(), _FakeCodeHost(), svc)
    assert ".kestrel/check.js" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_rewrites_its_section_and_adds_a_note() -> None:
    """Ensure the merge request's description keeps the reviewer's text,
    and a round becomes a note."""
    calls: list[tuple[str, str, dict]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        calls.append((req.method, req.url.path, body))
        if req.method == "GET":
            return httpx.Response(200, json={"description": "Mine."})
        return httpx.Response(201, json={"id": 42})

    host = GitLabCodeHost("https://gitlab.test", "glpat")
    host._http = httpx.AsyncClient(
        base_url="https://gitlab.test/api/v4",
        transport=httpx.MockTransport(handle),
    )

    await host.write_kestrel_section(
        "g/svc", 7, document(paragraph(Text("## not a heading"))),
    )
    note = await host.comment_on_change_request(
        "g/svc", 7, document(paragraph(Text("Round done."))),
    )

    put = [c for c in calls if c[0] == "PUT"][0]
    assert put[1].endswith("/merge_requests/7")
    assert put[2]["description"].startswith("Mine.\n\n")
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1].endswith("/merge_requests/7/notes")
    assert post[2] == {"body": "Round done."}
    assert note == "42"


@pytest.mark.asyncio
async def test_github_rewrites_its_section_and_comments() -> None:
    """Ensure the pull request's body is patched and a round becomes a
    conversation comment."""
    calls: list[tuple[str, str, dict]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        calls.append((req.method, req.url.path, body))
        if req.method == "GET":
            return httpx.Response(200, json={"body": "Mine."})
        return httpx.Response(201, json={"html_url": "https://c/1"})

    client = GitHubClient("https://api.github.test", "tok")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.test",
        transport=httpx.MockTransport(handle),
    )
    host = GitHubCodeHost(client, "https://github.test")

    await host.write_kestrel_section(
        "o/r", 7, document(paragraph(Text("Section."))),
    )
    url = await host.comment_on_change_request(
        "o/r", 7, document(paragraph(Text("Round done."))),
    )

    patch = [c for c in calls if c[0] == "PATCH"][0]
    assert patch[1] == "/repos/o/r/pulls/7"
    assert patch[2]["body"].startswith("Mine.\n\n")
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1] == "/repos/o/r/issues/7/comments"
    assert url == "https://c/1"
