# Contract: Document ⇄ Jira ADF (Cloud)

Owned by `app/document_formats/adf.py`. Rendering is total over the closed
set; parsing is total over ADF (nothing raises; unknown structure degrades
to its text).

| Document | ADF out | ADF in |
| --- | --- | --- |
| `Paragraph` | `paragraph` | `paragraph` |
| `Heading(level)` | `heading{level}` | `heading` |
| `Text` | `text` | `text` without marks |
| `Strong` / `Emphasis` / `Code` | `text` + `strong` / `em` / `code` mark | same (outermost mark kept when several; documented loss) |
| `Link(href, value)` | `text` + `link{href}` | `text` + `link`; `inlineCard{url}` |
| `Mention(account_id, display_name)` | `mention{id, text:"@name"}` | `mention{id, text}` |
| `HardBreak` | `hardBreak` | `hardBreak` |
| `CodeBlock(language)` | `codeBlock{language}` | `codeBlock` |
| `BulletList` / `OrderedList(start)` | `bulletList` / `orderedList{order}` | same, nested |
| `Table(header, rows)` | `table` › `tableRow` › `tableHeader` / `tableCell` › `paragraph` | same (merged cells split; documented loss) |
| `Image(src, alt)` | `paragraph` with `Link(src, alt)` (external images need media upload; out of scope) | `mediaSingle`/`media` → `Image` when a URL is known, else `Text(alt)` |
| `Rule` | `rule` | `rule` |
| `Marker(name)` | `paragraph` › `text "[kestrel:{name}]"` + `code` mark | that exact paragraph → `Marker(name)` |
| — | — | `panel`, `expand`, `blockquote`, `nestedExpand`: children kept; `emoji` → its text; `status`, `date` → their text |

Round-trip property (tested): `parse_adf(render_adf(d)) == d` for every
document built from the closed set.
