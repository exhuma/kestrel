"""Pluggable agent backends kestrel can dispatch to.

Each backend adapter translates a coordinator request into work on a
concrete system (the claude CLI today; opencode and plain
OpenAI-compatible LLMs in later phases) and reports progress back as
:class:`app.models.CanonicalEvent` on the shared session registry.
"""
