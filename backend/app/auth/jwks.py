"""Cached JWKS client, resolved from an IdP's OIDC discovery document."""
from __future__ import annotations

from functools import lru_cache

import httpx
import jwt


@lru_cache(maxsize=8)
def get_jwks_client(authority: str) -> jwt.PyJWKClient:
    """
    A cached ``PyJWKClient`` for ``authority``, resolved via discovery.

    ``PyJWKClient`` handles an unknown ``kid`` by refetching the JWKS
    itself, so no bespoke cache-invalidation logic is needed here — this
    cache only avoids re-resolving the discovery document (and
    constructing a new client) on every request for the same authority.

    :param authority: The IdP issuer base URL
        (``Settings.oidc_authority``).
    :returns: A ``PyJWKClient`` pointed at that authority's ``jwks_uri``.
    :raises httpx.HTTPStatusError: If the discovery document can't be
        fetched.
    :raises KeyError: If the discovery document has no ``jwks_uri``.
    """
    discovery_url = (
        f"{authority.rstrip('/')}/.well-known/openid-configuration"
    )
    with httpx.Client() as client:
        response = client.get(discovery_url)
        response.raise_for_status()
        doc = response.json()
    return jwt.PyJWKClient(doc["jwks_uri"])
