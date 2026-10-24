"""A Jira description keeps its structure from the ticket to the agent
(feature 046, User Story 1)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.backends.base import TurnRequest, TurnResult
from app.config import Settings
from app.config_models import TaskSourceConfig
from app.documents import (
    BulletList,
    Heading,
    Link,
    ListItem,
    Table,
    Text,
    document,
    paragraph,
)
from app.persistence.board_quarantine_store import BoardQuarantineStore
from app.persistence.board_store import BoardStore
from app.persistence.dismissal_store import DismissalStore
from app.routers.document_out import api_markdown
from app.services.board.quarantine import QuarantineService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.ingestion import BoardIntake, IngestionService
from app.services.jira import JiraClient, JiraTaskSource
from tests.board_test_support import board_session_factory
from tests.test_board_quarantine import _FakeBackendPolicy, _input_security

_SAFE = (
    '<CLASSIFICATION>{"safe": true, "category": "benign", "reason": "ok"}'
    "</CLASSIFICATION>"
)


def _text(value: str, *marks: dict) -> dict:
    node: dict = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def _para(*content: dict) -> dict:
    return {"type": "paragraph", "content": list(content)}


_DESCRIPTION = {"type": "doc", "version": 1, "content": [
    {"type": "heading", "attrs": {"level": 2}, "content": [_text("Why")]},
    {"type": "bulletList", "content": [{"type": "listItem", "content": [
        _para(_text("Finance")),
        {"type": "bulletList", "content": [{"type": "listItem", "content": [
            _para(_text("monthly")),
        ]}]},
    ]}]},
    {"type": "table", "content": [
        {"type": "tableRow", "content": [
            {"type": "tableHeader", "content": [_para(_text("Format"))]},
        ]},
        {"type": "tableRow", "content": [
            {"type": "tableCell", "content": [_para(_text("CSV"))]},
        ]},
    ]},
    _para(_text("spec", {"type": "link",
                         "attrs": {"href": "https://wiki/spec"}})),
]}

_EXPECTED = document(
    Heading(2, (Text("Why"),)),
    BulletList((ListItem((
        paragraph(Text("Finance")),
        BulletList((ListItem((paragraph(Text("monthly")),)),)),
    )),)),
    Table(((Text("Format"),),), (((Text("CSV"),),),)),
    paragraph(Link("https://wiki/spec", "spec")),
)


class _Classifier:
    """Says safe, remembering what the input-security agent was shown."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        self.prompts.append(req.prompt)
        return TurnResult(session_id="s", final_text=_SAFE)


def _jira() -> JiraTaskSource:
    issue = {"key": "RFC-1", "fields": {
        "summary": "Add CSV export", "description": _DESCRIPTION,
        "reporter": {"accountId": "acc-r", "displayName": "Rita"},
    }}

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=issue)

    client = JiraClient("https://jira.example", deployment="cloud")
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/3",
        transport=httpx.MockTransport(handler),
    )
    return JiraTaskSource(client)


class _Sources:
    def __init__(self) -> None:
        self.sources = {"jira-issue": _jira()}
        self.code_hosts: dict[str, object] = {}


@pytest.mark.asyncio
async def test_a_jira_description_keeps_its_structure_end_to_end(
    tmp_path: Path,
) -> None:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    classifier = _Classifier()
    quarantine = QuarantineService(
        BoardQuarantineStore(factory),
        SpecialistRoster({"input-security": _input_security()}),
        _FakeBackendPolicy(classifier),
        max_bytes=65536, classify_timeout_seconds=5,
    )
    ingestion = IngestionService(
        Settings(task_sources=[TaskSourceConfig(
            type="jira", base_url="https://jira.example", jql="x", key="RFC",
        )]),
        _Sources(), DismissalStore(factory),
        BoardIntake(quarantine, BoardService(store)),
    )

    workflow_id = await ingestion.maybe_start_run(
        source="jira-issue", task_ref="RFC-1", code_repo="o/r"
    )

    workflow = store.get_workflow(workflow_id)
    assert workflow.task_body == _EXPECTED
    original_request = api_markdown(workflow.task_body)
    assert "## Why" in original_request
    assert "- Finance\n  - monthly" in original_request
    assert "| Format |\n| --- |\n| CSV |" in original_request
    assert "[spec](https://wiki/spec)" in original_request
    (screened,) = classifier.prompts
    assert "## Why" in screened
    assert "https://wiki/spec" in screened
