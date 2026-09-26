import { describe, expect, it } from 'vitest'
import type { Word } from '../schema'
import { captionLines, editLine, lineText } from './edit'

const w = (text: string, start: number, end: number, emphasis = false): Word => ({ text, start, end, emphasis })
// Two lines: a sentence ending in "." and a second sentence.
const words: Word[] = [
  w('hum', 0.0, 0.3), w('YouTube', 0.3, 0.8, true), w('pe', 0.8, 1.0), w('hain.', 1.0, 1.4),
  w('bohat', 1.5, 1.9), w('acha', 1.9, 2.3), w('laga.', 2.3, 2.8),
]

describe('captionLines', () => {
  it('groups words into lines with their first-word index', () => {
    const lines = captionLines(words)
    expect(lines.map(lineText)).toEqual(['hum YouTube pe hain.', 'bohat acha laga.'])
    expect(lines.map(l => [l.index, l.from, l.start, l.end])).toEqual([[0, 0, 0.0, 1.4], [1, 4, 1.5, 2.8]])
  })
  it('caps a line at 14 words', () => {
    const many = Array.from({ length: 20 }, (_, i) => w(`w${i}`, i * 0.3, i * 0.3 + 0.25))
    expect(captionLines(many)[0].words).toHaveLength(14)
  })
})

describe('editLine', () => {
  const [first, second] = captionLines(words)

  it('same word count keeps timings and emphasis', () => {
    const out = editLine(words, first, 'hum YouTube par hain.')
    expect(out.slice(0, 4)).toEqual([w('hum', 0, 0.3), w('YouTube', 0.3, 0.8, true), w('par', 0.8, 1.0), w('hain.', 1.0, 1.4)])
    expect(out.slice(4)).toEqual(words.slice(4))
  })

  it('different word count spreads the line span by word length', () => {
    const out = editLine(words, second, 'bohat zyada acha laga.')
    const edited = out.slice(4)
    expect(edited.map(x => x.text)).toEqual(['bohat', 'zyada', 'acha', 'laga.'])
    expect(edited[0].start).toBe(1.5)
    expect(edited[edited.length - 1].end).toBe(2.8)
    for (let i = 1; i < edited.length; i++) expect(edited[i].start).toBeCloseTo(edited[i - 1].end, 3)
    // "zyada" (6 incl. space) gets more time than "acha" (5)
    expect(edited[1].end - edited[1].start).toBeGreaterThan(edited[2].end - edited[2].start)
    expect(out.slice(0, 4)).toEqual(words.slice(0, 4))
  })

  it('carries emphasis to a matching word when the count changes', () => {
    const out = editLine(words, first, 'hum YouTube pe sab hain.')
    expect(out.find(x => x.text === 'YouTube')?.emphasis).toBe(true)
    expect(out.find(x => x.text === 'sab')?.emphasis).toBe(false)
  })

  it('empty text removes the line', () => {
    const out = editLine(words, first, '   ')
    expect(out).toEqual(words.slice(4))
  })

  it('clamps retimed starts to not land after the next line (overlapping Whisper words)', () => {
    // The next line's first word starts before this line's own end -
    // Whisper sometimes emits overlapping word times. Starts must stay
    // non-decreasing across the boundary into the next (unedited) line.
    const overlapping: Word[] = [
      w('hum', 0.0, 0.3), w('YouTube', 0.3, 0.8, true), w('pe', 0.8, 1.0), w('hain.', 1.0, 1.4),
      w('bohat', 0.5, 1.9), w('acha', 1.9, 2.3), w('laga.', 2.3, 2.8),
    ]
    const [firstLine] = captionLines(overlapping)
    const out = editLine(overlapping, firstLine, 'hum YouTube par sab hain.')
    const boundary = [...out.slice(0, 5), overlapping[4]]
    for (let i = 1; i < boundary.length; i++) expect(boundary[i].start).toBeGreaterThanOrEqual(boundary[i - 1].start)
    for (const word of out.slice(0, 5)) expect(word.end).toBeGreaterThanOrEqual(word.start)
  })
})
