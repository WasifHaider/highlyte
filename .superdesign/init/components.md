# Components (Vue 3 SFCs, vanilla scoped CSS, no component library)
Framework: Vue 3 + Vite + Pinia + vue-router. CSS: global tokens in src/style.css + <style scoped> per component. React only inside the Remotion preview (RemotionPreview.vue mounts @remotion/player).

### `frontend/src/components/ClipCard.vue`

```vue
<template>
  <div class="clip-card">
    <div class="preview">
      <RemotionPreview v-if="clip.spec" :spec="previewSpec" :clip-style="clip.style" />
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
              <option v-for="l in LAYOUTS" :key="l.value" :value="l.value" :disabled="!layoutAllowed(l.value, clip.spec.reframe)">
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
        <CaptionEditor :clip-id="clip.id" :words="clip.spec.words" :edited="!!clip.captionsEdited" @draft="draftWords = $event" />
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
import { computed, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { clipDownloadUrl } from '../services/highlyteApi'
import RemotionPreview from './RemotionPreview.vue'
import CaptionEditor from './CaptionEditor.vue'
import { LAYOUTS, PRESETS, layoutAllowed } from '../utils/clipStyle'

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

```

### `frontend/src/components/ClipList.vue`

```vue
<template>
  <div>
    <StyleAllBar v-if="hasVerticalClips" />
    <div class="results-header">
      <div class="results-title">Highlights</div>
      <div class="select-all" @click="jobStore.toggleSelectAll()">
        <div class="checkbox" :class="{ checked: jobStore.allSelected }">
          <span v-if="jobStore.allSelected">✓</span>
        </div>
        Select all
      </div>
    </div>

    <div class="clip-list">
      <ClipCard
        v-for="clip in jobStore.clips"
        :key="clip.id"
        :clip="clip"
        :is-selected="!!jobStore.selected[clip.id]"
        @toggle="jobStore.toggleClip(clip.id)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import ClipCard from './ClipCard.vue'
import StyleAllBar from './StyleAllBar.vue'

const jobStore = useJobStore()
const hasVerticalClips = computed(() => jobStore.clips.some(c => c.spec))
</script>

<style scoped>
.results-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 18px; flex-wrap: wrap; gap: 8px; }
.results-title { font-family: var(--font-serif); font-size: 26px; font-weight: 500; }
.select-all { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--ink-soft); }
.checkbox {
  width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }
.clip-list { display: flex; flex-direction: column; gap: 16px; }
</style>

```

### `frontend/src/components/CaptionEditor.vue`

