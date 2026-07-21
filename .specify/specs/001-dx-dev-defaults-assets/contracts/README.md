# Contracts: DX polish — zero-config dev servers & lighter frontend assets

**No external or API contracts change in this feature.**

- **HTTP API**: no endpoints added, removed, or altered. Backend code is
  untouched.
- **Type contract** (`frontend/src/types/` ↔ backend JSON shapes): unaffected —
  no business types change. Constitution Principle I is not engaged.
- **CLI / config surface**: no new environment variables or settings keys. The
  canonical dev port (8000) and the `API_BASE` default are already in place;
  only `frontend/.env.example` guidance is adjusted (documentation, not a new
  contract).

The observable surface this feature touches is internal frontend wiring (icon
delivery, dev-server ergonomics) and the production build output, none of which
constitute a consumer-facing contract. This file exists to record that the
`contracts/` step was considered and is intentionally empty.
