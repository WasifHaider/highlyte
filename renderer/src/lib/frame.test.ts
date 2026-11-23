import { describe, expect, it } from 'vitest'
import fixture from '../__fixtures__/clip-spec.json'
import { OUT_H, OUT_W } from '../constants'
import { clipSpecSchema, type Layout } from '../schema'
import { framePlan, PANEL_H } from './frame'
import { resolveView } from './view'

const spec = clipSpecSchema.parse(fixture) // faces 0 and 1; shots: two [0,1] 0-4, one [1] 4-8
const noFaces = clipSpecSchema.parse({ ...fixture, reframe: { ...fixture.reframe, faces: [], speakerTimeline: [], shots: [] } })
const plan = (layout: Layout, t: number, s = spec) => framePlan(s, layout, resolveView(s, layout, t), t)
const shape = (layout: Layout, t: number, s = spec) => {
  const p = plan(layout, t, s)
  return { secondary: p.secondary !== null }
}

describe('framePlan keeps the same panels across camera cuts', () => {
  it('split has a secondary panel in both the two-shot and the close-up', () => {
    expect(shape('split', 1)).toEqual({ secondary: true })
    expect(shape('split', 5)).toEqual({ secondary: true })
  })
  it('hides the secondary panel during a close-up instead of removing it', () => {
    expect(plan('split', 1).secondary?.visible).toBe(true)
    expect(plan('split', 5).secondary?.visible).toBe(false)
  })
  it('follow and speaker never have a secondary panel', () => {
    for (const layout of ['follow', 'speaker'] as const) {
      expect(shape(layout, 1)).toEqual({ secondary: false })
      expect(shape(layout, 5)).toEqual({ secondary: false })
    }
  })
  it('fit uses the primary panel as a letterboxed full frame', () => {
    const p = plan('fit', 1)
    const boxH = (OUT_W * spec.source.height) / spec.source.width
    expect(p.fit).toBe(true)
    expect(p.primary).toEqual({
      crop: { x: 0, y: 0, w: spec.source.width, h: spec.source.height },
      boxH,
      top: (OUT_H - boxH) / 2,
      visible: true,
    })
    expect(p.secondary).toBeNull()
  })
  it('a clip with no faces falls back to fit with the primary panel', () => {
    expect(plan('follow', 1, noFaces).fit).toBe(true)
    expect(plan('split', 1, noFaces).secondary).toBeNull()
  })
})

describe('framePlan geometry', () => {
  it('split stacks two half-height panels during a two-shot', () => {
    const p = plan('split', 1)
    expect(p.primary.boxH).toBe(PANEL_H)
    expect(p.primary.top).toBe(0)
    expect(p.secondary?.boxH).toBe(PANEL_H)
    expect(p.secondary?.top).toBe(PANEL_H)
  })
  it('a close-up fills the whole frame', () => {
    const p = plan('follow', 5)
    expect(p.primary.boxH).toBe(OUT_H)
    expect(p.primary.top).toBe(0)
    expect(p.primary.crop.w / p.primary.crop.h).toBeCloseTo(OUT_W / OUT_H)
  })
})
