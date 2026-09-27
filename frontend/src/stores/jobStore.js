import { defineStore } from 'pinia'
import {
  apiErrorMessage, clipDownloadUrl, createJob, getHealth, getJobStatus, getRender,
  saveCaptions as apiSaveCaptions, resetCaptions as apiResetCaptions,
  retrySelection as apiRetrySelection, saveClipStyle, startRender,
  saveBounds as apiSaveBounds, resetBounds as apiResetBounds,
  swapClip as apiSwapClip, regenerateClip as apiRegenerateClip,
} from '../services/highlyteApi'
import { layoutAllowed } from '../utils/clipStyle'
import { toClipTime } from '@renderer/lib/timeline'

const POLL_INTERVAL_MS = 1000
const RENDER_POLL_MS = 2000
const STYLE_SAVE_DELAY_MS = 500
const BOUNDS_SAVE_DELAY_MS = 500

// Debounced saves waiting to go out, and saves already in flight, per clip.
// Kept outside Pinia state: they are bookkeeping, not something to render.
const queuedStyles = new Map() // clipId -> style to save when the timer fires
const queuedBounds = new Map() // clipId -> {start, end} to save when the timer fires
const styleSaves = new Map() // clipId -> Promise<void> of the save in flight
const boundsSaves = new Map() // clipId -> Promise<string|null> (error message or null)

