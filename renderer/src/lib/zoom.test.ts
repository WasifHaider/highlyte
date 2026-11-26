import { describe, expect, it } from 'vitest'
import type { Word } from '../schema'
import { ALT_EVERY_S, ALT_SCALE, FALL_S, HOLD_S, PUNCH, PUSH, switchTimes, zoomAt, zoomCrop } from './zoom'

const word = (text: string, start: number, end: number, emphasis = false): Word => ({ text, start, end, emphasis })
// One word every 0.4 s for 12 s; the word at 2.0 s is emphasised.
const words: Word[] = Array.from({ length: 30 }, (_, i) => word(`w${i}`, i * 0.4, i * 0.4 + 0.35, i === 5))

describe('zoomAt', () => {
  it('never zooms when off or unset', () => {
    for (const t of [0, 2.1, 7]) {
      expect(zoomAt(t, words, 'off', 12)).toBe(1)
      expect(zoomAt(t, words, undefined, 12)).toBe(1)
    }
  })

  it('punches in on an emphasised word and eases back after it', () => {
    expect(zoomAt(1.9, words, 'emphasis', 12)).toBe(1)
    expect(zoomAt(2.0, words, 'emphasis', 12)).toBe(1)
    expect(zoomAt(2.2, words, 'emphasis', 12)).toBeCloseTo(PUNCH)
    expect(zoomAt(2.35 + HOLD_S, words, 'emphasis', 12)).toBeCloseTo(PUNCH)
    const mid = zoomAt(2.35 + HOLD_S + FALL_S / 2, words, 'emphasis', 12)
    expect(mid).toBeGreaterThan(1)
    expect(mid).toBeLessThan(PUNCH)
    expect(zoomAt(2.35 + HOLD_S + FALL_S + 0.01, words, 'emphasis', 12)).toBe(1)
  })

  it('dynamic switches framing on word starts and pushes in slowly', () => {
    const switches = switchTimes(words, 12)
    expect(switches[0]).toBeGreaterThanOrEqual(ALT_EVERY_S)
    expect(words.some(w => w.start === switches[0])).toBe(true)
    expect(zoomAt(0, words, 'dynamic', 12)).toBe(1)
    const before = zoomAt(switches[0] - 0.01, words, 'dynamic', 12)
    const after = zoomAt(switches[0], words, 'dynamic', 12)
    expect(before).toBeCloseTo(1 + PUSH, 2)
    expect(after).toBeCloseTo(ALT_SCALE)
  })
})

describe('zoomCrop', () => {
  const crop = { x: 600, y: 0, w: 607.5, h: 1080 }
  it('leaves the crop alone without zoom', () => {
    expect(zoomCrop(crop, 1, 0.3, 1920, 1080)).toBe(crop)
  })
  it('tightens around the same centre and the face height', () => {
    const z = zoomCrop(crop, 1.2, 0.5, 1920, 1080)
    expect(z.w).toBeCloseTo(crop.w / 1.2)
    expect(z.h).toBeCloseTo(crop.h / 1.2)
    expect(z.x + z.w / 2).toBeCloseTo(crop.x + crop.w / 2)
    expect(z.y + z.h / 2).toBeCloseTo(0.5 * 1080)
  })
  it('stays inside the source frame', () => {
    const z = zoomCrop({ x: 0, y: 0, w: 607.5, h: 1080 }, 1.2, 0.05, 1920, 1080)
    expect(z.x).toBeGreaterThanOrEqual(0)
    expect(z.y).toBe(0)
  })
})
