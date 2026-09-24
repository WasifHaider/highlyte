import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

export const api = axios.create({ baseURL })

export function createJob(url, whisperModel = 'small') {
  return api.post('/api/generate', { url, whisper_model: whisperModel }).then(r => r.data)
}

export function getJobStatus(jobId) {
  return api.get(`/api/status/${jobId}`).then(r => r.data)
}

export function listProjects(params = {}) {
  return api.get('/api/jobs', { params }).then(r => r.data)
}

export function clipDownloadUrl(path) {
  return `${baseURL}${path}`
}

export function getHealth() {
  return api.get('/api/health').then(r => r.data)
}

export function saveClipStyle(clipId, style) {
  return api.patch(`/api/clips/${clipId}/style`, style).then(r => r.data)
}

export function startRender(clipId, style) {
  return api.post(`/api/clips/${clipId}/render`, style).then(r => r.data)
}

export function getRender(renderId) {
  return api.get(`/api/renders/${renderId}`).then(r => r.data)
}

export function rendersZipUrl(renderIds) {
  return `${baseURL}/api/renders/zip?ids=${renderIds.join(',')}`
}
