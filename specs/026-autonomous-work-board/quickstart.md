# Validation Guide: Autonomous Work Board

## Prerequisites

- A configured local task source and local bare repository, or configured
  GitHub/Jira task source and code host.
- A configured backend that can provide text turns; a file-edit-capable backend
  for coder cards.
- A valid specialist root with the default named roles.
- Standard local dependencies installed for `task quality`.

## Validate Specialist Configuration

1. Start Kestrel with the default specialist tree.
2. Confirm startup reports the loaded named roles without printing full prompt
   content.
3. Make one required manifest invalid, such as removing a required ability.
4. Confirm startup refuses the configuration before task ingestion starts.
5. Restore the manifest and restart successfully.

Expected outcome: no missing, incompatible, or unsafe specialist can receive a
card.

## Validate Safe Intake and Quarantine

1. Create a normal source task with a bounded ordinary request.
2. Observe the workflow and its initial board cards become available.
3. Submit a second source task or marked feedback containing an unsafe
   instruction pattern.
4. Open the resulting security review from Board or List.
5. Verify no specialist session, source acknowledgement, translation, or source
   mutation occurred for the quarantined input.
6. Release the review and verify a recorded decision permits the expected board
   event; repeat with discard and verify the source remains unchanged.

Expected outcome: external and gate input is fail-closed, deduplicated, and
operator-resolvable.

## Validate Scheduling and Recovery

1. Use a workflow containing two independent analysis cards, one coder card,
   and a dependent verifier card.
2. Observe both analysis cards claim concurrently when capacity permits.
3. Confirm the coder cannot run concurrently with another write-capable card
   for the same repository.
4. Stop Kestrel during an active card attempt and wait past its lease expiry.
5. Restart Kestrel and inspect the card event history and retained artifacts.

Expected outcome: completed artifacts survive; the interrupted attempt is
recorded; the card follows bounded retry, reassignment, or escalation policy;
and a repository never has two active writers.

## Validate Gates, Verification, and Projection

1. Drive understanding, refinement, PRD, and decomposition work to their gate
   cards. Resolve each through the board.
2. Submit an implementation nonconformance from verifier work and confirm an
   internal remediation card is created without a human gate.
3. Submit a requirements ambiguity and confirm a coordinator review and, when
   needed, human gate are created without changing the approved PRD.
4. Inspect the source task after ordinary claims/retries and after a gate,
   escalation, approved artifact, child work, and delivery.

Expected outcome: only the selected human-meaningful milestones project to the
source; public source cleanup affects only durably recorded Kestrel resources.

## Validate Operator UI

1. Open a workflow with cards in each waiting and terminal state.
2. Use Board to distinguish dependency waiting, human waiting, and quarantine.
3. Use List with only a keyboard to select a card, inspect details, and invoke
   an allowed action.
4. Open Graph, select the same card, filter direct dependencies, and confirm
   the shared detail view updates.
5. Trigger a stale intervention from a second browser state and confirm the UI
   reports the conflict without losing the operator's unsent draft.

Expected outcome: Graph explains relationships while Board/List remain the
complete accessible control surface.

## Required Automated Checks

Run the repository's full gate after implementation:

```text
task quality
```

Add backend tests for policy transitions, cycle rejection, atomic claims,
recovery, artifact provenance, all input transports, quarantine side-effect
blocking, and projection idempotency. Add frontend tests using mocked HTTP/SSE
for state grouping, safe rendering, interventions, stale revisions, keyboard
operation, and graph-to-detail selection.
