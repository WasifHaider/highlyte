import { describe, expect, it } from 'vitest'
import v1 from '../__fixtures__/clip-spec.json'
import v2 from '../__fixtures__/clip-spec-v2.json'
import { clipSpecSchema } from '../schema'
import { fileDuration, toClipTime } from './timeline'

const spec1 = clipSpecSchema.parse(v1)
const spec2 = clipSpecSchema.parse(v2)

describe('toClipTime', () => {
  it('leaves v1 specs alone', () => {
    expect(toClipTime(spec1)).toBe(spec1)
  })
  it('matches the v1 fixture once a v2 spec is converted', () => {
    const clip = toClipTime(spec2)
    expect(clip.words.map(w => w.text)).toEqual(spec1.words.map(w => w.text))
    expect(clip.words[0].start).toBeCloseTo(spec1.words[0].start, 3)
    expect(clip.reframe.speakerTimeline).toEqual(spec1.reframe.speakerTimeline)
    expect(clip.reframe.shots).toEqual(spec1.reframe.shots)
    expect(clip.reframe.faces[0].track.find(p => Math.abs(p.t) < 1e-9)?.cx).toBe(0.3)
  })
  it('drops words outside the clip', () => {
    const texts = toClipTime(spec2).words.map(w => w.text)
    expect(texts).not.toContain('Pehle.')
    expect(texts).not.toContain('Baad.')
  })
})

describe('fileDuration', () => {
  it('is known only for v2', () => {
    expect(fileDuration(spec2)).toBe(12)
    expect(fileDuration(spec1)).toBeNull()
  })
})
