"""Pluggable agent backends kestrel can dispatch to.

Each backend adapter translates a coordinator request into work on a
concrete system (the claude CLI or an opencode server) and reports progress
as :class:`app.models.CanonicalEvent`, which go to the server log.
"""
