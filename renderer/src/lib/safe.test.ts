import { describe, expect, it } from 'vitest'
import { OUT_H, OUT_W } from '../constants'
import { captionBox, SAFE, SAFE_BOTTOM_Y, SAFE_WIDTH } from './safe'

describe('safe area', () => {
  it('keeps clear of the bottom description band and the right button column', () => {
    expect(SAFE_BOTTOM_Y).toBe(OUT_H - SAFE.bottom)
    expect(SAFE_WIDTH).toBe(OUT_W - SAFE.left - SAFE.right)
    expect(SAFE.right).toBeGreaterThan(SAFE.left)
  })

  it('anchors lower captions by their bottom edge at the safe line', () => {
    expect(captionBox('lower')).toEqual({ left: SAFE.left, right: SAFE.right, bottom: SAFE.bottom })
  })

  it('centres middle captions on the frame midline', () => {
    expect(captionBox('middle')).toEqual({ left: SAFE.left, right: SAFE.right, top: OUT_H / 2, centered: true })
  })
})
