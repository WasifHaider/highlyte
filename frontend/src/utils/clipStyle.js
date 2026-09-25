export const LAYOUTS = [
  { value: 'follow', label: 'Follow face', minFaces: 1 },
  { value: 'speaker', label: 'Follow speaker', minFaces: 1 },
  { value: 'split', label: 'Split screen', minFaces: 2 },
  { value: 'fit', label: 'Fit with blur', minFaces: 0 },
]

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
