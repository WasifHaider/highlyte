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
  muted?: boolean
}

// Shows `crop` (source pixels) scaled to fill a boxW x boxH area. The crop
// has the box's aspect ratio, so one scale factor fits both dimensions.
export const CroppedVideo: React.FC<Props> = ({ src, trimBefore, srcW, srcH, crop, boxW, boxH, muted }) => {
  const scale = boxW / crop.w
  return (
    <div style={{ position: 'relative', width: boxW, height: boxH, overflow: 'hidden' }}>
      <OffthreadVideo
        src={src}
        trimBefore={trimBefore}
        muted={muted}
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
