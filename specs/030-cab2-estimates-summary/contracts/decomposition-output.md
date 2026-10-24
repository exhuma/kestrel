# Contract: pm decomposition output (amended)

Amends the `<DECOMPOSITION>` block that `backend/specialists/pm/prompt.md`
asks for. It is validated strictly when routed (research R4).

```
<DECOMPOSITION>{
  "summary": "1–2 paragraphs for a non-technical decision-maker. Describes the work; never recommends approving or rejecting it.",
  "tasks": [
    {
      "task_node_id": "t1",
      "title": "…",
      "body": "…",
      "prerequisites": [],
      "classification": "coding"
    }
  ]
}</DECOMPOSITION>
```

| Rule | On violation |
| --- | --- |
| block present, valid JSON object | coordinator_review "Unparseable decomposition proposal …" |
| `tasks` non-empty list of objects | same |
| `title`, `body` non-empty strings | same |
| `prerequisites` list of strings (optional) | same |
| `classification` ∈ {`coding`, `manual`} on every task | same |
| `summary` non-empty string | same |
| `task_node_id`s unique after assignment | same |

- **coding**: a self-contained, technically scoped change an autonomous coding
  agent can implement in the repository.
- **manual**: anything a human must do, such as approvals, vendor or
  infrastructure actions outside the repository, or communication. Its body
  is written for that human.

On success: the normalized candidate is stored as `decomposition_candidate`
on the decomposition card, and one `estimation` card is created (no gate yet).