```vue
<template>
  <div class="captions-edit">
    <div class="row">
      <button v-if="!open" class="btn" @click="start">Edit captions</button>
      <button v-if="!open && edited" class="btn ghost" :disabled="busy" @click="reset">Reset to original</button>
    </div>
    <div v-if="open" class="lines">
      <label v-for="(line, i) in lines" :key="line.index" class="line">
        <span class="time">{{ clock(line.start) }}</span>
        <input v-model="texts[i]" type="text" />
      </label>
      <div class="row">
        <button class="btn" :disabled="busy || saveDisabled" @click="save">{{ busy ? 'Saving…' : 'Save captions' }}</button>
        <button class="btn ghost" :disabled="busy" @click="cancel">Cancel</button>
      </div>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { captionLines, editLine, lineText } from '@renderer/captions/edit'
import { useJobStore } from '../stores/jobStore'

const props = defineProps({
  clipId: { type: String, required: true },
  words: { type: Array, required: true },
  edited: { type: Boolean, default: false },
})
const emit = defineEmits(['draft'])
const jobStore = useJobStore()

// Mirrors backend.captions.MAX_WORD_CHARS: catch the same limit here so
// a bad edit gets a clear message instead of a 422 after Save.
const MAX_WORD_CHARS = 40

const open = ref(false)
const busy = ref(false)
const error = ref('')
const texts = ref([])
const lines = computed(() => captionLines(props.words))

// Applied last line first, so each line's word index stays valid.
const draft = computed(() => {
  if (!open.value) return null
  let out = props.words
  for (let i = lines.value.length - 1; i >= 0; i--) {
    const line = lines.value[i]
    if (texts.value[i] !== lineText(line)) out = editLine(out, line, texts.value[i] ?? '')
  }
  return out
})
watch(draft, d => emit('draft', d))

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// Nothing to save once every line has been cleared out.
const saveDisabled = computed(() => open.value && (draft.value?.length ?? 0) === 0)

function overlongWordLine() {
  for (let i = 0; i < lines.value.length; i++) {
    const hasOverlong = (texts.value[i] || '').split(/\s+/).some(t => t.length > MAX_WORD_CHARS)
    if (hasOverlong) return lines.value[i]
  }
  return null
}

function start() {
  texts.value = lines.value.map(lineText)
  error.value = ''
  open.value = true
}
function cancel() {
  open.value = false
}
async function save() {
  const overlong = overlongWordLine()
  if (overlong) {
    error.value = `The line at ${clock(overlong.start)} has a word over ${MAX_WORD_CHARS} characters.`
    return
  }
  busy.value = true
  error.value = ''
  try {
    await jobStore.saveCaptions(props.clipId, draft.value)
    open.value = false
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to save captions'
  } finally {
    busy.value = false
  }
}
async function reset() {
  busy.value = true
  error.value = ''
  try {
    await jobStore.resetCaptions(props.clipId)
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Failed to reset captions'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.captions-edit { margin-top: 10px; }
.row { display: flex; gap: 8px; margin-top: 8px; }
.lines { display: flex; flex-direction: column; gap: 6px; max-height: 280px; overflow-y: auto; }
.line { display: flex; align-items: center; gap: 8px; }
.time { font-family: monospace; font-size: 11.5px; color: var(--ink-soft); width: 36px; flex-shrink: 0; }
.line input { flex: 1; min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.btn { border: 1px solid var(--border); background: var(--accent-soft); color: var(--accent-text); border-radius: 6px; padding: 4px 10px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.btn.ghost { background: transparent; color: var(--ink-soft); }
.btn:disabled { opacity: .6; cursor: default; }
.error { color: #9C3B14; font-size: 12.5px; margin-top: 6px; }
</style>

```

### `frontend/src/components/ExportBar.vue`

```vue
<template>
  <div class="bottombar">
    <div class="bottombar-inner">
      <span class="selection-label">{{ label }}</span>
      <div class="actions">
        <a v-if="zipUrl" class="zip-link" :href="zipUrl">Download all (zip)</a>
        <button
          class="export-btn"
          :class="{ active: canExport }"
          :disabled="!canExport"
          :title="jobStore.renderingEnabled ? '' : 'Rendering not configured'"
          @click="jobStore.exportSelected()"
        >
          {{ jobStore.renderingEnabled ? 'Render & export selected' : 'Rendering not configured' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { rendersZipUrl } from '../services/highlyteApi'

const jobStore = useJobStore()

const label = computed(() => {
  const n = jobStore.selectedCount
  if (n === 0) return 'Select clips to export'
  const renders = jobStore.selectedRenders
  const done = renders.filter(r => r.status === 'done').length
  const busy = renders.filter(r => ['queued', 'rendering'].includes(r.status)).length
  if (busy) return `Rendering ${busy} of ${n} clips… (${done} done)`
  return `${n} of ${jobStore.clips.length} clips selected`
})

const canExport = computed(() => jobStore.renderingEnabled && jobStore.selectedCount > 0)

const zipUrl = computed(() => {
  const renders = jobStore.selectedRenders
  if (renders.length === 0 || renders.length !== jobStore.selectedCount) return null
  if (!renders.every(r => r.status === 'done')) return null
  return rendersZipUrl(renders.map(r => r.id))
})
</script>

<style scoped>
.bottombar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
  background: rgba(255,255,255,0.94); backdrop-filter: blur(6px); border-top: 1px solid var(--border);
}
.bottombar-inner {
  max-width: 800px; margin: 0 auto; padding: 16px 24px;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}
.selection-label { font-size: 13.5px; color: var(--ink-soft); }
.actions { display: flex; align-items: center; gap: 14px; }
.zip-link { font-size: 13.5px; font-weight: 600; color: var(--accent); }
.export-btn {
  border: none; border-radius: 8px; padding: 10px 20px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); cursor: default; color: #fff;
  background: rgba(0,71,65,0.25);
}
.export-btn.active { background: var(--accent); cursor: pointer; }
</style>

```

