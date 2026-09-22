import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export const api = axios.create({ baseURL })

export function createJob(url, whisperModel = 'small') {
  return api.post('/api/generate', { url, whisper_model: whisperModel }).then(r => r.data)
}

export function getJobStatus(jobId) {
  return api.get(`/api/status/${jobId}`).then(r => r.data)
}

export function listJobs() {
  return api.get('/api/jobs').then(r => r.data)
}

export function clipDownloadUrl(path) {
  return `${baseURL}${path}`
}
