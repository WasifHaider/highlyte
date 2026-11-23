import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { fontFor, weightFor } from './fonts'
import { safeFor } from './lib/safe'

export const HOOK_S = 2.5

export const HookTitle: React.FC<{ text: string; font?: string; aspect?: string }> = ({ text, font, aspect }) => {
  const f = fontFor(font)
  const safe = safeFor(aspect)
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const endFrame = HOOK_S * fps
  if (frame > endFrame) return null
  const enter = spring({ frame, fps, config: { damping: 14 } })
  const exit = interpolate(frame, [endFrame - 8, endFrame], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return (
    <AbsoluteFill>
      <div style={{
        position: 'absolute', top: safe.top, left: safe.left + 20, right: safe.right, display: 'flex', justifyContent: 'center',
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
