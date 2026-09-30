import MarkdownIt from 'markdown-it'

// One shared renderer for Markdown shown in the cockpit (feature 043).
// `html: false` makes markdown-it *escape* any raw HTML in the source, so
// agent-produced Markdown can never inject live markup — no separate
// sanitizer needed. markdown-it's built-in `validateLink` rejects
// `javascript:`/`vbscript:`/`data:` hrefs (FR-005).
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

// A link leaves the cockpit in a new tab and cannot reach its opener.
md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, idx, options)
}

/**
 * Render a Markdown string to safe HTML for display via `v-html`.
 *
 * Safe by construction (see the renderer config above): raw HTML in the
 * source is escaped and dangerous link protocols are dropped.
 */
export function renderMarkdown(text: string): string {
  return md.render(text)
}

/** Whether content is structured data to show as preformatted text rather
 *  than render: a JSON media type, or content that parses as a JSON object
 *  or array. Older artifacts were all stored as `text/plain`, so the
 *  content itself is checked too (feature 043, FR-005). */
export function isStructured(
  mimeType: string | null | undefined,
  content: string,
): boolean {
  if ((mimeType ?? '').split(';')[0].trim() === 'application/json') return true
  const trimmed = content.trim()
  if (!/^[[{]/.test(trimmed)) return false
  try {
    JSON.parse(trimmed)
    return true
  } catch {
    return false
  }
}
