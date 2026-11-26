import { SIZES, type AspectId, type Size } from '../constants'

export type Insets = { top: number; bottom: number; left: number; right: number }

// Where text stays clear of the platform's own overlay (output pixels).
// 9:16 shorts (TikTok, Reels, Shorts) put the account name, description and
// music line along the bottom, a column of like/comment/share buttons down
// the right side, and tabs or a search bar across the top; these insets are
// a conservative common ground for all three. 4:5 and 1:1 are feed posts,
// where the app's own UI sits outside the frame, so they only keep text off
// the edges.
export const SAFE_BY_ASPECT: Record<AspectId, Insets> = {
  '9:16': { top: 250, bottom: 480, left: 60, right: 140 },
  '4:5': { top: 80, bottom: 120, left: 60, right: 60 },
  '1:1': { top: 60, bottom: 90, left: 60, right: 60 },
}

// The 9:16 insets, for code that has no style at hand.
export const SAFE = SAFE_BY_ASPECT['9:16']

export const safeFor = (aspect: string | undefined): Insets => SAFE_BY_ASPECT[aspect as AspectId] ?? SAFE

export type CaptionBox =
  | { left: number; right: number; bottom: number }
  | { left: number; right: number; top: number; centered: true }

// Lower captions grow upward from the safe bottom edge, so a longer page
// never reaches the description area. Middle captions stay centred on the
// frame's midline (the seam between split panels).
export function captionBox(position: 'lower' | 'middle', aspect?: string, size: Size = SIZES['9:16']): CaptionBox {
  const safe = safeFor(aspect)
  if (position === 'middle') return { left: safe.left, right: safe.right, top: size.height / 2, centered: true }
  return { left: safe.left, right: safe.right, bottom: safe.bottom }
}
