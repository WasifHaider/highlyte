import axios from 'axios'

// Same origin: Vite proxies /api to the backend in development, and in
// production both are served from one domain. That's what lets the
// backend's httpOnly session cookies go with every request, <video> too.
const baseURL = ''

export const api = axios.create({
  baseURL,
  withCredentials: true,
  // The backend rejects changes without this header (CSRF protection).
  headers: { 'X-Requested-With': 'highlyte' },
})

// A 401 outside the login endpoints means the session is gone (expired,
// logged out elsewhere, or the user was removed), so go log in again.
api.interceptors.response.use(
  response => response,
  (error) => {
    const status = error?.response?.status
    const url = error?.config?.url || ''
    if (status === 401 && !url.startsWith('/api/auth/')) {
      const next = window.location.pathname + window.location.search
      window.location.assign(`/login?next=${encodeURIComponent(next)}`)
    }
    return Promise.reject(error)
  },
)

export function createJob(url, language = 'hinglish') {
  return api.post('/api/generate', { url, language }).then(r => r.data)
}

export function getJobStatus(jobId) {
  return api.get(`/api/status/${jobId}`).then(r => r.data)
}

export function retrySelection(jobId) {
  return api.post(`/api/jobs/${jobId}/select`).then(r => r.data)
}

export function listProjects(params = {}) {
  return api.get('/api/jobs', { params }).then(r => r.data)
}

export function deleteProject(jobId) {
  return api.delete(`/api/jobs/${jobId}`)
}

export function retryProject(jobId) {
  return api.post(`/api/jobs/${jobId}/retry`).then(r => r.data)
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

export function saveCaptions(clipId, words) {
  return api.put(`/api/clips/${clipId}/captions`, { words }).then(r => r.data)
}

export function resetCaptions(clipId) {
  return api.post(`/api/clips/${clipId}/captions/reset`).then(r => r.data)
}

export function saveBounds(clipId, bounds) {
  return api.patch(`/api/clips/${clipId}/bounds`, bounds).then(r => r.data)
}

export function resetBounds(clipId) {
  return api.post(`/api/clips/${clipId}/bounds/reset`).then(r => r.data)
}

export function swapClip(clipId) {
  return api.post(`/api/clips/${clipId}/swap`).then(r => r.data)
}

export function regenerateClip(clipId) {
  return api.post(`/api/clips/${clipId}/regenerate`).then(r => r.data)
}

export function clipSrtUrl(clipId) {
  return `${baseURL}/api/clips/${clipId}/captions.srt`
}

// saveStyle: false renders the clip in `style` without saving it as the
// clip's style (the export bar's extra shapes).
export function startRender(clipId, style, { saveStyle = true } = {}) {
  const params = saveStyle ? undefined : { save_style: false }
  return api.post(`/api/clips/${clipId}/render`, style, { params }).then(r => r.data)
}

export function getRender(renderId) {
  return api.get(`/api/renders/${renderId}`).then(r => r.data)
}

export function rendersZipUrl(renderIds) {
  return `${baseURL}/api/renders/zip?ids=${renderIds.join(',')}`
}

export function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export const getMe = () => api.get('/api/auth/me').then(r => r.data)
export const login = (email, password) => api.post('/api/auth/login', { email, password }).then(r => r.data)
export const signup = (teamName, email, password) =>
  api.post('/api/auth/signup', { teamName, email, password }).then(r => r.data)
export const logout = () => api.post('/api/auth/logout')

export const listTeamUsers = () => api.get('/api/team/users').then(r => r.data)
export const addTeamUser = email => api.post('/api/team/users', { email }).then(r => r.data)
export const removeTeamUser = userId => api.delete(`/api/team/users/${userId}`)

export const setMyGroqKey = groqKey => api.put('/api/me/groq-key', { groqKey }).then(r => r.data)
export const setMyGroqBackupKey = groqBackupKey => api.put('/api/me/groq-backup-key', { groqBackupKey }).then(r => r.data)
export const setMyBrandKit = kit => api.put('/api/me/brand-kit', kit).then(r => r.data)

// Video upload: the browser sends the parts straight to R2 (see uploader.js).
export const startUpload = (file) =>
  api.post('/api/uploads', { filename: file.name, size: file.size, contentType: file.type || null }).then(r => r.data)
export const completeUpload = (uploadId, parts, language) =>
  api.post(`/api/uploads/${uploadId}/complete`, { parts, language }).then(r => r.data)
export const abortUpload = (uploadId) => api.delete(`/api/uploads/${uploadId}`)
