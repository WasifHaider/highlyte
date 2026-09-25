import { describe, expect, it } from 'vitest'
import fixture from '../__fixtures__/clip-spec.json'
import { clipSpecSchema, type ClipStyle } from '../schema'
import { captionPositionAt, resolveView } from './view'

const spec = clipSpecSchema.parse(fixture) // faces 0 (x .30) and 1 (x .70); shots: two [0,1] 0-4, one [1] 4-8
const noShots = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, shots: [] } })

const style = (layout: ClipStyle['layout'], captionPosition: ClipStyle['captionPosition'] = 'lower'): ClipStyle => ({
  layout,
  captionPreset: 'clean',
  showHook: false,
  hookTitle: null,
  accent: '#ffffff',
  captionPosition,
})

describe('resolveView with shots', () => {
  it('splits a two-person shot, left face on top', () => {
    expect(resolveView(spec, 'split', 1)).toEqual({ kind: 'two', topId: 0, bottomId: 1 })
  })
  it('shows one person full-frame in a close-up even when split is chosen', () => {
    expect(resolveView(spec, 'split', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('follow uses the shot main face', () => {
    expect(resolveView(spec, 'follow', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('speaker falls back to the shot face when the speaker is not in the shot', () => {
    // fixture timeline: face 0 from 0 s, face 1 from 4 s
    expect(resolveView(spec, 'speaker', 1)).toEqual({ kind: 'one', faceId: 0 })
    expect(resolveView(spec, 'speaker', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
  it('a shot without faces fits', () => {
    const none = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, shots: [{ start: 0, end: 8, kind: 'none', faceIds: [] }] } })
    expect(resolveView(none, 'split', 1)).toEqual({ kind: 'fit' })
  })
  it('fit stays fit', () => {
    expect(resolveView(spec, 'fit', 1)).toEqual({ kind: 'fit' })
  })
})

describe('resolveView without shots (clips analysed before shots existed)', () => {
  it('split orders the first two faces by their first position', () => {
    expect(resolveView(noShots, 'split', 1)).toEqual({ kind: 'two', topId: 0, bottomId: 1 })
  })
  it('follow uses the most present face', () => {
    expect(resolveView(noShots, 'follow', 1)).toEqual({ kind: 'one', faceId: 0 })
  })
  it('speaker follows the timeline', () => {
    expect(resolveView(noShots, 'speaker', 5)).toEqual({ kind: 'one', faceId: 1 })
  })
})

describe('captionPositionAt', () => {
  it('splits captions to the seam during a two-person shot', () => {
    expect(captionPositionAt(spec, style('split'), 1)).toBe('middle')
  })
  it('keeps captions off the speaker during a close-up within a split clip', () => {
    expect(captionPositionAt(spec, style('split'), 5)).toBe('lower')
  })
  it('uses the configured caption position for non-split layouts', () => {
    expect(captionPositionAt(spec, style('follow', 'middle'), 5)).toBe('middle')
  })
  it('splits captions for the whole clip when there are no shots', () => {
    expect(captionPositionAt(noShots, style('split'), 1)).toBe('middle')
  })
})