### `frontend/src/components/ProcessingSteps.vue`

```vue
<template>
  <div class="processing-card">
    <div class="processing-title">Processing your episode</div>
    <div class="steps">
      <div class="step" v-for="step in steps" :key="step.key">
        <div class="step-dot" :class="step.state">
          <span v-if="step.state === 'done'">✓</span>
        </div>
        <div class="step-text">
          <span class="step-label" :class="step.state === 'active' ? 'current' : step.state">{{ step.label }}</span>
          <div v-if="step.state === 'active' && progressNote" class="step-progress">
            <div v-if="progress.percent != null" class="progress-bar">
              <div class="progress-bar-fill" :style="{ width: Math.min(100, progress.percent) + '%' }"></div>
            </div>
            <span class="step-progress-note">{{ progressNote }}</span>
            <div v-if="progress.latestText" class="step-progress-text">"{{ progress.latestText }}"</div>
          </div>
        </div>
      </div>
    </div>
    <div class="processing-hint">This takes a few minutes on CPU: every clip gets word-timed captions and face tracking.</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, required: true }, // queued|transcribing|analyzing|preparing|done|error
  progress: { type: Object, default: () => ({}) },
})

const ORDER = ['transcribing', 'analyzing', 'preparing']
const LABELS = {
  transcribing: 'Transcribing audio',
  analyzing: 'Analyzing for highlights',
  preparing: 'Preparing clips (captions and framing)',
}

const steps = computed(() => {
  const currentIdx = ORDER.indexOf(props.status)
  return ORDER.map((key, i) => {
    let state = 'pending'
    if (props.status === 'done' || i < currentIdx) state = 'done'
    else if (i === currentIdx) state = 'active'
    return { key, label: LABELS[key], state }
  })
})

const progressNote = computed(() => props.progress?.note || '')
</script>

<style scoped>
.processing-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 48px 32px;
  max-width: 440px;
  margin: 0 auto;
  text-align: center;
}
.processing-title { font-family: var(--font-serif); font-size: 19px; font-weight: 500; margin-bottom: 28px; }
.step { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; text-align: left; }
.step-dot {
  width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0; margin-top: 1px;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: #fff;
  background: #fff; border: 1.5px solid var(--border);
}
.step-dot.active { background: var(--accent); animation: dotPulse 1s ease-in-out infinite; }
.step-dot.done { background: var(--accent); }
.step-text { flex: 1; min-width: 0; }
.step-label { font-size: 14px; color: var(--ink-faint); }
.step-label.current { color: var(--ink); font-weight: 600; }
.step-label.done { color: var(--ink); }
.step-progress { margin-top: 6px; }
.progress-bar {
  height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; margin-bottom: 5px;
}
.progress-bar-fill {
  height: 100%; background: var(--accent); transition: width .3s ease;
}
.step-progress-note { font-size: 11.5px; color: var(--ink-soft); font-family: monospace; }
.step-progress-text {
  margin-top: 4px; font-size: 12px; color: var(--ink-faint); font-style: italic;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.processing-hint { margin-top: 20px; font-size: 12px; color: var(--ink-soft); }
</style>

```

### `frontend/src/components/ProjectCard.vue`

