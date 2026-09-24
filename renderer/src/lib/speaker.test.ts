import { describe, expect, it } from 'vitest'
import { activeFace } from './speaker'

describe('activeFace', () => {
  const timeline = [{ t: 0, faceId: 1 }, { t: 4, faceId: 0 }]
  it('picks the latest turn at or before t', () => {
    expect(activeFace(timeline, 0)).toBe(1)
    expect(activeFace(timeline, 3.99)).toBe(1)
    expect(activeFace(timeline, 4)).toBe(0)
  })
  it('handles an empty timeline', () => {
    expect(activeFace([], 2)).toBeNull()
  })
})
