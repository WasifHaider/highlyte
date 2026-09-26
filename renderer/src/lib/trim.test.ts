import { describe, expect, it } from 'vitest'
import type { ClipSpec, Word } from '../schema'
import { canTrim, nudge, sentence } from './trim'

// Three sentences in a 40 s file. Word i of a sentence starting at `from`
// runs from + 0.9*i to from + 0.9*i + 0.8, so S1 is 1.0-9.9, S2 11.0-19.9,
// S3 21.0-29.9. The clip is S2 cut the snap.py way: 10.78-20.3.
function words(): Word[] {
  const out: Word[] = []
  for (const [from, n] of [[1, 'a'], [11, 'b'], [21, 'c']] as const) {
    for (let i = 0; i < 10; i++) {
      const start = from + i * 0.9
      out.push({ text: i === 9 ? `${n}${i}.` : `${n}${i}`, start, end: start + 0.8 })
    }
  }
  return out
}

function spec(over: Partial<ClipSpec> = {}): ClipSpec {
  return {
    version: 2, clipId: 'x-0', source: { url: '', width: 1920, height: 1080, fps: 30, duration: 40 },
    start: 10.78, end: 20.3, words: words(), wordsApprox: false, hookTitle: null, viralityScore: 5,
    reframe: { auto: 'fit', faces: [], speakerTimeline: [], shots: [] },
    ...over,
  } as ClipSpec
}

describe('canTrim', () => {
  it('needs a v2 spec with a file duration', () => {
    expect(canTrim(spec())).toBe(true)
    expect(canTrim(spec({ version: 1 } as Partial<ClipSpec>))).toBe(false)
    expect(nudge(spec({ version: 1 } as Partial<ClipSpec>), 'start', 0.5)).toEqual({ ok: false, reason: 'Re-run the video to trim this clip.' })
  })
})

describe('nudge', () => {
  it('moves one edge by the step', () => {
    expect(nudge(spec(), 'end', 0.5)).toEqual({ ok: true, bounds: { start: 10.78, end: 20.8 } })
    expect(nudge(spec(), 'start', -0.5)).toEqual({ ok: true, bounds: { start: 10.28, end: 20.3 } })
  })
  it('refuses a clip under 8 s', () => {
    expect(nudge(spec({ start: 11, end: 19 }), 'start', 0.5)).toEqual({ ok: false, reason: 'Clips must be at least 8 s.' })
  })
  it('stops at the file edge', () => {
    expect(nudge(spec({ start: 0, end: 10 }), 'start', -0.5)).toEqual({ ok: false, reason: 'That is the edge of the spare video.' })
  })
})

describe('sentence', () => {
  it('includes the next sentence', () => {
    // S3's last word ends 29.9; +0.4 air, nothing after it
    expect(sentence(spec(), 'end', 1)).toEqual({ ok: true, bounds: { start: 10.78, end: 30.3 } })
  })
  it('includes the previous sentence', () => {
    // S1's first word starts 1.0; -0.22 lead
    expect(sentence(spec(), 'start', -1)).toEqual({ ok: true, bounds: { start: 0.78, end: 20.3 } })
  })
  it('drops the last sentence', () => {
    expect(sentence(spec({ start: 10.78, end: 30.3 }), 'end', -1)).toEqual({ ok: true, bounds: { start: 10.78, end: 20.3 } })
  })
  it('refuses when there is none', () => {
    expect(sentence(spec({ start: 0.78, end: 30.3 }), 'start', -1)).toEqual({ ok: false, reason: 'No earlier sentence in the spare video.' })
  })
})