```vue
<template>
  <router-link :to="{ name: 'job', params: { id: project.id } }" class="project-card">
    <div class="thumb">
      <img v-if="project.thumbnailUrl && !imgFailed" :src="project.thumbnailUrl" alt="" loading="lazy" @error="imgFailed = true" />
      <div v-else class="thumb-placeholder" aria-hidden="true"><span class="play"></span></div>
      <span v-if="project.durationLabel" class="duration">{{ project.durationLabel }}</span>
    </div>
    <div class="body">
      <div class="title">{{ project.videoTitle || 'Untitled video' }}</div>
      <div v-if="project.videoChannel" class="channel">{{ project.videoChannel }}</div>
      <div class="status-row">
        <template v-if="processing">
          <span class="badge processing">Processing</span>
          <span class="note">{{ project.progress?.note || '' }}</span>
        </template>
        <span v-else-if="project.status === 'done'" class="badge done">
          Done · {{ project.clipCount }} clip{{ project.clipCount === 1 ? '' : 's' }}
        </span>
        <span v-else class="badge failed" :title="project.error || ''">Failed</span>
        <span class="time">{{ relativeTime(project.createdAt) }}</span>
      </div>
      <div v-if="processing && project.progress?.percent != null" class="progress-bar">
        <div class="progress-bar-fill" :style="{ width: Math.min(100, project.progress.percent) + '%' }"></div>
      </div>
    </div>
  </router-link>
</template>

<script setup>
import { computed, ref } from 'vue'
import { relativeTime } from '../utils/time'
import { isProcessing } from '../utils/projects'

const props = defineProps({ project: { type: Object, required: true } })
const imgFailed = ref(false)
const processing = computed(() => isProcessing(props.project))
</script>

<style scoped>
.project-card {
  display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; text-decoration: none; color: var(--ink);
  transition: border-color .15s ease, transform .15s ease;
}
.project-card:hover { border-color: var(--accent); transform: translateY(-1px); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: var(--accent-soft); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
.play { width: 0; height: 0; border-top: 12px solid transparent; border-bottom: 12px solid transparent; border-left: 18px solid var(--ink-faint); }
.duration {
  position: absolute; right: 8px; bottom: 8px; background: rgba(0,0,0,.75); color: #fff;
  font-size: 11.5px; padding: 2px 6px; border-radius: 4px;
}
.body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 4px; }
.title { font-weight: 600; font-size: 14.5px; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.channel { font-size: 12.5px; color: var(--ink-soft); }
.status-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; }
.badge { font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.badge.processing { background: #FFF4D6; color: #8A5A00; }
.badge.done { background: var(--accent-soft); color: var(--accent-text); }
.badge.failed { background: #FBEAE3; color: #9C3B14; }
.note { color: var(--ink-soft); }
.time { color: var(--ink-faint); margin-left: auto; }
.progress-bar { height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; margin-top: 6px; }
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
</style>

```

### `frontend/src/components/VideoCard.vue`

```vue
<template>
  <div class="video-card">
    <div class="thumb">
      <img v-if="meta.thumbnailUrl && !imgFailed" :src="meta.thumbnailUrl" alt="" @error="imgFailed = true" />
      <span v-else class="play" aria-hidden="true"></span>
    </div>
    <div class="video-info">
      <div class="video-title">{{ meta.title }}</div>
      <div class="video-meta">{{ meta.channel }} · {{ meta.durationLabel }}</div>
      <div class="status-note">{{ statusNote }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  meta: { type: Object, required: true },
  statusNote: { type: String, default: '' },
})
const imgFailed = ref(false)
</script>

<style scoped>
.video-card {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 44px;
}
.thumb {
  width: 180px;
  height: 101px;
  flex-shrink: 0;
  border-radius: 10px;
  background: repeating-linear-gradient(45deg,#F0EDE4,#F0EDE4 8px,#E3DFD3 8px,#E3DFD3 16px);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  overflow: hidden;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.play { width: 0; height: 0; border-top: 10px solid transparent; border-bottom: 10px solid transparent; border-left: 15px solid var(--ink-faint); }
.video-info { flex: 1; min-width: 200px; display: flex; flex-direction: column; justify-content: center; }
.video-title { font-family: var(--font-serif); font-size: 22px; font-weight: 500; line-height: 1.3; }
.video-meta { margin-top: 8px; font-size: 13px; color: var(--ink-soft); }
.status-note { margin-top: 6px; font-size: 12px; color: var(--accent); font-weight: 500; }
</style>

```

