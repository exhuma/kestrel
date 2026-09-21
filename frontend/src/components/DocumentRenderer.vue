<script lang="ts">
import { defineComponent, h, type VNode } from 'vue'

interface InlineNode {
  type: 'text' | 'strong' | 'emphasis' | 'code' | 'link'
  text: string
  href?: string
}

interface ListItem {
  paragraphs: { content: InlineNode[] }[]
}

interface BlockNode {
  type:
    | 'heading'
    | 'paragraph'
    | 'code_block'
    | 'rule'
    | 'ordered_list'
    | 'bullet_list'
  level?: number
  content?: InlineNode[]
  language?: string | null
  text?: string
  start?: number | null
  items?: ListItem[]
}

interface DocumentPayload {
  version: number
  blocks: BlockNode[]
}

function parseDoc(json: string): DocumentPayload | null {
  try {
    const parsed = JSON.parse(json) as DocumentPayload
    if (parsed.version !== 1 || !Array.isArray(parsed.blocks)) return null
    return parsed
  } catch {
    return null
  }
}

function renderInline(nodes: InlineNode[]): VNode[] {
  return nodes.map((node, i) => {
    switch (node.type) {
      case 'strong':
        return h('strong', { key: i }, node.text)
      case 'emphasis':
        return h('em', { key: i }, node.text)
      case 'code':
        return h(
          'code',
          { key: i, class: 'document-renderer__inline-code' },
          node.text,
        )
      case 'link':
        if (node.href && /^https?:\/\//i.test(node.href)) {
          return h(
            'a',
            {
              key: i,
              href: node.href,
              target: '_blank',
              rel: 'noopener noreferrer',
            },
            node.text,
          )
        }
        return h('span', { key: i }, node.text)
      default:
        return h('span', { key: i }, node.text)
    }
  })
}

function renderListItems(items: ListItem[] | undefined): VNode[] {
  return (items ?? []).map((item, j) =>
    h(
      'li',
      { key: j },
      item.paragraphs.map((p, k) =>
        h('p', { key: k }, renderInline(p.content)),
      ),
    ),
  )
}

function renderHeading(block: BlockNode, i: number): VNode {
  const level = Math.min(Math.max(block.level ?? 1, 1), 6)
  return h(`h${level}`, { key: i }, renderInline(block.content ?? []))
}

function renderCodeBlock(block: BlockNode, i: number): VNode {
  return h(
    'pre',
    { key: i, class: 'document-renderer__code' },
    [
      h(
        'code',
        { 'data-lang': block.language ?? undefined },
        block.text ?? '',
      ),
    ],
  )
}

function renderBlock(block: BlockNode, i: number): VNode | null {
  switch (block.type) {
    case 'heading':
      return renderHeading(block, i)
    case 'paragraph':
      return h('p', { key: i }, renderInline(block.content ?? []))
    case 'code_block':
      return renderCodeBlock(block, i)
    case 'rule':
      return h('hr', { key: i })
    case 'ordered_list':
      return h(
        'ol',
        { key: i, start: block.start ?? 1 },
        renderListItems(block.items),
      )
    case 'bullet_list':
      return h('ul', { key: i }, renderListItems(block.items))
    default:
      return null
  }
}

export default defineComponent({
  name: 'DocumentRenderer',
  props: { json: { type: String, required: true } },
  setup(props) {
    return () => {
      const doc = parseDoc(props.json)
      if (!doc) {
        return h(
          'pre',
          { class: 'document-renderer__fallback' },
          props.json,
        )
      }
      const children = doc.blocks
        .map(renderBlock)
        .filter((v): v is VNode => v !== null)
      return h('div', { class: 'document-renderer' }, children)
    }
  },
})
</script>

<style scoped>
.document-renderer {
  max-width: 44rem;
}
.document-renderer :deep(h1),
.document-renderer :deep(h2),
.document-renderer :deep(h3),
.document-renderer :deep(h4),
.document-renderer :deep(h5),
.document-renderer :deep(h6) {
  margin-top: 1.2em;
  margin-bottom: 0.4em;
}
.document-renderer :deep(p) {
  margin-bottom: 0.6em;
}
.document-renderer__code {
  background: rgba(var(--v-theme-on-surface), 0.06);
  border-radius: 4px;
  padding: 0.8em;
  overflow-x: auto;
  font-size: 0.9em;
}
.document-renderer__inline-code {
  background: rgba(var(--v-theme-on-surface), 0.08);
  border-radius: 3px;
  padding: 0.1em 0.3em;
  font-size: 0.9em;
}
.document-renderer :deep(ul),
.document-renderer :deep(ol) {
  padding-left: 1.5em;
  margin-bottom: 0.6em;
}
.document-renderer__fallback {
  white-space: pre-wrap;
  font-size: 0.85em;
  color: rgb(var(--v-theme-on-surface-variant));
}
</style>
