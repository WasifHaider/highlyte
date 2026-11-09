// Uploads a file straight to R2 in parts, with the presigned part URLs the
// backend handed out. Going around the backend matters: Cloudflare Tunnel
// rejects request bodies over 100 MB. XMLHttpRequest rather than fetch,
// because only XHR reports upload progress.

const CONCURRENCY = 3
const RETRIES = 3

export const MAX_UPLOAD_BYTES = 5 * 1024 ** 3
export const UPLOAD_EXTS = ['.mp4', '.mov', '.mkv', '.webm', '.m4v']
export const UPLOAD_ACCEPT = 'video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-m4v,' + UPLOAD_EXTS.join(',')
export const UPLOAD_FAILED = 'Upload failed. Check your connection and try again.'

// Same checks and wording as the backend, so a bad file fails at once.
export function uploadProblem(file) {
  const name = (file?.name || '').toLowerCase()
  if (!UPLOAD_EXTS.some(ext => name.endsWith(ext))) {
    return "That file type isn't supported. Use MP4, MOV, MKV, WebM or M4V."
  }
  if (!file.size) return 'That file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) return 'File is over 5 GB.'
  return null
}

export class UploadCancelled extends Error {
  constructor() { super('Upload cancelled'); this.name = 'UploadCancelled' }
}

function putPart(url, blob, signal, onLoaded) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new UploadCancelled())
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    signal?.addEventListener('abort', abort, { once: true })
    xhr.open('PUT', url)
    xhr.upload.onprogress = (e) => onLoaded(e.loaded)
    xhr.onload = () => {
      signal?.removeEventListener('abort', abort)
      const etag = xhr.getResponseHeader('ETag')
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag)
      else reject(new Error(`part upload failed (${xhr.status}${etag ? '' : ', no ETag'})`))
    }
    xhr.onerror = () => { signal?.removeEventListener('abort', abort); reject(new Error('network error')) }
    xhr.onabort = () => { signal?.removeEventListener('abort', abort); reject(new UploadCancelled()) }
    xhr.send(blob)
  })
}

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms))

// Returns [{ partNumber, etag }] once every part is in R2.
// onProgress(loadedBytes, totalBytes) fires as bytes go out.
export async function uploadParts(file, partUrls, partSize, { onProgress, signal } = {}) {
  const loaded = new Array(partUrls.length).fill(0)
  const report = () => onProgress?.(loaded.reduce((a, b) => a + b, 0), file.size)
  const parts = []
  let next = 0

  async function uploadOne(index) {
    const blob = file.slice(index * partSize, Math.min(file.size, (index + 1) * partSize))
    for (let attempt = 0; ; attempt++) {
      try {
        const etag = await putPart(partUrls[index], blob, signal, (n) => { loaded[index] = n; report() })
        loaded[index] = blob.size
        report()
        parts.push({ partNumber: index + 1, etag })
        return
      } catch (e) {
        loaded[index] = 0
        report()
        if (e instanceof UploadCancelled || attempt >= RETRIES) throw e
        await wait(1000 * 2 ** attempt)
      }
    }
  }

  async function worker() {
    while (next < partUrls.length) {
      const index = next++
      await uploadOne(index)
    }
  }

  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, partUrls.length) }, worker))
  return parts.sort((a, b) => a.partNumber - b.partNumber)
}
