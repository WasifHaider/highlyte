import { describe, expect, it } from 'vitest'
import fixture from '../__fixtures__/clip-spec.json'
import { clipSpecSchema } from '../schema'
import { resolveView } from './view'

const spec = clipSpecSchema.parse(fixture) // faces 0 (x .30) and 1 (x .70); shots: two [0,1] 0-4, one [1] 4-8
const noShots = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, shots: [] } })

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
