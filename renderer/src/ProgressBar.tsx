import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion'

export const PROGRESS_BAR_H = 14

// A thin bar along the top or bottom edge that fills as the clip plays.
export const ProgressBar: React.FC<{ edge: 'top' | 'bottom'; color: string }> = ({ edge, color }) => {
  const frame = useCurrentFrame()
  const { durationInFrames } = useVideoConfig()
  const share = durationInFrames > 1 ? Math.min(1, frame / (durationInFrames - 1)) : 1
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <div style={{
        position: 'absolute', left: 0, [edge]: 0, height: PROGRESS_BAR_H, width: '100%',
        background: 'rgba(0,0,0,0.35)',
      }}>
        <div style={{ height: '100%', width: `${share * 100}%`, background: color }} />
      </div>
    </AbsoluteFill>
  )
}
