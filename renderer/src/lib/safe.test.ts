import { describe, expect, it } from 'vitest'
import { SIZES } from '../constants'
import { captionBox, SAFE, SAFE_BY_ASPECT, safeFor } from './safe'

describe('safe area', () => {
  it('keeps 9:16 text clear of the right button column and the bottom band', () => {
    expect(SAFE.right).toBeGreaterThan(SAFE.left)
    expect(SAFE.bottom).toBeGreaterThan(SAFE.top)
  })

  it('uses the 9:16 insets for a style with no aspect', () => {
    expect(safeFor(undefined)).toBe(SAFE)
    expect(safeFor('16:9')).toBe(SAFE)
    expect(safeFor('1:1')).toBe(SAFE_BY_ASPECT['1:1'])
  })

  it('anchors lower captions by their bottom edge at the safe line', () => {
    expect(captionBox('lower')).toEqual({ left: SAFE.left, right: SAFE.right, bottom: SAFE.bottom })
    const square = SAFE_BY_ASPECT['1:1']
    expect(captionBox('lower', '1:1', SIZES['1:1'])).toEqual({ left: square.left, right: square.right, bottom: square.bottom })
  })

  it('centres middle captions on the frame midline of each size', () => {
    expect(captionBox('middle')).toEqual({ left: SAFE.left, right: SAFE.right, top: SIZES['9:16'].height / 2, centered: true })
    expect(captionBox('middle', '4:5', SIZES['4:5'])).toMatchObject({ top: SIZES['4:5'].height / 2 })
  })
})
