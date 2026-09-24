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

export function layoutAllowed(layout, faceCount) {
  const entry = LAYOUTS.find(l => l.value === layout)
  return !!entry && faceCount >= entry.minFaces
}
