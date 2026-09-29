# Feature Specification: Bounded, visible agent tool use

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: Review of Vikunja 710 (2026-09-29). While the PRD was being
written, opencode logged a step about every 1.5 s: the `pm` specialist, on
a Qwen model, called the operator's GitLab MCP tool `gitlab_list_project_issues`
over and over (step 171 and counting). kestrel showed only "Project Manager
is working…". The developer asked for all three proposed fixes, with the
tool allowlist set in the config file per backend, since opencode is only
one possible backend.

## Context

A board turn is one request to the backend. opencode runs its own agent loop
inside it: call the model, run the tool it asks for, repeat. Three gaps let
the loop above run unchecked:

1. **Every tool the backend offers is available.** Turns run on opencode's
   default agent, so any MCP server in the operator's opencode config
   (GitLab here) is available to every specialist. None of them needs it:
   the ticket is in their prompt.
2. **Nothing bounds the loop but the turn timeout** (600 s by default,
   hundreds of identical calls).
3. **Nothing shows it.** kestrel reads a turn's tool calls only after the
   turn ends.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Only the tools I allow (Priority: P1)

The operator lists the tools a backend may use in the config file:
`allowed_tools = ["read", "grep", "glob", "list", "bash", "edit", "write"]`.
Every turn on that backend can see only those tools. Tools not listed
(MCP tools included) are hidden from the model. Without the setting, the
backend behaves exactly as before.

**Acceptance Scenarios**:

1. **Given** an opencode backend with `allowed_tools`, **When** a turn runs,
   **Then** only the listed tools are available, and read-only turns still
   cannot write.
2. **Given** `allowed_tools` on a backend that cannot honour it, **When**
   kestrel starts, **Then** the config is rejected with a clear error,
   rather than silently ignored.

### User Story 2 - A looping agent is stopped (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a turn calls the same tool with the same input
   `max_repeated_tool_calls` times (default 5), **When** it does, **Then**
   kestrel aborts the turn and the request shows the reason, naming the
   tool.
2. **Given** a turn makes more than `max_tool_calls` tool calls (default
   150), **When** it does, **Then** kestrel aborts it the same way.
3. **Given** an aborted card turn, **When** it ends, **Then** it is handled
   like any other failed turn: recorded on the request, and retried by the
   usual recovery.

### User Story 3 - See tool use while it happens (Priority: P2)

**Acceptance Scenarios**:

1. **Given** a specialist is working, **When** it calls tools, **Then** the
   request's activity line shows the latest tool and how many calls the
   turn has made, for example "calling gitlab_list_project_issues (×40)",
   updated while the turn runs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A backend in the config file MAY set `allowed_tools`, a list
  of tool names (the backend's own names and wildcards). Only `opencode`
  supports it today; setting it on any other backend type MUST fail
  config validation.
- **FR-002**: With `allowed_tools` set, every opencode turn MUST deny all
  tools except the listed ones. Read-only turns MUST still deny the
  file-writing and delegation tools, even if they are listed.
- **FR-003**: Each opencode turn MUST be aborted when one tool is called
  with identical input `max_repeated_tool_calls` times, or when it makes
  more than `max_tool_calls` calls. Both are per-backend settings.
- **FR-004**: An aborted turn MUST fail with a safe reason that names the
  tool and the limit, and a card turn MUST record that reason on the
  request.
- **FR-005**: While a card turn runs, the request's activity MUST carry
  the latest tool called and the number of calls so far, and live views
  MUST be updated at most every 2 s per turn.

## Success Criteria *(mandatory)*

- **SC-001**: A turn repeating a tool call with identical input is stopped
  within `max_repeated_tool_calls` calls.
- **SC-002**: With an allowlist, a specialist cannot call an unlisted tool.
- **SC-003**: The operator can tell a looping turn from a productive one
  without opening the backend's logs.

## Assumptions

- The loop guard and the live tool view come from opencode's event stream,
  which kestrel already reads during a turn to answer permission prompts.
  Other backends keep their current behaviour.
- The allowlist uses opencode's per-message `tools` map. opencode turns it
  into session permission rules, where the last matching rule wins and a
  denied tool is hidden from the model.

## Out of scope

- Per-specialist tool lists.
- Tool allowlists for `claude_cli` (its flags differ) and `openai_compat`
  (it runs no tools).
