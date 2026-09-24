<template>
  <div class="clip-card">
    <div class="preview">
      <RemotionPreview v-if="clip.spec" :spec="clip.spec" :clip-style="clip.style" />
      <div v-else class="no-preview">No vertical preview for this clip. Re-run the video to generate one.</div>
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

      <template v-if="clip.spec">
        <label class="field">
          <span>Hook title</span>
          <input type="text" :value="clip.style.hookTitle || ''" maxlength="80"
            @input="set({ hookTitle: $event.target.value || null })" />
        </label>
        <label class="check">
          <input type="checkbox" :checked="clip.style.showHook" @change="set({ showHook: $event.target.checked })" />
          Show hook title
        </label>
        <div class="field-row">
          <label class="field">
            <span>Layout</span>
            <select :value="clip.style.layout" @change="set({ layout: $event.target.value })">
              <option v-for="l in LAYOUTS" :key="l.value" :value="l.value" :disabled="l.minFaces > faceCount">
                {{ l.label }}{{ l.value === clip.spec.reframe.auto ? ' (auto)' : '' }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>Captions</span>
            <select :value="clip.style.captionPreset" @change="set({ captionPreset: $event.target.value })">
              <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
        </div>
        <div class="field-row">
          <label class="field">
            <span>Caption position</span>
            <select :value="clip.style.captionPosition" :disabled="clip.style.layout === 'split'"
              @change="set({ captionPosition: $event.target.value })">
              <option value="lower">Lower third</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label class="field">
            <span>Accent colour</span>
            <input type="color" :value="clip.style.accent" @input="set({ accent: $event.target.value })" />
          </label>
        </div>
        <div v-if="clip.spec.wordsApprox" class="note">Approximate caption sync</div>
      </template>

      <div class="clip-snippet">"{{ snippet }}"</div>

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
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl } from '../services/highlyteApi'
import RemotionPreview from './RemotionPreview.vue'
import { LAYOUTS, PRESETS } from '../utils/clipStyle'

const props = defineProps({
  clip: { type: Object, required: true },
  isSelected: { type: Boolean, default: false },
})
defineEmits(['toggle'])

const jobStore = useJobStore()
const faceCount = computed(() => props.clip.spec?.reframe.faces.length || 0)
const render = computed(() => jobStore.renders[props.clip.id])
const snippet = computed(() => {
  const t = props.clip.text || ''
  return t.length > 220 ? t.slice(0, 217) + '…' : t
})

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
.field-row { display: flex; gap: 12px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); flex: 1; min-width: 140px; }
.field input[type="text"], .field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field input[type="color"] { width: 48px; height: 32px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); }
.note { font-size: 12px; color: var(--ink-faint); }
.clip-snippet { font-family: var(--font-serif); font-style: italic; font-size: 14.5px; line-height: 1.5; }
.render-status { font-size: 13px; color: var(--ink-soft); }
.render-status.error { color: #9C3B14; }
.render-status a { color: var(--accent); font-weight: 600; }
.retry { margin-left: 8px; border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 3px 10px; cursor: pointer; }
.progress-bar { margin-top: 6px; height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>
