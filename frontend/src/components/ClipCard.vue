<template>
  <div class="clip-card">
    <div class="preview">
      <RemotionPreview v-if="clip.spec" :spec="previewSpec" :clip-style="clip.style" />
      <div v-else class="no-preview">No vertical preview for this clip. Re-run the video to generate one.</div>
      <TrimControls v-if="clip.spec" :clip="clip" />
    </div>

    <div class="details">
      <div class="meta-row">
        <div class="checkbox" :class="{ checked: isSelected }" @click="$emit('toggle')">
          <span v-if="isSelected">✓</span>
        </div>
        <span class="clip-range">{{ clip.startLabel }} – {{ clip.endLabel }}</span>
        <span class="clip-duration">{{ clip.durationLabel }}</span>
        <span class="clip-tag">{{ clip.tag }}</span>
        <span v-if="clip.viralityScore != null" class="virality" title="Virality score">{{ Number(clip.viralityScore).toFixed(1) }}/10</span>
      </div>
      <div v-if="clip.qaFlags?.length" class="qa-flags">
        <span v-for="f in clip.qaFlags" :key="f" class="qa-chip">{{ QA_LABELS[f] || f }}</span>
      </div>
      <div v-if="firstCaptionLine" class="caption-preview">"{{ firstCaptionLine }}"</div>
      <div v-if="clip.reason" class="reason">{{ clip.reason }}</div>

      <template v-if="clip.spec">
        <label class="field">
          <span>Hook title</span>
          <input type="text" :value="clip.style.hookTitle || ''" maxlength="80" :disabled="!!clip.pendingAction"
            @input="set({ hookTitle: $event.target.value || null })" />
        </label>
        <label class="check">
          <input type="checkbox" :checked="clip.style.showHook" :disabled="!!clip.pendingAction" @change="set({ showHook: $event.target.checked })" />
          Show hook title
        </label>
        <div class="field-row">
          <label class="field">
            <span>Layout</span>
            <select :value="clip.style.layout" :disabled="!!clip.pendingAction" @change="set({ layout: $event.target.value })">
              <option v-for="l in LAYOUTS" :key="l.value" :value="l.value" :disabled="!layoutAllowed(l.value, clipTime.reframe)">
                {{ l.label }}{{ l.value === clipTime.reframe.auto ? ' (auto)' : '' }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>Captions</span>
            <select :value="clip.style.captionPreset" :disabled="!!clip.pendingAction" @change="set({ captionPreset: $event.target.value })">
              <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
        </div>
        <div class="field-row">
          <label class="field">
            <span>Caption position</span>
            <select :value="clip.style.captionPosition" :disabled="clip.style.layout === 'split' || !!clip.pendingAction"
              @change="set({ captionPosition: $event.target.value })">
              <option value="lower">Lower third</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label class="field">
            <span>Accent colour</span>
            <input type="color" :value="clip.style.accent" :disabled="!!clip.pendingAction" @input="set({ accent: $event.target.value })" />
          </label>
        </div>
        <div v-if="clip.spec.wordsApprox" class="note">Approximate caption sync</div>
        <div :class="{ 'controls-disabled': clip.pendingAction }">
          <CaptionEditor :clip-id="clip.id" :words="clip.spec.words" :edited="!!clip.captionsEdited"
            :start="clip.spec.version === 2 ? clip.spec.start : null" :end="clip.spec.version === 2 ? clip.spec.end : null"
            :revision="clip.revision || 0" :pending="!!clip.pendingAction"
            @draft="draftWords = $event" />
        </div>
      </template>

      <div class="clip-snippet">"{{ snippet }}"</div>

      <div class="actions-row">
        <button class="action-btn" :disabled="swapDisabled" :title="swapTitle" @click="jobStore.swapClip(clip.id)">Swap scene</button>
        <button class="action-btn" :disabled="regenerateDisabled" :title="regenerateTitle" @click="jobStore.regenerateClip(clip.id)">Regenerate</button>
        <a class="action-link" :href="clipSrtUrl(clip.id)" download>Download SRT</a>
      </div>
      <div v-if="clip.pendingAction" class="pending-note">
        {{ clip.pendingAction === 'swap' ? 'Swapping in another moment…' : 'Regenerating this clip…' }}
      </div>
      <div v-if="clip.actionError" class="action-error">{{ clip.actionError }}</div>

      <div v-if="render" class="render-status" :class="render.status">
        <template v-if="render.status === 'queued'">Waiting to render…</template>
        <template v-else-if="render.status === 'rendering'">
          Rendering {{ Math.round(render.progress || 0) }}%
          <div class="progress-bar"><div class="progress-bar-fill" :style="{ width: (render.progress || 0) + '%' }"></div></div>
        </template>
        <template v-else-if="render.status === 'done'">
          <a :href="clipDownloadUrl(render.downloadUrl)">Download mp4</a>
        </template>
        <template v-else>
          Render failed: {{ render.error }}
          <button class="retry" @click="jobStore.retryRender(clip.id)">Retry</button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl, clipSrtUrl } from '../services/highlyteApi'
