# Tasks: Bounded, visible agent tool use (036)

**Input**: `specs/036-agent-tool-guard/spec.md`

## Phase 1: Foundation

- [X] T001 Config: `allowed_tools`, `max_tool_calls`,
  `max_repeated_tool_calls` on `BackendConfig` in
  `backend/app/config_models.py`; validation; `config.toml.example`; tests
- [X] T002 `TurnRequest.on_tool`, `TurnStopped` in
  `backend/app/backends/base.py`; `run_card_turn` takes a `TurnRequest`

## Phase 2: User Stories 1 and 2 (P1)

- [X] T003 [US1] [US2] `backend/app/backends/opencode_tools.py`: the tools
  map and `ToolLoopGuard`; the event loop feeds tool parts to it;
  `opencode.py` sends the map, aborts a tripped turn, raises `TurnStopped`;
  tests
- [X] T004 [US2] `turn_failure` names a stopped turn's reason; tests

## Phase 3: User Story 3 (P2)

- [X] T005 [US3] `LiveTurn.tool`/`tool_calls`, throttled announce; card
  turns report tools; `RequestActivityOut.tool`/`tool_calls`; frontend
  activity line; tests

## Phase 4: Polish

- [X] T006 Contract and architecture docs; full gate; commit; push
