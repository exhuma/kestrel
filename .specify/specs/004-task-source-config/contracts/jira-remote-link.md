# Contract: Jira repository resolution from a web/remote link

Broadens how a Jira RFC's target repository is discovered. The custom field
becomes optional; a title-matched web/remote link is a fallback.

## Resolution order (per RFC)

1. **Custom field** — when the entry's `repo_field` is configured, read it. A
   non-empty `owner/name[@base]` resolves the repository (existing behaviour,
   unchanged).
2. **Web/remote link fallback** — when the field is absent/empty, fetch the
   issue's remote links and select the first whose title **case-insensitively
   equals** the entry's `repo_link_text` (default `"Repository"`). Parse its URL
   into `owner/name`.
3. **Unresolved** — neither yields a repo ⇒ the RFC is reported unresolved (no
   run started; live loop comments as today; dry-run marks it unresolved).

## Client call

`GET /rest/api/2/issue/{key}/remotelink` → a JSON array of entries shaped like:

```json
[ { "relationship": "mentioned in", "object": { "url": "https://github.com/acme/gateway", "title": "Repository" } } ]
```

The client returns the raw list; title-matching and URL parsing happen in the
poll service (keeps the client thin).

## URL → `owner/name` parsing (`_repo_from_url`)

- Parse `urllib.parse.urlparse(url).path`; split on `/`, dropping empties.
- Trim a trailing `.git`.
- For GitLab deep-links, truncate the path at the `/-/` segment (everything
  before `-`), so `.../group/sub/proj/-/issues/3` → `group/sub/proj`.
- Result:
  - `https://github.com/acme/gateway` → `acme/gateway`
  - `https://gitlab.host/group/sub/proj` → `group/sub/proj`
  - `https://github.com/acme/gateway.git` → `acme/gateway`
- A URL whose path has fewer than two segments, or is otherwise not an
  `owner/name` shape, returns `None` (**treated as unresolved, never a crash** —
  spec Edge Case).

## Notes

- Matching is by link **title**, not URL host — the operator controls it via the
  entry's `repo_link_text`.
- Base-branch (`@base`) only comes from the custom-field form; a web link
  resolves the repo and the base branch defaults to the code host's default
  branch (existing `_probe` behaviour).
