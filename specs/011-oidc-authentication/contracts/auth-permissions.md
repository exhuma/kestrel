# Contract: `GET /api/auth/permissions`

The single source of truth the frontend uses to decide which mutating
controls to show as enabled — computed once, backend-side, so the frontend
never re-implements role→permission mapping (constitution Principle II).

## Request

No parameters. Requires a valid `Authorization: Bearer <token>` header when
`auth_enabled=True`. When `auth_enabled=False`, this endpoint still exists
and responds (no auth required) with the "everything allowed" shape below,
so the frontend's `usePermissions` composable has one code path regardless
of the setting.

## Response — 200 OK (auth enabled, valid token)

```json
{
  "sub": "a1b2c3d4-...",
  "email": "operator@example.com",
  "preferred_username": "operator",
  "permissions": [
    "sessions:write",
    "workflows:approve",
    "workflows:respond"
  ]
}
```

## Response — 200 OK (auth disabled)

```json
{
  "sub": null,
  "email": null,
  "preferred_username": null,
  "permissions": ["*"]
}
```

`"*"` is a sentinel meaning "every permission" — `usePermissions().can(...)`
treats its presence as always-true rather than the frontend needing to know
the full permission vocabulary itself.

## Response — 401 Unauthorized (auth enabled, missing/invalid token)

Standard `get_current_claims` rejection — same shape as any other
protected endpoint's 401 (see `permission-gated-endpoints.md`).

## Test cases

- Auth disabled → 200 with the sentinel shape above, no `Authorization`
  header needed.
- Auth enabled, valid token, user has 3 mapped permissions → 200 listing
  exactly those 3, `sub`/`email`/`preferred_username` populated from claims.
- Auth enabled, valid token, user has zero mapped roles → 200 with
  `"permissions": []`, not an error (spec FR-009 / edge case: view-only is a
  valid state, not a failure).
- Auth enabled, expired/invalid/tampered token → 401.
