"""Board domain: durable work cards, dependencies, claims, and policy.

Replaces the fixed six-step workflow driver (feature 026). See
``specs/026-autonomous-work-board/`` for the full design. This package is
layered like the rest of the service tier: ``models``/``policy`` are pure
and dependency-free; ``service``/``quarantine``/``dispatch`` depend on the
persistence layer (``app.persistence.board_store`` and friends) but not on
routers or adapters.
"""
