# Versioning & releases

Releases use **CalVer**: `vYYYY.M.D` with an optional pre-release suffix
(`-alpha.N`, `-beta.N`, `-rc.N`) — e.g. `v2026.7.3-alpha.1`. Pushing such a
tag builds and publishes the image to `ghcr.io/exhuma/kestrel`.

## Channels

Each release publishes the immutable full version (e.g. `2026.7.3-alpha.1`)
plus **moving channel pointers** that cascade by maturity — there is
deliberately **no `latest`** tag:

| Release kind | Channels advanced |
| --- | --- |
| `-alpha.N` | `alpha` |
| `-beta.N` | `beta`, `alpha` |
| `-rc.N` | `rc` |
| _(stable, no suffix)_ | `stable`, `beta`, `alpha` |

Track the alpha channel with `ghcr.io/exhuma/kestrel:alpha`.

## Cutting a release

1. Bump both manifests so they match the intended tag (kept in sync by
   `scripts/check_version_sync.sh`):
   - `backend/pyproject.toml` — PEP 440 form (e.g. `2026.7.3a1`).
   - `frontend/package.json` — npm form (e.g. `2026.7.3-alpha.1`).
2. Commit, then tag and push:

   ```bash
   git tag v2026.7.3-alpha.1
   git push --tags
   ```

Pushing the tag triggers `.github/workflows/release.yml`, which:

- runs the full test suite (`testing.yml`);
- verifies the manifests match the tag (`check_version_sync.sh`);
- derives the channel tags (`derive_channels.sh`);
- builds and pushes the image to GHCR (with `KESTREL_VERSION` baked in);
- creates a GitHub Release (marked pre-release for alpha/beta/rc).

## Verifying the running version

The baked-in `KESTREL_VERSION` is reported by `GET /healthz`:

```bash
curl -s http://localhost:8000/healthz
# {"status":"ok","version":"2026.7.3-alpha.1"}
```
