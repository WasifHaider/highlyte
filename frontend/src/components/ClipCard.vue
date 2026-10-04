<template>
  <div class="card card-interactive clip-card" :class="{ editing: isEditing }">
    <div class="preview">
      <button v-if="clip.spec" type="button" class="poster" aria-label="Edit clip" :disabled="!!clip.pendingAction" @click="openEdit">
        <img v-if="clip.thumbUrl && !posterFailed" :src="clip.thumbUrl" alt="" loading="lazy" @error="posterFailed = true" />
        <span class="play" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.9l10.4-6.5a1 1 0 0 0 0-1.8L9.5 4.6A1 1 0 0 0 8 5.5Z"/></svg>
        </span>
      </button>
      <div v-else class="no-preview">No vertical preview. Re-run the video.</div>
      <span class="duration-badge tabular">{{ clip.durationLabel }}</span>
      <Transition name="fade">
        <div v-if="clip.pendingAction" class="pending-overlay">
          <svg class="spinner" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
          <span class="pending-pill">{{ pendingText }}</span>
        </div>
      </Transition>
    </div>

    <div class="body">
      <div class="title-row">
        <div
          class="checkbox"
          :class="{ checked: isSelected }"
          role="checkbox"
          :aria-checked="isSelected"
          tabindex="0"
          aria-label="Select clip"
          @click="$emit('toggle')"
          @keydown.space.prevent="$emit('toggle')"
          @keydown.enter.prevent="$emit('toggle')"
        >
          <svg v-if="isSelected" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
        </div>
        <h3 class="clip-title">{{ title }}</h3>
        <span v-if="clip.viralityScore != null" class="virality tabular" title="Virality score">{{ Number(clip.viralityScore).toFixed(1) }}<small>/10</small></span>
      </div>

      <div class="meta-row">
        <span class="clip-range tabular">{{ clip.startLabel }}–{{ clip.endLabel }}</span>
        <span v-if="clip.tag" class="chip">{{ clip.tag }}</span>
        <span v-for="f in clip.qaFlags || []" :key="f" class="chip chip-warning">{{ QA_LABELS[f] || f }}</span>
      </div>

      <p v-if="clip.reason" class="reason">{{ clip.reason }}</p>
      <p v-if="firstCaptionLine" class="caption-preview">"{{ firstCaptionLine }}"</p>

      <div class="actions-row">
        <button
          v-if="clip.spec"
          class="btn btn-secondary btn-sm edit-btn"
          :class="{ editing: isEditing }"
          :aria-pressed="isEditing"
          :disabled="!!clip.pendingAction"
          @click="toggleEdit"
        >{{ isEditing ? 'Editing' : 'Edit' }}</button>
        <button class="btn btn-secondary btn-sm" :disabled="swapDisabled || startingSwap" :title="swapTitle" @click="onSwap">
          <BusyLabel :busy="startingSwap" idle="Swap scene" busy-text="Swap scene" spinner-size="12" />
        </button>
        <button class="btn btn-secondary btn-sm" :disabled="regenerateDisabled || startingRegenerate" :title="regenerateTitle" @click="onRegenerate">
          <BusyLabel :busy="startingRegenerate" idle="Regenerate" busy-text="Regenerate" spinner-size="12" />
        </button>
        <a class="btn-ghost srt-link" :href="clipSrtUrl(clip.id)" download>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14"/></svg>
          SRT
        </a>
      </div>

      <Transition name="fade">
        <div v-if="clip.actionError" class="danger-note action-error">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>
          {{ clip.actionError }}
        </div>
      </Transition>

      <Transition name="fade">
        <div v-if="render" class="render-status" :class="render.status">
          <template v-if="render.status === 'queued'">Waiting to render…</template>
          <template v-else-if="render.status === 'rendering'">
            Rendering {{ Math.round(render.progress || 0) }}%
            <div class="progress-bar"><div class="progress-bar-fill" :style="{ width: (render.progress || 0) + '%' }"></div></div>
          </template>
          <template v-else-if="render.status === 'done'">
            <a class="download-link" :href="clipDownloadUrl(render.downloadUrl)">Download mp4</a>
          </template>
          <template v-else>
            <div class="danger-note">
              Render failed: {{ render.error }}
            </div>
            <button class="btn btn-ghost btn-sm retry" @click="jobStore.retryRender(clip.id)">Retry</button>
          </template>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl, clipSrtUrl } from '../services/highlyteApi'
import BusyLabel from './ui/BusyLabel.vue'
import { captionLines, lineText } from '@renderer/captions/edit'
import { toClipTime } from '@renderer/lib/timeline'

const QA_LABELS = {
  low_confidence: 'Low confidence — check captions',
  weak_pick: 'Weaker pick',
  no_face_start: 'No face at start',
}

const props = defineProps({
  clip: { type: Object, required: true },
  isSelected: { type: Boolean, default: false },
})
defineEmits(['toggle'])

