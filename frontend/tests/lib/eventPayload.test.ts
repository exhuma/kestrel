import { describe, it, expect } from 'vitest'
import { parsePayload } from '../../src/lib/eventPayload'

describe('parsePayload', () => {
  it.each(['', '{}', 'not json', '[]', '"x"', 'null', '{"detail": "  "}'])(
    'has nothing to show for %j',
    (raw) => {
      expect(parsePayload(raw)).toBeNull()
    },
  )

  it('reads a detail as a sentence', () => {
    expect(parsePayload('{"detail": "the turn failed"}')).toEqual({
      kind: 'detail',
      detail: 'the turn failed',
      fields: [],
    })
  })

  it('keeps other fields as labelled values', () => {
    expect(parsePayload('{"round": 2, "reason": "cap"}')).toEqual({
      kind: 'fields',
      fields: [
        ['round', '2'],
        ['reason', 'cap'],
      ],
    })
  })

  it('shows a non-string detail as a labelled value', () => {
    expect(parsePayload('{"detail": 3}')).toEqual({
      kind: 'fields',
      fields: [['detail', '3']],
    })
  })
})
