import { defineStore } from 'pinia'
import { createJob, getJobStatus, listJobs } from '../services/highlyteApi'

const POLL_INTERVAL_MS = 1000

export const useJobStore = defineStore('job', {
  state: () => ({
    currentJobId: null,
    job: null,
    recentJobs: [],
    selected: {}, // clipId -> bool
    playingClipId: null,
    error: null,
    polling: false,
    _timer: null,
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
  },
  actions: {
    async submitUrl(url, whisperModel = 'small') {
      this.error = null
      const { job_id } = await createJob(url, whisperModel)
      this.currentJobId = job_id
      this.job = null
      this.selected = {}
      this.startPolling()
      return job_id
    },
    async refresh() {
      if (!this.currentJobId) return
      try {
        const data = await getJobStatus(this.currentJobId)
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
    setPlaying(clipId) {
      this.playingClipId = this.playingClipId === clipId ? null : clipId
    },
    async loadRecentJobs() {
      try {
        this.recentJobs = await listJobs()
      } catch {
        this.recentJobs = []
      }
    },
  },
})
