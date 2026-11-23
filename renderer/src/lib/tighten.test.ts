import { describe, expect, it } from 'vitest'
import fixture from '../__fixtures__/clip-spec.json'
import { clipSpecSchema, type ClipSpec, type Word } from '../schema'
import { buildTimeline, cutsFor, KEEP_S, outputWords, toOutput, toSource } from './tighten'

const w = (text: string, start: number, end: number, emphasis = false): Word => ({ text, start, end, emphasis })

// A 10 s clip: speech 0.5-3, a 2 s pause, speech 5-6, an "um" at 6-6.4,
// speech 6.4-9.5.
const spec: ClipSpec = clipSpecSchema.parse({
  ...fixture,
  start: 0,
  end: 10,
  words: [w('one', 0.5, 1), w('two', 1, 3), w('three', 5, 6), w('um', 6, 6.4), w('four', 6.4, 9.5)],
  silences: [[3, 5], [9.6, 10]],
})

describe('cutsFor', () => {
  it('cuts nothing when off', () => {
    expect(cutsFor(spec, 'off', 10)).toEqual([])
    expect(cutsFor(spec, undefined, 10)).toEqual([])
  })
  it('cuts the middle of long pauses between words, keeping a little air', () => {
    expect(cutsFor(spec, 'pauses', 10)).toEqual([[3 + KEEP_S, 5 - KEEP_S]])
  })
  it('also cuts filler sounds in "all", but never an emphasised word', () => {
    expect(cutsFor(spec, 'all', 10)).toEqual([[3 + KEEP_S, 5 - KEEP_S], [6, 6.4]])
    const emphasised = { ...spec, words: spec.words.map(x => (x.text === 'um' ? { ...x, emphasis: true } : x)) }
    expect(cutsFor(emphasised, 'all', 10)).toEqual([[3 + KEEP_S, 5 - KEEP_S]])
  })
  it('works without measured pauses (older clips): fillers only', () => {
    const old = { ...spec, silences: [] }
    expect(cutsFor(old, 'pauses', 10)).toEqual([])
    expect(cutsFor(old, 'all', 10)).toEqual([[6, 6.4]])
  })
})

describe('timeline', () => {
  const tl = buildTimeline(spec, 'all')
  it('keeps the pieces between cuts and shortens the clip by the cut time', () => {
    expect(tl.tightened).toBe(true)
    expect(tl.pieces.map(p => [p.from, p.to])).toEqual([[0, 3.15], [4.85, 6], [6.4, 10]])
    expect(tl.length).toBeCloseTo(10 - 1.7 - 0.4)
  })
  it('maps output time to source time and back', () => {
    expect(toSource(tl, 1)).toBeCloseTo(1)
    expect(toSource(tl, 3.15)).toBeCloseTo(4.85)        // first frame after the pause cut
    expect(toOutput(tl, 6.4)).toBeCloseTo(3.15 + 1.15)
    expect(toOutput(tl, 4)).toBeNull()                    // inside a cut
    for (const t of [0.2, 2, 3.5, 5, 7]) expect(toOutput(tl, toSource(tl, t))).toBeCloseTo(t)
  })
  it('moves words onto the output timeline and drops the filler', () => {
    const out = outputWords(tl, spec.words)
    expect(out.map(x => x.text)).toEqual(['one', 'two', 'three', 'four'])
    expect(out[2].start).toBeCloseTo(3.15 + KEEP_S)   // the air kept before "three"
    expect(out[3].start).toBeCloseTo(4.3)
    expect(out[3].end).toBeCloseTo(tl.length - 0.5, 1)
  })
  it('is the whole clip, unchanged, when off', () => {
    const off = buildTimeline(spec, 'off')
    expect(off.tightened).toBe(false)
    expect(off.pieces).toEqual([{ from: 0, to: 10, outStart: 0 }])
    expect(off.length).toBe(10)
    expect(outputWords(off, spec.words)).toBe(spec.words)
  })
  it('never leaves a sliver of a piece between two cuts', () => {
    const tight = { ...spec, silences: [[3, 5], [5.1, 6]] as [number, number][], words: [w('a', 0.5, 3), w('b', 6, 9)] }
    const t = buildTimeline(tight, 'pauses')
    expect(t.pieces.every(p => p.to - p.from >= 0.3)).toBe(true)
  })
})

describe('clipFrames', () => {
  it('is the tightened length in frames, or the plain length when off', async () => {
    const { clipFrames } = await import('./tighten')
    const { FPS } = await import('../constants')
    expect(clipFrames(spec, 'off')).toBe(10 * FPS)
    expect(clipFrames(spec, 'all')).toBe(Math.round((10 - 1.7 - 0.4) * FPS))
  })
})
