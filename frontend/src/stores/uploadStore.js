import { defineStore } from 'pinia'
import { abortUpload, apiErrorMessage, completeUpload, getHealth, startUpload } from '../services/highlyteApi'
import { UPLOAD_FAILED, UploadCancelled, uploadParts, uploadProblem } from '../services/uploader'
import { useJobStore } from './jobStore'

// One upload at a time, kept in a store so it carries on if the user moves
// to another page while a big file goes up.
let controller = null
let uploadId = null

function onBeforeUnload(e) {
  e.preventDefault()
  e.returnValue = ''
}

export const useUploadStore = defineStore('upload', {
  state: () => ({
    enabled: false,
    active: false,
    name: '',
    percent: 0,
    bytesPerSecond: 0,
    error: null,
  }),
  actions: {
    async loadEnabled() {
      try {
        this.enabled = !!(await getHealth()).uploads
      } catch {
        this.enabled = false
      }
    },
    // Uploads `file` and starts its job. Returns the job id, or null when
    // the upload failed (see `error`) or was cancelled.
    async upload(file, language) {
      if (this.active) return null
      this.error = uploadProblem(file)
      if (this.error) return null

      this.active = true
      this.name = file.name
      this.percent = 0
      this.bytesPerSecond = 0
      controller = new AbortController()
      window.addEventListener('beforeunload', onBeforeUnload)
      const startedAt = performance.now()
      try {
        const started = await startUpload(file)
        uploadId = started.uploadId
        const parts = await uploadParts(file, started.partUrls, started.partSize, {
          signal: controller.signal,
          onProgress: (loaded, total) => {
            this.percent = total ? Math.min(100, (loaded / total) * 100) : 0
            const seconds = (performance.now() - startedAt) / 1000
            this.bytesPerSecond = seconds > 0.5 ? loaded / seconds : 0
          },
        })
        const { job_id } = await completeUpload(uploadId, parts, language)
        uploadId = null
        return useJobStore().openNewJob(job_id)
      } catch (e) {
        if (!(e instanceof UploadCancelled)) this.error = apiErrorMessage(e, UPLOAD_FAILED)
        if (uploadId) abortUpload(uploadId).catch(() => {})
        uploadId = null
        return null
      } finally {
        this.active = false
        controller = null
        window.removeEventListener('beforeunload', onBeforeUnload)
      }
    },
    cancel() {
      controller?.abort()
    },
  },
})
