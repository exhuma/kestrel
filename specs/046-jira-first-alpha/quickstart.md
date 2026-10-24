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
   - clear the change-owner field and confirm the "no change owner" text;
   - resolving an interview form posts nothing; the next comment is the
     acknowledgement;
   - a gate decided in the UI reads as one plain sentence (for example
     "PRD signed off."), not "Gate approved: ...".
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
   - Write `@kestrel looks right` on the ticket *before* a gate is
     announced (for example while the interview is still open), then let
     the gate open: the old comment is never acted on and gets no answer.
   - Edit an already-processed reply: nothing happens.
   - As the operator (the account kestrel posts with), reply
     `@kestrel looks right` where you are entitled: it is acted on. Kestrel's
     own announcements, which also contain `@kestrel`, are never acted on.
   - Restart kestrel: no comment is posted twice and no reply is acted on
     twice.
5. **Held reply (Story 3).** Post a reply that screening holds back, for
   example a prompt-injection attempt. The ticket says it is held. Release
   it in the UI and confirm it is then acted on.

## Results

To be filled in by Michel on Jira Cloud (T047). Date and kestrel version:
_______.

**Limitations of a one-person test.** Michel is the reporter, the change
owner and kestrel's posting account at once, so some steps cannot be
exercised as written:

- **Stranger refusal** (step 4, third bullet) cannot be tried with a third
  user. Clear the change-owner field instead: nobody is then entitled at
  CAB-1 or CAB-2, so a reply to a CAB gate is refused. (Or ask a colleague to
  reply once.)
- **Notifications** cannot be observed, because every comment is
  self-authored and Jira does not notify you of your own activity. Check only
  that mentions render as chips (a name, not raw `[~accountid:...]`).
- The reporter's and the change owner's replies come from the same account,
  so "the reporter may not decide CAB" is covered by the unit tests only.

Steps:

- [ ] 1. Rendering: description structure matches in the cockpit; the
  restatement comment shows no raw Markdown; the mention renders as a chip.
- [ ] 2. Announcements: exactly one comment per gate opening.
- [ ] 2. The interview comment links the form and asks nothing here.
- [ ] 2. CAB-1 and CAB-2 mention only the change owner.
- [ ] 2. After delivery the change owner is asked to move the issue on.
- [ ] 2. The issue's status never changes.
- [ ] 2. With the change-owner field cleared, the "no change owner" text
  appears.
- [ ] 2. Resolving an interview form posts nothing.
- [ ] 2. A gate decided in the UI reads as one plain sentence.
- [ ] 3. Retry: with Jira unreachable while a gate opens, the comment
  appears once after the connection returns.
- [ ] 4. `@kestrel looks right` under the restatement approves it; the
  confirmation reads "thank you. Understanding confirmed."; the cockpit
  says who decided, via Jira.
- [ ] 4. `@kestrel no` under the PRD: kestrel asks for the reason; the gate
  stays open.
- [ ] 4. Stranger refusal (with the change-owner field cleared, see above).
- [ ] 4. `@kestrel CAB approved` on CAB-2 approves the decomposition.
- [ ] 4. A comment written before the gate's announcement is not acted on
  and gets no answer.
- [ ] 4. Editing a processed reply changes nothing.
- [ ] 4. The operator's own `@kestrel` reply is acted on where entitled;
  kestrel's announcements never are.
- [ ] 4. After a restart, nothing is posted or acted on twice.
- [ ] 5. A held reply: the ticket says it is held; releasing it in the UI
  has it acted on.

Notes:
