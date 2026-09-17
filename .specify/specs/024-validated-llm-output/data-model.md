# Data Model: Validated LLM Output

## Required Output Result

- `value`: The typed, validated artifact returned to the workflow.
- `error`: A concise reason explaining why one model response was unusable.

## Attempt Budget

- Maximum total requests: 5.
- Attempt 1: the original artifact prompt.
- Attempts 2-5: correction prompts that contain the validation reason and the
  prior invalid response.

No persistent entity is added. The budget exists only during the active turn.
