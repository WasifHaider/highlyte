import { describe, expect, it } from 'vitest'
import { cropWindow } from './crop'

describe('cropWindow', () => {
  it('makes a 9:16 window centred on the face', () => {
    const c = cropWindow(1920, 1080, 0.5, 1080 / 1920)
    expect(c.w).toBeCloseTo(607.5)
    expect(c.h).toBe(1080)
    expect(c.x).toBeCloseTo(656.25)
    expect(c.y).toBe(0)
  })
  it('clamps to the frame edges', () => {
    expect(cropWindow(1920, 1080, 0.0, 1080 / 1920).x).toBe(0)
    expect(cropWindow(1920, 1080, 1.0, 1080 / 1920).x).toBeCloseTo(1920 - 607.5)
  })
  it('shrinks height when the window would be wider than the source', () => {
    const c = cropWindow(1000, 1000, 0.5, 2)
    expect(c.w).toBe(1000)
    expect(c.h).toBe(500)
    expect(c.y).toBe(250)
  })
})
