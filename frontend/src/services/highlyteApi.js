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
