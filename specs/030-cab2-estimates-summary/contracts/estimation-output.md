# Contract: developer estimation output (new)

The specialist is `developer`, on an `estimation` card. The envelope's extra
context carries the normalized candidate: each task's `task_node_id`, title,
body and classification.

```
<ESTIMATES>{
  "estimates": [
    {
      "task_node_id": "t1",
      "size": "M",
      "confidence": "medium",
      "man_hours": 6,
      "agent_tokens": 400000,
      "review_hours": 1.5,
      "risks": ["schema migration"],
      "rationale": "One new table plus a service; tests exist for the neighbour."
    }
  ]
}</ESTIMATES>
```

| Field | Meaning |
| --- | --- |
| `size` | S, M, L or XL, relative to this codebase |
| `confidence` | low, medium or high: how much you trust your own numbers |
| `man_hours` | hours for one competent developer who knows this codebase to do it **by hand, without an agent** |
| `agent_tokens` | total tokens (input and output) an autonomous coding agent would use to implement and self-test it; `0` for manual tasks |
| `review_hours` | hours for a human to review the agent's change; `0` for manual tasks |
| `risks` | short named risks (e.g. "schema migration", "touches auth", "no tests in area"); may be empty |
| `rationale` | one line explaining the numbers |

Validation (all fail closed, as a coordinator_review card "Invalid estimates
on card {id}: {reason}", with no gate):
- the block is present and is valid JSON with an `estimates` list;
- there is exactly one entry per candidate `task_node_id`, with no unknown ids
  and no duplicates;
- enums are valid, and the numbers are finite and non-negative, with
  `agent_tokens` an integer;
- `man_hours > 0` for every task;
- coding tasks have `agent_tokens > 0` and `review_hours > 0`;
- manual tasks have `agent_tokens == 0` and `review_hours == 0`;
- `rationale` is a non-empty string, and `risks` is a list of strings.

On success, in order:
1. the `cab2_proposal` artifact is stored (producer: the estimation card);
2. the `decomposition_gate` is created, titled `Approve decomposition (c
   coding, m manual)`, with `requested_decision=approve_decomposition` and
   `target_artifact_id` set to the proposal;
3. the `executive_summary` artifact is stored, produced by the gate card.

If a `decomposition_gate` is already `awaiting_human` in the workflow, steps
1–3 are skipped and a coordinator_review card is created instead (R6).
