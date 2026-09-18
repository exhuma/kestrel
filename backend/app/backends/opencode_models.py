"""Model helpers for the OpenCode backend."""

from __future__ import annotations


def split_model(model: str | None) -> dict[str, str] | None:
    """Parse a ``provider/model`` value into OpenCode's model object."""
    if not model or "/" not in model:
        return None
    provider, _, model_id = model.partition("/")
    return {"providerID": provider, "modelID": model_id}
