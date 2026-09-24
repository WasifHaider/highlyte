import { defineStore } from 'pinia'
import {
  clipDownloadUrl, createJob, getHealth, getJobStatus, getRender, saveClipStyle, startRender,
} from '../services/highlyteApi'

const POLL_INTERVAL_MS = 1000
const RENDER_POLL_MS = 2000
const STYLE_SAVE_DELAY_MS = 500

export const useJobStore = defineStore('job', {
  state: () => ({
    currentJobId: null,
    job: null,
    selected: {}, // clipId -> bool
    error: null,
    polling: false,
    _timer: null,
    renders: {}, // clipId -> render {id, status, progress, error, downloadUrl}
    renderingEnabled: false,
    _renderTimer: null,
    _styleTimers: {},
  }),
  getters: {
    clips: (state) => state.job?.clips || [],
    selectedCount: (state) => Object.values(state.selected).filter(Boolean).length,
    allSelected: (state) => {
      const clips = state.job?.clips || []
      return clips.length > 0 && clips.every(c => state.selected[c.id])
    },
    isProcessing: (state) => !!state.job && !['done', 'error'].includes(state.job.status),
    isDone: (state) => state.job?.status === 'done',
    progress: (state) => state.job?.progress || {},
    selectedRenders: (state) => (state.job?.clips || [])
      .filter(c => state.selected[c.id])
      .map(c => state.renders[c.id])
      .filter(Boolean),
  },
  actions: {
    async submitUrl(url, whisperModel = 'small') {
      this.error = null
      const { job_id } = await createJob(url, whisperModel)
      this.currentJobId = job_id
      this.job = null
      this.selected = {}
      this.renders = {}
      this.startPolling()
      return job_id
    },
    async refresh() {
      if (!this.currentJobId) return
      try {
        const data = await getJobStatus(this.currentJobId)
        // The Player needs an absolute URL; the API returns its own path.
        for (const c of data.clips || []) {
          if (c.spec?.source?.url?.startsWith('/')) c.spec.source.url = clipDownloadUrl(c.spec.source.url)
        }
        this.job = data
        if (data.status === 'error') {
          this.error = data.error
          this.stopPolling()
        } else if (data.status === 'done') {
          for (const c of data.clips) {
            if (!(c.id in this.selected)) this.selected[c.id] = true
          }
          this.stopPolling()
        }
      } catch (e) {
        this.error = e?.message || 'Failed to fetch job status'
        this.stopPolling()
      }
    },
    startPolling() {
      this.stopPolling()
      this.polling = true
      this.refresh()
      this._timer = setInterval(() => this.refresh(), POLL_INTERVAL_MS)
    },
    stopPolling() {
      this.polling = false
      if (this._timer) {
        clearInterval(this._timer)
        this._timer = null
      }
    },
    toggleClip(clipId) {
      this.selected[clipId] = !this.selected[clipId]
    },
    toggleSelectAll() {
      const target = !this.allSelected
      for (const c of this.clips) this.selected[c.id] = target
    },
    async loadHealth() {
      try {
        this.renderingEnabled = !!(await getHealth()).rendering
      } catch {
        this.renderingEnabled = false
      }
    },
    updateStyle(clipId, patch) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      clip.style = { ...clip.style, ...patch }
      // Saving is debounced so typing in the hook title isn't a request per key.
      clearTimeout(this._styleTimers[clipId])
      this._styleTimers[clipId] = setTimeout(() => {
        saveClipStyle(clipId, clip.style).catch(e => {
          this.error = e?.response?.data?.detail || 'Failed to save clip style'
        })
      }, STYLE_SAVE_DELAY_MS)
    },
    async exportSelected() {
      const clips = this.clips.filter(c => this.selected[c.id] && c.spec)
      for (const c of clips) await this._render(c)
      this._pollRenders()
    },
    async retryRender(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      await this._render(clip)
      this._pollRenders()
    },
    async _render(clip) {
      try {
        this.renders[clip.id] = await startRender(clip.id, clip.style)
      } catch (e) {
        this.renders[clip.id] = { status: 'error', error: e?.response?.data?.detail || e.message }
      }
    },
    _pollRenders() {
      if (this._renderTimer) return
      this._renderTimer = setInterval(async () => {
        const pending = Object.entries(this.renders).filter(([, r]) => r.id && ['queued', 'rendering'].includes(r.status))
        if (pending.length === 0) {
          clearInterval(this._renderTimer)
          this._renderTimer = null
          return
        }
        for (const [clipId, r] of pending) {
          try {
            this.renders[clipId] = await getRender(r.id)
          } catch {
            // transient; try again next tick
          }
        }
      }, RENDER_POLL_MS)
    },
  },
})
