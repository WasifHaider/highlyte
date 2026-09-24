import { describe, expect, it } from 'vitest'
import { sampleTrack } from './track'

const pt = (t: number, cx: number) => ({ t, cx, cy: 0.4, w: 0.1, h: 0.2 })

describe('sampleTrack', () => {
  it('returns centre for an empty track', () => {
    expect(sampleTrack([], 3)).toEqual({ cx: 0.5, cy: 0.5 })
  })
  it('interpolates between close samples', () => {
    expect(sampleTrack([pt(0, 0.2), pt(1, 0.4)], 0.5).cx).toBeCloseTo(0.3)
  })
  it('holds the last position during a short gap, then eases to centre', () => {
    const track = [pt(0, 0.2), pt(10, 0.8)]
    expect(sampleTrack(track, 1.5).cx).toBeCloseTo(0.2)
    expect(sampleTrack(track, 2.25).cx).toBeCloseTo(0.35)
    expect(sampleTrack(track, 5).cx).toBeCloseTo(0.5)
    expect(sampleTrack(track, 10).cx).toBeCloseTo(0.8)
  })
  it('uses the first sample shortly before the track starts', () => {
    expect(sampleTrack([pt(1, 0.3)], 0).cx).toBeCloseTo(0.3)
    expect(sampleTrack([pt(5, 0.3)], 0).cx).toBeCloseTo(0.5)
  })
})
