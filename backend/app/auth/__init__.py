"""OIDC authentication and permission-based authorization.

Opt-in via ``Settings.auth_enabled`` (``KESTREL_AUTH_ENABLED``). Disabled
(the default), every dependency in this package short-circuits to
"everything allowed" and kestrel behaves exactly as it does without this
package.
"""
