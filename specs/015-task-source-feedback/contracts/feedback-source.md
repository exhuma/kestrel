# Contract: Feedback Source

`FeedbackSource` owns feedback enumeration and acknowledgement for one run.

```python
class FeedbackSource(Protocol):
    async def list_feedback(
        self, run: WorkflowRun, cursor: str | None
    ) -> list[Feedback]: ...

    async def acknowledge(self, feedback: Feedback) -> bool: ...

    async def reply(self, feedback: Feedback, body: str) -> bool: ...
```

`cursor` is opaque to callers. Sources may re-read a boundary; callers rely on
the feedback item's external identifier for durable deduplication.

When a reaction is unavailable, `reply` is the required acknowledgement
fallback. Any Kestrel-authored acknowledgement must be excluded from intake.
