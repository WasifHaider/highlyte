import { describe, expect, it } from 'vitest'
import fixture from './__fixtures__/clip-spec.json'
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

  it('computes duration in frames', () => {
    expect(durationInFrames({ start: 1, end: 9 })).toBe(240)
    expect(durationInFrames({ start: 1, end: 1 })).toBe(1)
  })
})
