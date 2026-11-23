import { loadFont as loadAnton } from '@remotion/google-fonts/Anton'
import { loadFont as loadBebas } from '@remotion/google-fonts/BebasNeue'
import { loadFont as loadMontserrat } from '@remotion/google-fonts/Montserrat'
import { loadFont as loadPoppins } from '@remotion/google-fonts/Poppins'

// Loaded through Remotion so the browser preview and Lambda render wait
// for the same font before drawing a frame. Ids match FontId in
// backend/spec.py. Anton and Bebas Neue come in one weight only, so
// `weights` says which a caption can ask for without the browser faking
// bold.
export type FontSpec = { fontFamily: string; weights: number[] }

const LATIN = { subsets: ['latin' as const] }

export const FONTS = {
  montserrat: { fontFamily: loadMontserrat('normal', { weights: ['700', '800', '900'], ...LATIN }).fontFamily, weights: [700, 800, 900] },
  poppins: { fontFamily: loadPoppins('normal', { weights: ['700', '800', '900'], ...LATIN }).fontFamily, weights: [700, 800, 900] },
  anton: { fontFamily: loadAnton('normal', { weights: ['400'], ...LATIN }).fontFamily, weights: [400] },
  bebas: { fontFamily: loadBebas('normal', { weights: ['400'], ...LATIN }).fontFamily, weights: [400] },
} satisfies Record<string, FontSpec>

export type FontId = keyof typeof FONTS

// The default font, kept for code that has no style at hand.
export const { fontFamily } = FONTS.montserrat

// A style saved before fonts could be chosen has no font: Montserrat.
export const fontFor = (id: string | undefined): FontSpec => FONTS[id as FontId] ?? FONTS.montserrat

// The heaviest weight the font has that is no heavier than `want`, or its
// lightest one.
export function weightFor(font: FontSpec, want: number): number {
  const fit = font.weights.filter(w => w <= want)
  return fit.length ? Math.max(...fit) : Math.min(...font.weights)
}
