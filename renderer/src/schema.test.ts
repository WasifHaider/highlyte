import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/clip-spec.json'
import v2fixture from './__fixtures__/clip-spec-v2.json'
import { clipPropsSchema, clipSpecSchema, clipStyleSchema } from './schema'
import { durationInFrames } from './constants'

const style = {
  layout: 'speaker', captionPreset: 'karaoke', showHook: true,
  hookTitle: 'Hook', accent: '#FFD400', captionPosition: 'lower',
}

describe('schema', () => {
  it('accepts the Python-generated fixture spec', () => {
    const spec = clipSpecSchema.parse(fixture)
    expect(spec.reframe.faces).toHaveLength(2)
  })

  it('accepts full props', () => {
    expect(clipPropsSchema.parse({ spec: fixture, style }).style.layout).toBe('speaker')
  })

  it('rejects a bad accent and an unknown preset', () => {
    expect(clipStyleSchema.safeParse({ ...style, accent: 'red' }).success).toBe(false)
    expect(clipStyleSchema.safeParse({ ...style, captionPreset: 'neon' }).success).toBe(false)
  })

  it('rejects a hookTitle over 80 chars', () => {
    expect(clipStyleSchema.safeParse({ ...style, hookTitle: 'x'.repeat(81) }).success).toBe(false)
    expect(clipStyleSchema.safeParse({ ...style, hookTitle: 'x'.repeat(80) }).success).toBe(true)
  })

  it('computes duration in frames', () => {
    expect(durationInFrames({ start: 1, end: 9 })).toBe(240)
    expect(durationInFrames({ start: 1, end: 1 })).toBe(1)
  })

  it('reads shots from the fixture and defaults them for old specs', () => {
    expect(clipSpecSchema.parse(fixture).reframe.shots).toHaveLength(2)
    const old = structuredClone(fixture) as any
    delete old.reframe.shots
    expect(clipSpecSchema.parse(old).reframe.shots).toEqual([])
  })

  it('rejects an unknown shot kind', () => {
    const bad = structuredClone(fixture) as any
    bad.reframe.shots = [{ start: 0, end: 1, kind: 'three', faceIds: [] }]
    expect(clipSpecSchema.safeParse(bad).success).toBe(false)
  })
})

describe('spec v2', () => {
  it('parses the Python-generated v2 fixture', () => {
    const parsed = clipSpecSchema.parse(v2fixture)
    expect(parsed.version).toBe(2)
    expect(parsed.source.duration).toBe(12)
  })
})
