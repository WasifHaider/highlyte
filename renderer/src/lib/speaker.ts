export function activeFace(timeline: { t: number; faceId: number }[], t: number): number | null {
  let id: number | null = null
  for (const turn of timeline) {
    if (turn.t <= t) id = turn.faceId
    else break
  }
  return id ?? timeline[0]?.faceId ?? null
}