const jobStore = useJobStore()
const render = computed(() => jobStore.renders[props.clip.id])
const clipTime = computed(() => toClipTime(props.clip.spec))
const firstCaptionLine = computed(() => {
  if (!props.clip.spec) return ''
  const lines = captionLines(clipTime.value.words)
  return lines[0] ? lineText(lines[0]) : ''
})
const anyPending = computed(() => jobStore.clips.some(c => c.pendingAction))
const swapDisabled = computed(() => anyPending.value || jobStore.job?.alternatesLeft === 0)
const swapTitle = computed(() => {
  if (anyPending.value) return 'Another clip is being replaced. Wait for it to finish.'
  if (jobStore.job?.alternatesLeft === 0) return 'No other moments left to swap in.'
  return ''
})
const regenerateDisabled = computed(() => anyPending.value)
const regenerateTitle = computed(() => anyPending.value ? 'Another clip is being replaced. Wait for it to finish.' : '')
const pendingText = computed(() => props.clip.pendingAction === 'swap' ? 'Swapping in another moment…' : 'Regenerating this clip…')
const isEditing = computed(() => jobStore.editingClipId === props.clip.id)
const posterFailed = ref(false)
// A swapped or regenerated clip gets a new poster file; try it afresh.
watch(() => props.clip.thumbUrl, () => { posterFailed.value = false })

const title = computed(() => props.clip.style?.hookTitle || firstCaptionLine.value || 'Highlight')

function openEdit() {
  if (!isEditing.value) jobStore.openEditor(props.clip.id)
}

function toggleEdit() {
  if (isEditing.value) jobStore.closeEditor()
  else jobStore.openEditor(props.clip.id)
}

// Shows a spinner for the brief window between the click and the store
// setting clip.pendingAction (the request that starts the replace), on top
// of the store's own pendingAction overlay that covers the rest of it.
const startingSwap = ref(false)
const startingRegenerate = ref(false)
async function onSwap() {
  startingSwap.value = true
  try {
    await jobStore.swapClip(props.clip.id)
  } finally {
    startingSwap.value = false
  }
}
async function onRegenerate() {
  startingRegenerate.value = true
  try {
    await jobStore.regenerateClip(props.clip.id)
  } finally {
    startingRegenerate.value = false
  }
}
</script>

<style scoped>
/* Opus-style row: small 9:16 thumbnail on the left, details and actions on
   the right. The big preview and every control live in the edit panel. */
.clip-card { overflow: hidden; display: flex; flex-direction: row; align-items: stretch; gap: 16px; padding: 14px; }
.clip-card.editing { border-color: var(--accent); border-width: 2px; padding: 13px; }
.preview {
  aspect-ratio: 9 / 16; background: #000; position: relative; overflow: hidden;
  width: 112px; flex-shrink: 0; align-self: flex-start; border-radius: 10px;
}
.poster {
  position: absolute; inset: 0; width: 100%; padding: 0; border: 0; cursor: pointer;
  background: #000; display: flex; align-items: center; justify-content: center;
}
.poster:disabled { cursor: default; }
.poster img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.poster .play {
  position: relative; width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; padding-left: 2px;
  background: rgba(0,0,0,0.55); color: #fff; transition: transform 0.15s ease, background 0.15s ease;
}
.poster:not(:disabled):hover .play, .poster:focus-visible .play { transform: scale(1.08); background: var(--accent); }
.duration-badge {
  position: absolute; right: 6px; bottom: 6px; font-size: 10.5px; font-weight: 600; color: #fff;
  background: rgba(0,0,0,0.65); padding: 1px 6px; border-radius: 4px; pointer-events: none;
}
.no-preview {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 8px; background: var(--bg-subtle); color: var(--ink-faint); font-size: 11px;
}
.pending-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  background: rgba(255,255,255,0.5); animation: softPulse 1.6s infinite; text-align: center; padding: 6px;
}
.spinner { color: var(--accent); animation: spin 1s linear infinite; }
.pending-pill {
  font-size: 11px; font-weight: 600; color: var(--ink); background: rgba(255,255,255,0.9);
  padding: 3px 8px; border-radius: 999px;
}
.body { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.title-row { display: flex; align-items: flex-start; gap: 10px; }
.clip-title {
  flex: 1; min-width: 0; margin: 0; font-size: 14.5px; font-weight: 600; line-height: 1.35; color: var(--ink);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.checkbox {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0; cursor: pointer; margin-top: 2px;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.virality {
  flex-shrink: 0; font-size: 15px; font-weight: 700; color: var(--accent-text, var(--accent));
  background: var(--accent-soft); padding: 1px 8px; border-radius: 999px;
}
.virality small { font-size: 10.5px; font-weight: 500; color: var(--ink-soft); }
.meta-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.clip-range { font-size: 12px; color: var(--ink-faint); margin-right: 2px; }
.reason { margin: 0; font-size: 12.5px; color: var(--ink-soft); }
.caption-preview {
  margin: 0; font-size: 12.5px; color: var(--ink-faint);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.edit-btn.editing { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.actions-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: auto; padding-top: 4px; }
.srt-link {
  margin-left: auto; display: inline-flex; align-items: center; gap: 5px;
  font-size: 12.5px; font-weight: 500; color: var(--ink-soft); text-decoration: none; padding: 4px 6px; border-radius: 6px;
}
.srt-link:hover { color: var(--ink); background: var(--bg-subtle); }
.action-error { display: flex; align-items: center; gap: 6px; }
.render-status { font-size: 12.5px; color: var(--ink-soft); }
.download-link { color: var(--accent); font-weight: 600; }
.progress-bar { margin-top: 6px; height: 4px; border-radius: 2px; background: var(--bg-subtle); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
.retry { margin-top: 6px; }

@media (max-width: 480px) {
  .clip-card { gap: 12px; }
  .preview { width: 88px; }
}
</style>
