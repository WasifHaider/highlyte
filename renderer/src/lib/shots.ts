import type { Shot } from '../schema'

export function activeShot(shots: Shot[] | undefined, t: number): Shot | null {
  if (!shots) return null
  let current: Shot | null = null
  for (const shot of shots) {
    if (shot.start <= t) current = shot
    else break
  }
  return current ?? shots[0] ?? null
}
