# Contract: port changes (`app/ports.py`)

```python
@dataclass(frozen=True)
class Person:
    account_id: str
    display_name: str

@dataclass(frozen=True)
class Task:
    ref: str
    title: str
    body: Document                 # was str
    reporter: Person | None = None
    change_owner: Person | None = None

@dataclass(frozen=True)
class Feedback:
    external_id: str
    origin: Literal["ticket", "review"]
    author: Person                 # was str (display name)
    body: Document                 # was str
    created_at: datetime

class TaskSource(Protocol):
    async def post_comment(self, ref: str, body: Document) -> str: ...
    async def publish_refined(self, ref: str, content: Document) -> None: ...
    async def create_subtask(self, parent_ref: str, title: str,
                             body: Document, markers=()) -> str: ...
    async def list_comments(self, ref: str,
                            since: str | None) -> CommentPage: ...
    # transition(): documented as sub-tasks only (constitution, 4th constraint)

class CodeHost(Protocol):
    async def open_change_request(..., body: Document, ...) -> ...: ...
```

`CommentPage(comments: list[Feedback], cursor: str | None)`: the adapter
returns the cursor to store, so cursor semantics stay inside the adapter
(Jira: last seen `created` timestamp; inclusive, deduped by external id).

Every `| str` is removed. `Task.title` stays `str` (a title is a label, not
a document).
