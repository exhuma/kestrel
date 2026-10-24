# Quickstart: Task-Source Feedback

1. Configure a feedback marker and an OpenAI-compatible translation backend.
2. Ingest a task and wait for the understanding review request.
3. Reply with the marker, active token, and an approval; verify refinement
   starts without visiting the UI.
4. Request PRD changes; verify Kestrel replies with a concise delta only.
5. Approve a proposed decomposition; verify child tasks are created only then.
6. Close and reopen a completed child while it remains within retention; verify
   exactly one linked successor starts.
7. Advance a closed child beyond the configured retention window; verify one
   retirement notice and no further automatic monitoring.

Run backend tests with `cd backend && uv run pytest`, then run `task quality`.
