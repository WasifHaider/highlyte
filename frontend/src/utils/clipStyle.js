export const LAYOUTS = [
  { value: 'follow', label: 'Follow face', minFaces: 1 },
  { value: 'speaker', label: 'Follow speaker', minFaces: 1 },
  { value: 'split', label: 'Split screen', minFaces: 2 },
  { value: 'fit', label: 'Fit with blur', minFaces: 0 },
]

export const ACCENT_PRESETS = ['#FFD400', '#FFFFFF', '#00E0B8', '#4DA3FF', '#FF5C8A', '#FF8A00', '#B388FF', '#14201F']

// Ids match FontId in backend/spec.py and renderer/src/fonts.ts.
export const FONTS = [
  { value: 'montserrat', label: 'Montserrat' },
  { value: 'poppins', label: 'Poppins' },
  { value: 'anton', label: 'Anton' },
  { value: 'bebas', label: 'Bebas Neue' },
]

export const PROGRESS_BARS = [
  { value: 'off', label: 'Off' },
  { value: 'top', label: 'Top edge' },
  { value: 'bottom', label: 'Bottom edge' },
]

export const ASPECTS = [
  { value: '9:16', label: '9:16 vertical' },
  { value: '4:5', label: '4:5 portrait' },
  { value: '1:1', label: '1:1 square' },
]

export const ZOOMS = [
  { value: 'off', label: 'Off' },
  { value: 'emphasis', label: 'Punch-in on key words' },
  { value: 'dynamic', label: 'Dynamic' },
]

export const TIGHTEN = [
  { value: 'off', label: 'Off' },
  { value: 'pauses', label: 'Cut long pauses' },
  { value: 'all', label: 'Cut pauses and um/uh' },
]

export const DEFAULT_BRAND_KIT = { accent: '#FFD400', font: 'montserrat', progressBar: 'off' }

export const PRESETS = [
  { value: 'karaoke', label: 'Karaoke highlight' },
  { value: 'pop', label: 'Pop word-by-word' },
  { value: 'clean', label: 'Clean subtitle' },
]

// With per-shot tracks a clip can have >= 2 faces overall (e.g. two
// close-ups) without ever showing two people at once, so split needs its
// own rule: only offer it when some shot actually splits the frame.
// Clips analysed before shots existed have no `shots` array and keep the
// old face-count rule.
export function layoutAllowed(layout, reframe) {
  const entry = LAYOUTS.find(l => l.value === layout)
  if (!entry) return false
  if (layout === 'split' && reframe?.shots?.length) {
    return reframe.shots.some(s => s.kind === 'two')
  }
  return (reframe?.faces?.length || 0) >= entry.minFaces
}
