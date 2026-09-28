# Data model: CAB-2 estimates, coding/manual split, and executive summary

No database schema changes. All new data lives in artifact content (JSON or
Markdown) or in fields that are computed when read. Card kinds are stored as
text, so adding one needs no migration.

## New card kind

| Kind | Claimed by | Workspace | Created by | Routed by |
| --- | --- | --- | --- | --- |
| `estimation` | `developer` | `read_only` | decomposition routing (code), never the coordinator | `route_estimation_result` |

- `eligible_roles = ("developer",)`, `state = ready`, title `"Estimate
  decomposition (N tasks)"`.
- One `dependency` relation from the estimation card to the decomposition card
  whose candidate it estimates (research R2).
- Phase projection: "Technical analysis" (phase 7).

## Classified task (in `decomposition_candidate`, from the pm)

| Field | Type | Rule |
| --- | --- | --- |
| `title` | string | required, non-empty |
| `body` | string | required, non-empty |
| `task_node_id` | string | unique within the candidate; assigned `t<n>` when absent (R4) |
| `prerequisites` | list[string] | optional, default `[]` |
| `classification` | `"coding"` \| `"manual"` | required (strict mode); defaults to `coding` only when reading a legacy gate target |

The candidate document is `{"summary": string, "tasks": [ClassifiedTask…]}`.
`summary` is required in strict mode. It holds the pm's 1–2 paragraph prose.

The stored `decomposition_candidate` is the **normalized** form: ids have been
assigned, whitespace trimmed and types checked. The estimator and publishing
see exactly what was validated.

## Task estimate (from the developer)

| Field | Type | Rule |
| --- | --- | --- |
| `task_node_id` | string | must match exactly one candidate task |
| `size` | `S` \| `M` \| `L` \| `XL` | required |
| `confidence` | `low` \| `medium` \| `high` | required |
| `man_hours` | number | > 0 for every task |
| `agent_tokens` | integer | > 0 for coding, == 0 for manual |
| `review_hours` | number | > 0 for coding, == 0 for manual |
| `risks` | list[string] | may be empty; each entry trimmed, deduplicated |
| `rationale` | string | non-empty; newlines collapsed to one line |

## CAB-2 proposal (gate target, `logical_name = "cab2_proposal"`)

```json
{
  "summary": "…pm prose…",
  "tasks": [
    {
      "task_node_id": "t1", "title": "…", "body": "…",
      "prerequisites": [], "classification": "coding",
      "estimate": {"size": "M", "confidence": "medium", "man_hours": 6,
                   "agent_tokens": 400000, "review_hours": 1.5,
                   "risks": ["schema migration"], "rationale": "…"}
    }
  ]
}
```

- Producer: the estimation card. Trust: `agent_output`.
- It is a superset of the candidate. The lenient parser (R4) reads both this
  and pre-feature candidates, so publishing has one code path.
- It is the structured record a future estimate-vs-actual feature reads,
  joined to child workflows through `child_task_link.task_node_id` (FR-016).

## Executive summary (`logical_name = "executive_summary"`)

- Producer: the CAB-2 (`decomposition_gate`) card. Trust: `agent_output`.
  MIME type: `text/markdown`.
- Built only by code (`render_executive_summary`) from the proposal. Its
  sections, in order:
  1. A header line: "Agent estimates — unverified. kestrel makes no go/no-go
     recommendation."
  2. The pm's prose, verbatim.
  3. **Totals**: size counts in S/M/L/XL order, omitting zero buckets (for
     example "2×S, 1×L"); total man-hours; total agent tokens; total review
     hours; the low-confidence count "k of n"; and "c coding, m manual".
  4. **Risks**: each distinct risk flag with the `task_node_id`s it applies
     to. Omitted when there are none.
  5. **Tasks**: one Markdown table row per task, with id, title,
     classification, size, confidence, man-hours, tokens, review hours and
     rationale.
- Totals are sums and counts over the per-task figures, and nothing else
  (SC-002). Hours are shown to one decimal place and tokens with thousands
  separators.

## Gate title (FR-015)

`Approve decomposition (c coding, m manual)`. A zero side is still shown, for
example `(0 coding, 2 manual)`, so the split is never implied.

## Manual marker

`ManualTaskSentinel` renders `<!-- kestrel:manual -->` (or its code-span form
on Jira). It is applied **in addition to** `SubtaskSentinel` on published
manual tasks. Ingestion never creates a workflow for a body that contains it.

## Published sub-task body

```
<task body>

## Estimate (agent, unverified)
Size M · confidence medium · ~6.0 man-hours · ~400,000 agent tokens ·
~1.5 review hours
Risks: schema migration
Rationale: …
```

A manual task additionally opens with the line: "**Manual task** — for a
human. kestrel will not assign this to an agent." Legacy candidates without an
estimate get no section (FR-019).

## Board snapshot addition

`BoardSnapshotOut.task_body: str` (default `""`) holds `Workflow.task_body`
verbatim. It is not added to `WorkflowSummaryOut`. It is mirrored as
`BoardSnapshot.task_body: string`.
