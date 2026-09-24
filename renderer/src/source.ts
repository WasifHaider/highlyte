import { staticFile } from 'remotion'

// Real specs carry an absolute URL (R2 or the API); the fixture uses a
// file in renderer/public for Studio and still renders.
export const resolveSrc = (url: string): string => (/^(https?:|blob:|\/)/.test(url) ? url : staticFile(url))