### `frontend/src/components/StyleAllBar.vue`

```vue
<template>
  <div class="style-all">
    <div class="bar-title">Style all clips</div>
    <div class="fields">
      <label class="field">
        <span>Layout</span>
        <select v-model="form.layout">
          <option v-for="l in LAYOUTS" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>Captions</span>
        <select v-model="form.captionPreset">
          <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </label>
      <label class="field color">
        <span>Accent colour</span>
        <input v-model="form.accent" type="color" />
      </label>
      <label class="check">
        <input v-model="form.showHook" type="checkbox" /> Show hook title
      </label>
      <button class="apply" @click="apply">Apply to all</button>
    </div>
    <div class="hint">
      <template v-if="appliedCount">Applied to {{ appliedCount }} clip{{ appliedCount === 1 ? '' : 's' }}.</template>
      <template v-else>Clips that can't use a face layout keep their automatic layout. Hook titles stay per clip.</template>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useJobStore } from '../stores/jobStore'
import { LAYOUTS, PRESETS } from '../utils/clipStyle'

const APPLIED_MESSAGE_MS = 2400

const jobStore = useJobStore()
// Start from the first clip's current style so the bar reflects what's there.
const first = jobStore.clips.find(c => c.spec)?.style || {}
const form = reactive({
  layout: first.layout || 'fit',
  captionPreset: first.captionPreset || 'karaoke',
  accent: first.accent || '#FFD400',
  showHook: first.showHook ?? true,
})
const appliedCount = ref(0)
let timer = null

function apply() {
  appliedCount.value = jobStore.applyStyleToAll({ ...form })
  clearTimeout(timer)
  timer = setTimeout(() => { appliedCount.value = 0 }, APPLIED_MESSAGE_MS)
}
onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.style-all { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; }
.bar-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; }
.fields { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); min-width: 150px; }
.field select {
  font-family: var(--font-sans); font-size: 13.5px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 9px; background: #fff;
}
.field.color { min-width: 0; }
.field input[type="color"] { width: 48px; height: 34px; border: 1px solid var(--border); border-radius: 8px; padding: 2px; background: #fff; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-soft); padding-bottom: 8px; }
.apply {
  border: none; border-radius: 8px; padding: 9px 16px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
.hint { margin-top: 10px; font-size: 12px; color: var(--ink-faint); }
</style>

```

### `frontend/src/components/RemotionPreview.vue`

```vue
<template>
  <div ref="host" class="remotion-preview"></div>
</template>

<script setup>
// Hosts the Remotion Player (React) inside this Vue app. The composition
// is imported straight from renderer/src, so the preview is the exact
// code Lambda renders.
import { onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { Player } from '@remotion/player'
import { ClipComposition } from '@renderer/ClipComposition'
import { FPS, OUT_H, OUT_W, durationInFrames } from '@renderer/constants'

const props = defineProps({
  spec: { type: Object, required: true },
  clipStyle: { type: Object, required: true },
})

const host = ref(null)
let root = null

// React must receive plain objects, not Vue's reactive proxies.
const plain = (value) => JSON.parse(JSON.stringify(toRaw(value)))

function draw() {
  if (!root) return
  const spec = plain(props.spec)
  root.render(createElement(Player, {
    component: ClipComposition,
    inputProps: { spec, style: plain(props.clipStyle) },
    durationInFrames: durationInFrames(spec),
    fps: FPS,
    compositionWidth: OUT_W,
    compositionHeight: OUT_H,
    controls: true,
    acknowledgeRemotionLicense: true,
    style: { width: '100%' },
  }))
}

onMounted(() => {
  root = createRoot(host.value)
  draw()
})
watch(() => [props.spec, props.clipStyle], draw, { deep: true })
onBeforeUnmount(() => {
  root?.unmount()
  root = null
})
</script>

<style scoped>
.remotion-preview { width: 100%; aspect-ratio: 9 / 16; background: #000; border-radius: 10px; overflow: hidden; }
</style>

```
