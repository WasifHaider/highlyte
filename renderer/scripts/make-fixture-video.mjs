// 12 s 1920x1080 test pattern with a tone, used as spec.source for the
// fixture in Studio and still renders (fixture.mp4 is git-ignored).
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'

mkdirSync('public', { recursive: true })
execFileSync('ffmpeg', [
  '-y', '-loglevel', 'error',
  '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30',
  '-f', 'lavfi', '-i', 'sine=frequency=440',
  '-t', '12', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest',
  'public/fixture.mp4',
], { stdio: 'inherit' })
console.log('wrote public/fixture.mp4')