function track(saves, clipId, promise, onChange) {
  const p = promise.finally(() => {
    if (saves.get(clipId) === p) saves.delete(clipId)
    onChange?.()
  })
  saves.set(clipId, p)
  onChange?.()
  return p
}

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
    _boundsTimers: {},
    _revisions: {},
    editingClipId: null,
    captionDrafts: {},
    // Bumped on every change to the module-level save-tracking maps below, so
    // `savingClip` (a getter over those non-reactive Maps) re-evaluates.
    _saveActivityTick: 0,
  }),
  getters: {
    clips: (state) => state.job?.clips || [],
    selectedCount: (state) => Object.values(state.selected).filter(Boolean).length,
    allSelected: (state) => {
      const clips = state.job?.clips || []
      return clips.length > 0 && clips.every(c => state.selected[c.id])
    },
    isProcessing: (state) => !!state.job && !['done', 'error', 'selection_failed'].includes(state.job.status),
    isDone: (state) => state.job?.status === 'done',
    selectionFailed: (state) => state.job?.status === 'selection_failed',
    progress: (state) => state.job?.progress || {},
    selectedRenders: (state) => (state.job?.clips || [])
      .filter(c => state.selected[c.id])
      .map(c => state.renders[c.id])
      .filter(Boolean),
    // Whether a style or trim save is queued (debounced) or in flight for
    // this clip. Additive: read-only over the existing save-tracking maps,
    // it doesn't change save behaviour.
    savingClip: (state) => (clipId) => {
      state._saveActivityTick // register the reactive dependency
      return queuedStyles.has(clipId) || queuedBounds.has(clipId) || styleSaves.has(clipId) || boundsSaves.has(clipId)
    },
  },
  actions: {
    async submitUrl(url, language = 'hinglish') {
      this.error = null
      const { job_id } = await createJob(url, language)
      this.currentJobId = job_id
      this.job = null
      this.selected = {}
      this.renders = {}
      this._revisions = {}
      this.editingClipId = null
      this.captionDrafts = {}
      this.startPolling()
      return job_id
    },
    async refresh() {
      if (!this.currentJobId) return
      // Captured before the await: if the project changes while this
      // request is in flight, a late response for the old id must not
      // overwrite the job the user has since switched to.
      const id = this.currentJobId
      try {
        const data = await getJobStatus(id)
        if (this.currentJobId !== id) return
        // The Player needs an absolute URL; the API returns its own path.
        for (const c of data.clips || []) {
          if (c.spec?.source?.url?.startsWith('/')) c.spec.source.url = clipDownloadUrl(c.spec.source.url)
        }
        this.job = data
        if (data.status === 'error') {
          this.error = data.error
          this.stopPolling()
        } else if (data.status === 'selection_failed') {
          this.stopPolling()
        } else if (data.status === 'done') {
          for (const c of data.clips) {
            if (!(c.id in this.selected)) this.selected[c.id] = true
            if (this._revisions[c.id] !== undefined && this._revisions[c.id] !== c.revision) {
              delete this.renders[c.id]
            }
            this._revisions[c.id] = c.revision
          }
          if (!data.clips.some(c => c.pendingAction)) this.stopPolling()
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
    async retrySelection() {
      if (!this.currentJobId) return
      this.error = null
      try {
        await apiRetrySelection(this.currentJobId)
        this.startPolling()
      } catch (e) {
        this.error = apiErrorMessage(e, 'Could not retry clip selection.')
      }
    },
    toggleClip(clipId) {
      this.selected[clipId] = !this.selected[clipId]
    },
    openEditor(clipId) {
      // Switching to a different clip must not carry the previous clip's
      // unsaved caption draft along: its preview would keep showing stale
      // text, and a Save on the new clip would never touch it again.
      if (this.editingClipId && this.editingClipId !== clipId) delete this.captionDrafts[this.editingClipId]
      this.editingClipId = clipId
    },
    closeEditor() {
      if (this.editingClipId) delete this.captionDrafts[this.editingClipId]
      this.editingClipId = null
    },
    // The caption editor's unsaved text, so the clip's card preview can
    // show it live while the editor sits in the side panel.
    setCaptionDraft(clipId, words) {
      if (words) this.captionDrafts[clipId] = words
      else delete this.captionDrafts[clipId]
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
      queuedStyles.set(clipId, clip.style)
      this._bumpSaveActivity()
      this._styleTimers[clipId] = setTimeout(() => this._saveStyleNow(clipId), STYLE_SAVE_DELAY_MS)
    },
    // Sends a queued style save right away (if any) and waits for it and for
    // any style save already in flight, so a following request sees it.
    _saveStyleNow(clipId) {
      clearTimeout(this._styleTimers[clipId])
      delete this._styleTimers[clipId]
      const style = queuedStyles.get(clipId)
      if (style === undefined) return styleSaves.get(clipId) || Promise.resolve()
      queuedStyles.delete(clipId)
      this._bumpSaveActivity()
      return track(styleSaves, clipId, saveClipStyle(clipId, style).then(() => {}, e => {
        this.error = e?.response?.data?.detail || 'Failed to save clip style'
      }), () => this._bumpSaveActivity())
    },
    // Same for the trim; resolves to an error message, or null once saved.
    _saveBoundsNow(clipId) {
      clearTimeout(this._boundsTimers[clipId])
      delete this._boundsTimers[clipId]
      const bounds = queuedBounds.get(clipId)
      if (bounds === undefined) return boundsSaves.get(clipId) || Promise.resolve(null)
      queuedBounds.delete(clipId)
      this._bumpSaveActivity()
      return track(boundsSaves, clipId, apiSaveBounds(clipId, bounds).then(() => null, e => {
        const message = apiErrorMessage(e, 'Failed to save the trim')
        this.error = message
        return message
      }), () => this._bumpSaveActivity())
    },
    // Drops a queued trim save without sending it.
    _cancelBounds(clipId) {
      clearTimeout(this._boundsTimers[clipId])
      delete this._boundsTimers[clipId]
      if (queuedBounds.delete(clipId)) this._bumpSaveActivity()
    },
    // Bumps the reactive counter `savingClip` depends on, so it re-evaluates
    // after a change to the (non-reactive) save-tracking maps above.
    _bumpSaveActivity() {
      this._saveActivityTick++
    },
    // Applies one style to every clip that has a vertical preview. A layout
    // a clip can't use (a face layout with no faces found) falls back to
    // that clip's automatic layout. Hook title text stays per clip.
    applyStyleToAll(patch) {
      let changed = 0
      for (const clip of this.clips) {
        if (!clip.spec) continue
        const clipPatch = { ...patch }
        const clipTimeReframe = toClipTime(clip.spec).reframe
        if ('layout' in clipPatch && !layoutAllowed(clipPatch.layout, clipTimeReframe)) {
          clipPatch.layout = clipTimeReframe.auto
        }
        this.updateStyle(clip.id, clipPatch)
        changed++
      }
      return changed
    },
    async saveCaptions(clipId, words) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      const res = await apiSaveCaptions(clipId, words)
      clip.spec = { ...clip.spec, words: res.words }
      clip.captionsEdited = res.captionsEdited
      clip.actionError = null
      // Any existing render was made with the old text; don't offer it.
      delete this.renders[clipId]
    },
    async resetCaptions(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      const res = await apiResetCaptions(clipId)
      clip.spec = { ...clip.spec, words: res.words }
      clip.captionsEdited = res.captionsEdited
      clip.actionError = null
      delete this.renders[clipId]
    },
    updateBounds(clipId, bounds) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      clip.spec = { ...clip.spec, ...bounds }
      clip.boundsEdited = true
      clip.actionError = null
      delete this.renders[clipId]
      clearTimeout(this._boundsTimers[clipId])
      queuedBounds.set(clipId, bounds)
      this._bumpSaveActivity()
      this._boundsTimers[clipId] = setTimeout(() => this._saveBoundsNow(clipId), BOUNDS_SAVE_DELAY_MS)
    },
    async resetBounds(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      // A nudge still waiting to be saved would otherwise land after the
      // reset and trim the clip again; one already in flight must finish
      // first for the same reason.
      this._cancelBounds(clipId)
      await boundsSaves.get(clipId)
      try {
        const res = await apiResetBounds(clipId)
        clip.spec = { ...clip.spec, start: res.start, end: res.end }
        clip.boundsEdited = res.boundsEdited
        delete this.renders[clipId]
      } catch (e) {
        this.error = apiErrorMessage(e, 'Failed to reset the trim')
      }
    },
    async swapClip(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      clip.actionError = null
      await this._beforeReplace(clipId)
      try {
        const res = await apiSwapClip(clipId)
        clip.pendingAction = res.pendingAction
        this.startPolling()
      } catch (e) {
        clip.actionError = apiErrorMessage(e, 'Failed to swap this clip')
      }
    },
    async regenerateClip(clipId) {
      const clip = this.clips.find(c => c.id === clipId)
      if (!clip) return
      clip.actionError = null
      await this._beforeReplace(clipId)
      try {
        const res = await apiRegenerateClip(clipId)
        clip.pendingAction = res.pendingAction
        this.startPolling()
      } catch (e) {
        clip.actionError = apiErrorMessage(e, 'Failed to regenerate this clip')
      }
    },
    // Before Swap/Regenerate: the clip is about to be replaced, so a queued
    // trim save is moot (cancel it), but a queued style change carries over
    // (preset, accent, caption position), so send it now rather than let it
    // hit the server mid-action and get a 409.
    async _beforeReplace(clipId) {
      this._cancelBounds(clipId)
      await this._saveStyleNow(clipId)
    },
    async exportSelected() {
      // A clip being replaced can't be rendered (the server says 409); it is
      // left out rather than shown as a failed render.
      const clips = this.clips.filter(c => this.selected[c.id] && c.spec && !c.pendingAction)
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
      // The server renders the bounds it has saved, so a nudge still waiting
      // in the debounce (or in flight) must land first, or Export made just
      // after a nudge would render the old trim.
      await this._saveStyleNow(clip.id)
      const boundsError = await this._saveBoundsNow(clip.id)
      if (boundsError) {
        this.renders[clip.id] = { status: 'error', error: boundsError }
        return
      }
      // A status poll may have replaced the clip object while we waited.
      const current = this.clips.find(c => c.id === clip.id) || clip
      try {
        this.renders[clip.id] = await startRender(clip.id, current.style)
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
