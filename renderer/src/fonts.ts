import { loadFont } from '@remotion/google-fonts/Montserrat'

// Loaded through Remotion so the browser preview and Lambda render wait
// for the same font before drawing a frame.
export const { fontFamily } = loadFont('normal', { weights: ['700', '800', '900'], subsets: ['latin'] })
