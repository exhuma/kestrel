# Data model: Jira is where people work with kestrel (046)

## Document constructs (extended, `app/documents.py`)

| Construct | Kind | Fields | New |
| --- | --- | --- | --- |
| `Text`, `Strong`, `Emphasis`, `Code` | inline | `value` | |
| `Link` | inline | `href`, `value` | |
| `Mention` | inline | `account_id`, `display_name` | yes |
| `HardBreak` | inline | — | yes |
| `Heading` | block | `level` 1-6, `content` | |
| `Paragraph` | block | `content` | |
| `CodeBlock` | block | `language`, `text` | |
| `ListItem` | — | `content: tuple[Paragraph \| BulletList \| OrderedList]` | nested lists |
| `BulletList`, `OrderedList` | block | `items` (+ `start`, now rendered) | |
| `Image` | block | `src`, `alt` | yes |
| `Table` | block | `header: tuple[Cell]`, `rows: tuple[tuple[Cell]]`; `Cell = tuple[Inline]` | yes |
| `Rule` | block | — | |
| `Marker` | block | `name` (e.g. `posted`) | yes |

Validation (builders and parsers alike): non-empty inlines, heading level,
non-empty lists, rectangular tables, non-empty `account_id`. Parsers MUST
return validated documents, which today's `parse_markdown` does not.

Derived queries on `Document` (pure, no format knowledge): `markers() ->
frozenset[str]`, `plain_text() -> str`, `mentions() -> frozenset[str]`
(unused for reply detection until a service account exists).

## Port value types (`app/ports.py`)

- `Person(account_id: str, display_name: str)`
- `Task(ref, title, body: Document, reporter: Person | None, change_owner:
  Person | None)`
- `Feedback(external_id, origin, author: Person, body: Document,
  created_at)`

## Persistence (Alembic 0036)

**`board_workflow`**: `task_body` and `approved_prd` hold document JSON. The
migration parses the existing Markdown once.

**`board_external_projection`** (existing ledger), new columns:

| Column | Type | Note |
| --- | --- | --- |
| `task_ref` | Text, nullable | where to post; null on old rows |
| `payload` | Text, nullable | document JSON, for retry; null on old rows |
| `attempts` | Integer, default 0 | retry backoff |

New kinds: `gate_opened`, `status`, `reply`.

**`board_comment_cursor`** (new):

| Column | Type |
| --- | --- |
| `workflow_id` | Text, PK, FK `board_workflow` |
| `cursor` | Text (adapter-owned, opaque) |
| `updated_at` | DateTime (naive UTC) |

**`board_inbound_comment`** (new): one row per considered comment.

| Column | Type | Note |
| --- | --- | --- |
| `external_id` | Text, PK | e.g. `jira-comment:KEY-1:10042` |
| `workflow_id` | Text, FK | |
| `gate_card_id` | Text, nullable | the gate it was matched to |
| `author_account_id` | Text | |
| `state` | Text | see below |
| `security_review_id` | Text, nullable | when held |
| `intent` | Text, nullable | `approve` / `reject` / `unclear` |
| `created_at`, `processed_at` | DateTime | |

States: `ignored` (no `@kestrel` marker / carries kestrel's own
`Marker`) are **not** stored, only
skipped by cursor. Stored states: `refused` (not entitled), `held`
(screening), `unclear` (asked back), `decided`, `already_decided`,
`no_gate` (nothing open), `interview_pointer`.

```
            ┌──────── refused / no_gate / interview_pointer / already_decided
new ────────┤
 (@kestrel, ├── held ──(operator releases)──▶ re-processed as new
  entitled) │            └─(discarded)──▶ stays held, ticket told
            └── screened ─▶ liaison ─┬─ approve / reject(+reason) ─▶ decided
                                     └─ unclear / reason missing ──▶ unclear
```

## Gate decision attribution

`GatesService.resolve(card_id, decision, *, answer=None, decided_by:
Decider | None = None)` where `Decider(channel: "ui" | "jira", account_id,
display_name, comment_external_id)`. It is written into the `gate.approved`
or `gate.rejected` event payload. `None` means the UI operator, as today.

Rejection reason rule, now backend-enforced: `confirm_understanding` and
`approve_prd` rejections require a non-empty `answer`.

## Announcements: event → comment

| Trigger (board event) | Kind / idempotency key | Mentions | Content |
| --- | --- | --- | --- |
| `gate.opened` understanding | `gate_opened:{card}` | reporter | restatement, how to answer |
| `gate.opened` strategic interview | `gate_opened:{card}` | reporter | number of questions, form link |
| `gate.opened` refinement (batch) | `gate_opened:batch:{plan}` | reporter | personas asking, question count, form link |
| `gate.opened` PRD | `gate_opened:{card}` | reporter | the PRD in full, how to answer |
| `gate.opened` CAB-1 | `gate_opened:{card}` | change owner | ready for CAB: strategic-fit answers |
| `gate.opened` CAB-2 | `gate_opened:{card}` | change owner | ready for CAB: executive summary |
| delivered | `delivery:{card}` (existing) | change owner | should move on, change-request link |
| workflow outcome failed / cancelled | `status:outcome:{workflow}` | change owner | should move on, why |
| CI failed / repaired | `status:ci:{card}:{round}` | — | status line |
| escalation | `escalation:…` (existing) | — | status line |
| reply outcome | `reply:{comment external_id}` | the author | confirmation / refusal / question / held / already decided |

Every announcement ends with a kestrel link (`public_base_url`; omitted
when unset) and a `Marker("posted")`. No row mentions a CAB member, and
none changes the issue's status.

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| `change_owner_field` | `[[task_sources]]` jira | `""` (unset ⇒ "no change owner" path) |
| `board_comment_poll_interval_seconds` | global | 60 |
| `board_projection_retry_interval_seconds` | global | 120 |
| `feedback_marker` | global | `@kestrel` (revived: the plain-text reply marker) |
| `feedback_ignore_authors`, `feedback_window_days` | global | removed (dead since the clean break) |
