# Quickstart: Validated LLM Output

Run the focused workflow checks:

```bash
cd backend
uv run pytest tests/test_workflow_gate.py tests/test_workflow_gap_analysis.py \
  tests/test_workflow_driver.py tests/test_task_source_notifier.py -q
```

Verify the repository quality gate:

```bash
task quality
```

Expected results:

- A valid first response takes one request.
- Invalid required output is corrected within five total requests or fails.
- No empty PRD reaches approval or publication.
- Blank revision diff lines do not crash change-summary rendering.
