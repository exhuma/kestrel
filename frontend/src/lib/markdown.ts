import MarkdownIt from 'markdown-it'

// One shared renderer for every prose deliverable (refined issue, plan).
// `html: false` (the default, set explicitly for intent) makes markdown-it
// *escape* any raw HTML in the source, so agent-produced markdown can never
// inject live markup — no separate sanitizer needed. markdown-it's built-in
// `validateLink` additionally rejects `javascript:`/`vbscript:`/`data:` hrefs.
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

/**
 * Render a markdown string to sanitized HTML for display via `v-html`.
 *
 * Safe by construction (see the renderer config above): raw HTML in the
 * source is escaped and dangerous link protocols are dropped.
 */
export function renderMarkdown(text: string): string {
  return md.render(text)
}
