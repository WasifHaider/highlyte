import { describe, expect, it } from 'vitest'
import { activeShot } from './shots'

const shots = [
  { start: 0, end: 4, kind: 'two' as const, faceIds: [0, 1] },
  { start: 4, end: 8, kind: 'one' as const, faceIds: [2] },
]

describe('activeShot', () => {
  it('picks the latest shot starting at or before t', () => {
    expect(activeShot(shots, 0)?.kind).toBe('two')
    expect(activeShot(shots, 3.99)?.kind).toBe('two')
    expect(activeShot(shots, 4)?.kind).toBe('one')
    expect(activeShot(shots, 99)?.kind).toBe('one')
  })
  it('handles no shots', () => {
    expect(activeShot([], 1)).toBeNull()
  })
  it('handles undefined shots (clips analysed before shots existed, unparsed)', () => {
    expect(activeShot(undefined, 1)).toBeNull()
  })
})
