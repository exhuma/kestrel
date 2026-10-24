import { describe, it, expect } from 'vitest'
import { isStructured, renderMarkdown } from '../../src/lib/markdown'

describe('renderMarkdown', () => {
  it('renders headings, emphasis and lists as HTML', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** text\n\n- one\n- two')
    expect(html).toContain('<h1>Title</h1>')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>one</li>')
  })

  it('renders a fenced code block as pre/code', () => {
    const html = renderMarkdown('```\nconst x = 1\n```')
    expect(html).toContain('<pre>')
    expect(html).toContain('<code>')
    expect(html).toContain('const x = 1')
  })

  it('renders a markdown link as an anchor', () => {
    const html = renderMarkdown('[docs](https://example.com)')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('escapes raw HTML in the source instead of emitting live tags', () => {
    const html = renderMarkdown(
      '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>',
    )
    // The dangerous tags are escaped as text, never emitted live.
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })

  it('drops a javascript: link protocol', () => {
    const html = renderMarkdown('[click](javascript:alert(1))')
    // markdown-it's validateLink rejects the unsafe href, so no live link.
    expect(html).not.toContain('href="javascript:')
  })
})

describe('isStructured', () => {
  it('treats a JSON media type as structured', () => {
    expect(isStructured('application/json', 'anything')).toBe(true)
  })

  it('treats JSON content stored as plain text as structured', () => {
    expect(isStructured('text/plain', '{"questions": []}')).toBe(true)
  })

  it.each([
    ['text/markdown', '# PRD'],
    ['text/plain', 'Just prose.'],
    ['text/plain', '[link](https://example.com)'],
  ])('renders %s %j as Markdown', (mime, content) => {
    expect(isStructured(mime, content)).toBe(false)
  })
})
