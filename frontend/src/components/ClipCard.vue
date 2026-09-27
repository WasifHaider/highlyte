<template>
  <div class="card card-interactive clip-card" :class="{ editing: isEditing }">
    <div class="preview">
      <RemotionPreview v-if="clip.spec" :spec="previewSpec" :clip-style="clip.style" />
      <div v-else class="no-preview">No vertical preview for this clip. Re-run the video to generate one.</div>
      <div v-if="clip.pendingAction" class="pending-overlay">
        <svg class="spinner" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
        <span class="pending-pill">{{ pendingText }}</span>
      </div>
    </div>

    <div class="body">
      <TrimControls v-if="clip.spec" :clip="clip" />

      <div class="meta-row">
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
        <span class="clip-range tabular">{{ clip.startLabel }}–{{ clip.endLabel }}</span>
        <span class="clip-duration tabular">{{ clip.durationLabel }}</span>
      </div>

      <div v-if="firstCaptionLine" class="caption-preview">"{{ firstCaptionLine }}"</div>
      <div v-if="clip.reason" class="reason">{{ clip.reason }}</div>

      <div v-if="clip.qaFlags?.length" class="qa-flags">
        <span v-for="f in clip.qaFlags" :key="f" class="chip chip-warning">{{ QA_LABELS[f] || f }}</span>
      </div>
      <div class="chips-row">
        <span v-if="clip.tag" class="chip">{{ clip.tag }}</span>
        <span v-if="clip.viralityScore != null" class="virality tabular" title="Virality score">{{ Number(clip.viralityScore).toFixed(1) }}/10</span>
      </div>

      <button
        v-if="clip.spec"
        class="btn btn-secondary btn-sm edit-btn"
        :class="{ editing: isEditing }"
        :aria-pressed="isEditing"
        :disabled="!!clip.pendingAction"
        @click="toggleEdit"
      >{{ isEditing ? 'Editing' : 'Edit' }}</button>

      <div class="actions-row">
        <button class="btn btn-secondary btn-sm" :disabled="swapDisabled" :title="swapTitle" @click="jobStore.swapClip(clip.id)">Swap scene</button>
        <button class="btn btn-secondary btn-sm" :disabled="regenerateDisabled" :title="regenerateTitle" @click="jobStore.regenerateClip(clip.id)">Regenerate</button>
        <a class="btn-ghost srt-link" :href="clipSrtUrl(clip.id)" download>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14"/></svg>
          SRT
        </a>
      </div>

      <div v-if="clip.actionError" class="danger-note action-error">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>
        {{ clip.actionError }}
      </div>

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
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl, clipSrtUrl } from '../services/highlyteApi'
import RemotionPreview from './RemotionPreview.vue'
import TrimControls from './TrimControls.vue'
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
const previewSpec = computed(() => {
  const draft = jobStore.captionDrafts[props.clip.id]
  return draft ? { ...props.clip.spec, words: draft } : props.clip.spec
})
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

function toggleEdit() {
  if (isEditing.value) jobStore.closeEditor()
  else jobStore.openEditor(props.clip.id)
}
</script>

<style scoped>
.clip-card { overflow: hidden; display: flex; flex-direction: column; }
.clip-card.editing { border-color: var(--accent); border-width: 2px; }
.preview { aspect-ratio: 9 / 16; background: #000; position: relative; }
.no-preview {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 16px; background: var(--bg-subtle); color: var(--ink-faint); font-size: 12px;
}
.pending-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  background: rgba(255,255,255,0.4); animation: softPulse 1.6s infinite;
}
.spinner { color: var(--accent); animation: spin 1s linear infinite; }
.pending-pill {
  font-size: 13px; font-weight: 600; color: var(--ink); background: rgba(255,255,255,0.9);
  padding: 4px 12px; border-radius: 999px;
}
.body { padding: 14px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.checkbox {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0; cursor: pointer;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.clip-range { font-size: 12.5px; color: var(--ink-soft); }
.clip-duration { font-size: 11px; color: var(--ink-faint); }
.caption-preview { font-size: 13px; color: var(--ink-soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reason { font-size: 12px; color: var(--ink-faint); margin-top: -4px; }
.qa-flags { display: flex; gap: 6px; flex-wrap: wrap; }
.chips-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.virality { margin-left: auto; font-size: 12px; font-weight: 600; color: var(--ink-soft); }
.edit-btn { width: 100%; }
.edit-btn.editing { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.actions-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
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
</style>
