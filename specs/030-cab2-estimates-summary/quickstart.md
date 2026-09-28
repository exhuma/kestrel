# Quickstart: validating feature 030

## Automated

```
task quality                         # structural limits, lint, dead code
cd backend && uv run pytest -q
cd frontend && npm test
```

Key scenarios the tests must cover (each maps to a spec story):

| Scenario | Where |
| --- | --- |
| strict candidate parse: missing classification or summary, duplicate id → coordinator_review, no estimation card | backend decomposition tests |
| valid candidate → normalized `decomposition_candidate` and one `estimation` card with a dependency edge, no gate | backend decomposition tests |
| valid estimates → proposal + gate "(c coding, m manual)" + exec summary on the gate card | backend estimation tests |
| totals equal sums/counts; size counts "2×S, 1×L" | backend summary renderer tests |
| invalid estimates (missing, unknown, duplicate id; manual with tokens; coding with 0 hours) → coordinator_review, no gate | backend estimation tests |
| gate already awaiting → no second gate | backend estimation tests |
| publish: manual gets both sentinels and the manual header; estimate section on every task; legacy candidate publishes unchanged | backend publish tests |
| ingestion skips a body with the manual sentinel, on every poll | backend ingestion tests |
| coordinator cannot create an `estimation` card | backend coordinator tests |
| snapshot carries `task_body`; listing does not | backend board API tests |
| rail: request slot available iff body non-empty; exec summary slot follows the gate | frontend `artifacts` tests |
| dialog direct mode: freshness note shown, no trust chip, no fetch | frontend `ArtifactDialog` tests |
| action banner offers "Read executive summary" on a CAB-2 ask | frontend `ActionBanner` tests |

## Manual walk-through (fixture task source)

1. Enable decomposition (`KESTREL_BOARD_DECOMPOSITION_REQUIRED=true`) and run
   the dev stack.
2. Ingest a fixture task and approve the gates through to decomposition.
3. When the pm's decomposition completes, the cockpit shows an "Estimate
   decomposition" card in Technical analysis, and there is no CAB-2 ask yet.
4. When estimation completes, the banner asks for CAB-2. "Read executive
   summary" opens the summary with the `agent_output` chip. Check its totals
   against the task table.
5. Approve. The fixture source gets one sub-task per task. The manual ones
   carry `<!-- kestrel:manual -->`, and no workflow appears for them after the
   next poll.
6. In the rail, "Original request" opens the request text with the freshness
   note and no trust chip.
