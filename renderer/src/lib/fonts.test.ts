import { describe, expect, it } from 'vitest'
import { FONTS, fontFor, weightFor } from '../fonts'

describe('fonts', () => {
  it('falls back to Montserrat for a missing or unknown font', () => {
    expect(fontFor(undefined)).toBe(FONTS.montserrat)
    expect(fontFor('comic-sans')).toBe(FONTS.montserrat)
    expect(fontFor('anton')).toBe(FONTS.anton)
  })
  it('never asks a one-weight font for a weight it lacks', () => {
    expect(weightFor(FONTS.anton, 900)).toBe(400)
    expect(weightFor(FONTS.montserrat, 900)).toBe(900)
    expect(weightFor(FONTS.montserrat, 750)).toBe(700)
    expect(weightFor(FONTS.montserrat, 400)).toBe(700)
  })
})
