import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { fontFor, weightFor } from './fonts'
import { SAFE } from './lib/safe'

export const HOOK_S = 2.5

export const HookTitle: React.FC<{ text: string; font?: string }> = ({ text, font }) => {
  const f = fontFor(font)
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const endFrame = HOOK_S * fps
  if (frame > endFrame) return null
  const enter = spring({ frame, fps, config: { damping: 14 } })
  const exit = interpolate(frame, [endFrame - 8, endFrame], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill>
      <div style={{
        position: 'absolute', top: SAFE.top, left: SAFE.left + 20, right: SAFE.right, display: 'flex', justifyContent: 'center',
        opacity: exit, transform: `translateY(${(1 - enter) * -40}px)`,
      }}>
        <div style={{
          background: 'white', color: '#111', borderRadius: 24, padding: '22px 34px', fontFamily: f.fontFamily,
          fontWeight: weightFor(f, 800), fontSize: 60, lineHeight: 1.15, textAlign: 'center',
          boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
        }}>
          {text}
        </div>
      </div>
    </AbsoluteFill>
  )
}
