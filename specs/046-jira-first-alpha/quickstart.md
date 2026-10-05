# Quickstart: validating 046

## Prerequisites

- A Jira Cloud project, the operator's API token in
  `KESTREL_JIRA_API_TOKEN` (kestrel posts as the operator; no service
  account yet), a user-picker custom field for the change owner, and two
  test users: a reporter and a change owner.
- `config.toml`: a `[[task_sources]] type = "jira"` entry with
  `change_owner_field = "customfield_NNNNN"`, and `public_base_url` set.
- `uv run alembic upgrade head` (applies 0036).

## Automated

```sh
task quality                 # includes the new import-linter contract
cd backend && uv run pytest  # document round-trips, ADF mapping, announcements,
                             # comment poller, entitlement, liaison parsing
cd frontend && npx vitest run
```

Key suites (see `tasks.md` for exact files): ADF round-trip property over
the closed set ([adf-mapping](contracts/adf-mapping.md)); a fake Jira
adapter driving a full request through every gate from comments only.

## Manual, against Jira Cloud

1. **Rendering (Story 1).** Ingest an issue whose description has a
   heading, a nested list, a table and a link. The cockpit's "Original
   request" shows the same structure. The restatement comment kestrel posts
   shows no raw `#`, `*` or `|`, and the reporter mention notifies.
2. **Announcements (Story 2).** Walk a request through the gates:
   - each gate opening adds exactly one comment;
   - the interview comment links to the form and asks nothing on the
     ticket;
   - the CAB-1 and CAB-2 comments mention only the change owner;
   - after delivery the change owner is asked to move the issue on;
   - the issue's status never changes;
   - clear the change-owner field and confirm the "no change owner" text.
3. **Retry (Story 2).** Block kestrel's network access to Jira while a gate
   opens, then restore it. The comment appears once.
4. **Replies (Story 3).**
   - As the reporter, reply `@kestrel looks right` under the restatement:
     the gate is approved, a confirmation follows, and the cockpit feed
     says who decided, via Jira.
   - Reply `@kestrel no` under the PRD: kestrel asks for the reason, and
     the gate stays open.
   - As a third user, reply `@kestrel approve`: kestrel refuses, and
     nothing changes.
   - As the change owner, relay `@kestrel CAB approved` on CAB-2: the
     decomposition is approved.
   - Edit an already-processed reply: nothing happens.
   - As the operator (the account kestrel posts with), reply
     `@kestrel looks right` where you are entitled: it is acted on. Kestrel's
     own announcements, which also contain `@kestrel`, are never acted on.
   - Restart kestrel: no comment is posted twice and no reply is acted on
     twice.
5. **Held reply (Story 3).** Post a reply that screening holds back, for
   example a prompt-injection attempt. The ticket says it is held. Release
   it in the UI and confirm it is then acted on.