import RemotionPreview from './RemotionPreview.vue'
import CaptionEditor from './CaptionEditor.vue'
import TrimControls from './TrimControls.vue'
import { LAYOUTS, PRESETS, layoutAllowed } from '../utils/clipStyle'
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
const draftWords = ref(null)
const previewSpec = computed(() => draftWords.value ? { ...props.clip.spec, words: draftWords.value } : props.clip.spec)
const snippet = computed(() => {
  const t = props.clip.text || ''
  return t.length > 220 ? t.slice(0, 217) + '…' : t
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

function set(patch) {
  jobStore.updateStyle(props.clip.id, patch)
}
</script>

<style scoped>
.clip-card {
  display: grid; grid-template-columns: 220px 1fr; gap: 20px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px;
}
@media (max-width: 640px) { .clip-card { grid-template-columns: 1fr; } }
.no-preview {
  aspect-ratio: 9 / 16; display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 16px; border-radius: 10px; background: var(--accent-soft); color: var(--ink-soft); font-size: 13px;
}
.details { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.meta-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.checkbox {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0; cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 13px; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.clip-range { font-family: monospace; font-size: 12.5px; color: var(--ink-soft); }
.clip-duration { font-size: 11px; color: var(--ink-faint); }
.clip-tag, .virality {
  background: var(--accent-soft); color: var(--accent-text); font-size: 11.5px; font-weight: 600;
  padding: 3px 10px; border-radius: 999px;
}
.qa-flags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.qa-chip {
  font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px;
  background: #FFFAEB; color: #B54708;
}
.field-row { display: flex; gap: 12px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); flex: 1; min-width: 140px; }
.field input[type="text"], .field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field input[type="color"] { width: 48px; height: 32px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); }
.note { font-size: 12px; color: var(--ink-faint); }
.caption-preview { font-family: var(--font-serif); font-style: italic; font-size: 13.5px; line-height: 1.4; color: var(--ink-soft); }
.reason { font-size: 12px; color: var(--ink-faint); }
.clip-snippet { font-family: var(--font-serif); font-style: italic; font-size: 14.5px; line-height: 1.5; }
.actions-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.action-btn {
  border: 1px solid var(--border); background: var(--accent-soft); color: var(--accent-text);
  border-radius: 6px; padding: 4px 10px; font-size: 12.5px; font-weight: 600; cursor: pointer;
}
.action-btn:disabled { opacity: .6; cursor: default; }
.action-link { font-size: 12.5px; font-weight: 600; color: var(--accent); }
.pending-note { font-size: 12.5px; color: var(--ink-soft); }
.action-error { color: #9C3B14; font-size: 12.5px; }
/* CSS-only disable: a pending swap/regenerate is blocked here by dimming and
   swallowing clicks. CaptionEditor also closes itself when the action starts
   (its `pending` prop), so it is never left open and unreachable. */
.controls-disabled { opacity: .6; pointer-events: none; }
.render-status { font-size: 13px; color: var(--ink-soft); }
.render-status.error { color: #9C3B14; }
.render-status a { color: var(--accent); font-weight: 600; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
.progress-bar { margin-top: 6px; height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
