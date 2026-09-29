# Specialist definitions

One subdirectory per named role, loaded from `specialists_root`
(`KESTREL_SPECIALISTS_ROOT`, default `./specialists`) by
`backend/app/services/board/specialists.py`. Each role directory holds:

- `manifest.toml` — the role's identity, contract, and limits.
- `prompt.md` — the prompt content referenced by the manifest's
  `prompt_file`.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `id` | Stable machine id. Must match the directory name. |
| `label` | Human-readable name shown on the board. |
| `purpose` | One-line role summary. |
| `allowed_card_types` | Card kinds this specialist may claim. Empty for a role that never claims a card (e.g. the coordinator, which only proposes actions). |
| `required_abilities` | Backend `Capability` values this role needs (`text`, `file_edits`, `tool_use` — see `app/backends/base.py`). Validated against the dispatched backend's advertised `caps`, and `file_edits` is required whenever `workspace_permission` is `write`. |
| `model_policy` | `"default"` uses the configured default session backend/model; a specific backend id pins this role to it. |
| `workspace_permission` | `none`, `read_only`, or `write`. `write` requires a repository workspace lease at claim time. |
| `retry_limit` | Maximum attempts before a card claimed by this role escalates. |
| `prompt_file` | Path, relative to this role's directory, to its prompt content. |

## Card kinds (this feature's initial vocabulary)

`understanding_gate`, `refinement_gate`, `prd_gate`, `decomposition_gate` are
human gates: no specialist claims them, the operator resolves them directly.
`security_review` is claimed only by `input-security` (structured
classification, no tools, no workspace — see its manifest). `analysis` and
`design` are read-only specialist work. `estimation` is `developer`'s
read-only sizing of a decomposition, created only by decomposition routing
(never by the coordinator); its valid result opens the
`decomposition_gate` (CAB-2). `implementation` is write-capable
coder work. `verification` is the verifier's work. Approving CAB-2
creates, per approved coding task, an `implementation` card and the
`verification` card that checks it, and per approved manual task a
`manual_task` card. No specialist ever claims a `manual_task`: it is the
operator's own work, which the operator marks done. `reconciliation` is
created only by the coordinator when specialist outputs conflict.

## Roles

- `requester`, `pm`, `uiux`, `developer`, `infosec`, `dba`, `architect`,
  `ops`, `qa` — the existing interview/analysis personas (feature 012),
  carried over with their prompts unchanged.
- `coordinator` — proposes bounded board actions; never claims a card or
  holds workspace access itself (FR-004, FR-005, FR-006).
- `coder` — the only role that claims `implementation` cards and holds a
  repository write lease.
- `verifier` — claims `verification` cards; routes ordinary nonconformance
  to internal remediation and ambiguity/risk to the coordinator (FR-027,
  FR-028).
- `input-security` — classifies untrusted input for the quarantine boundary
  (FR-019). Structured-output-only: no tools, no workspace access, so it can
  safely see content nothing else has cleared yet.
