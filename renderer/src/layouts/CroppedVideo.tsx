import { OffthreadVideo } from 'remotion'
import type { Crop } from '../lib/crop'

type Props = {
  src: string
  trimBefore: number
  srcW: number
  srcH: number
  crop: Crop
  boxW: number
  boxH: number
  top?: number
  visible?: boolean
  muted?: boolean
}

// Shows `crop` (source pixels) scaled to fill a boxW x boxH area placed
// `top` pixels from the top. The crop has the box's aspect ratio, so one
// scale factor fits both dimensions. A hidden panel stays mounted (see
// lib/frame.ts) so its video keeps playing in sync for when it reappears.
export const CroppedVideo: React.FC<Props> = ({ src, trimBefore, srcW, srcH, crop, boxW, boxH, top = 0, visible = true, muted }) => {
  const scale = boxW / crop.w
  return (
    <div style={{ position: 'absolute', left: 0, top, width: boxW, height: boxH, overflow: 'hidden', visibility: visible ? 'visible' : 'hidden' }}>
      <OffthreadVideo
        src={src}
        trimBefore={trimBefore}
        muted={muted}
        pauseWhenBuffering
        style={{
          position: 'absolute',
          width: srcW * scale,
          height: srcH * scale,
          left: -crop.x * scale,
          top: -crop.y * scale,
          maxWidth: 'none',
        }}
      />
    </div>
  )
}
