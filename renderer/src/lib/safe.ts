import { OUT_H, OUT_W } from '../constants'

// Where text stays clear of the platform's own overlay on a 9:16 short.
// TikTok, Reels and Shorts put the account name, description and music
// line along the bottom, a column of like/comment/share buttons down the
// right side, and tabs or a search bar across the top. These insets are a
// conservative common ground for all three (output pixels, 1080x1920).
export const SAFE = {
  top: 250,
  bottom: 480,
  left: 60,
  right: 140,
} as const

// The lowest a caption's bottom edge may sit, and the horizontal band it
// is centred in.
export const SAFE_BOTTOM_Y = OUT_H - SAFE.bottom
export const SAFE_WIDTH = OUT_W - SAFE.left - SAFE.right

export type CaptionBox =
  | { left: number; right: number; bottom: number }
  | { left: number; right: number; top: number; centered: true }

// Lower captions grow upward from the safe bottom edge, so a longer page
// never reaches the description area. Middle captions stay centred on the
// frame's midline (the seam between split panels).
export function captionBox(position: 'lower' | 'middle'): CaptionBox {
  if (position === 'middle') return { left: SAFE.left, right: SAFE.right, top: OUT_H / 2, centered: true }
  return { left: SAFE.left, right: SAFE.right, bottom: SAFE.bottom }
}
