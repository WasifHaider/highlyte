<template>
  <div class="processing-card">
    <div class="processing-title">Processing your episode</div>
    <div class="steps">
      <div class="step" v-for="step in steps" :key="step.key">
        <div class="row">
          <div class="step-marker" :class="step.state">
            <span v-if="step.state === 'done'" class="check">✓</span>
            <span v-else-if="step.state === 'active'" class="dot"></span>
          </div>
          <span class="step-label" :class="step.state">{{ step.label }}</span>
          <span v-if="step.state === 'active' && progressText" class="step-progress-text tabular">{{ progressText }}</span>
        </div>
        <div v-if="step.state === 'active' && progress.percent != null" class="progress-bar">
          <div class="progress-bar-fill" :style="{ width: Math.min(100, progress.percent) + '%' }"></div>
        </div>
        <div v-if="step.state === 'active' && progress.latestText" class="step-progress-quote">"{{ progress.latestText }}"</div>
      </div>
    </div>
    <p class="processing-hint">This takes a few minutes on CPU: every clip gets word-timed captions and face tracking.</p>
    <p class="processing-hint">You can leave this page; we will keep working.</p>
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

// Same progress logic as before (note + percent + latestText), just
// formatted into a single right-aligned string for the active row.
const progressText = computed(() => {
  const note = props.progress?.note || ''
  const percent = props.progress?.percent
  if (note && percent != null) return `${note} ${Math.min(100, Math.round(percent))}%`
  if (note) return note
  if (percent != null) return `${Math.min(100, Math.round(percent))}%`
  return ''
})
</script>

<style scoped>
.processing-card { padding: 8px 0 0; }
.processing-title { font-size: 15px; font-weight: 600; margin-bottom: 24px; }
.steps { display: flex; flex-direction: column; gap: 12px; }
.step { display: flex; flex-direction: column; }
.row { display: flex; align-items: center; gap: 12px; min-height: 44px; }
.step-marker {
  width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.step-marker.pending { border: 1px solid var(--border); background: #fff; }
.step-marker.active { border: 2px solid var(--accent); background: #fff; animation: softPulse 1.6s ease-in-out infinite; }
.step-marker.active .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.step-marker.done { background: var(--accent); border: 1px solid var(--accent); }
.step-marker.done .check { color: #fff; font-size: 11px; line-height: 1; }
.step-label { font-size: 14px; flex: 1; min-width: 0; }
.step-label.pending { color: var(--ink-faint); }
.step-label.active, .step-label.done { color: var(--ink); }
.step-progress-text { font-size: 12.5px; color: var(--ink-soft); flex-shrink: 0; }
.progress-bar {
  margin-left: 32px; margin-top: 2px;
  height: 4px; border-radius: 2px; background: var(--border); overflow: hidden;
}
.progress-bar-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
.step-progress-quote {
  margin-left: 32px; margin-top: 4px;
  font-size: 12px; color: var(--ink-faint); font-style: italic;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.processing-hint { margin-top: 24px; margin-bottom: 0; font-size: 12.5px; color: var(--ink-faint); }
.processing-hint + .processing-hint { margin-top: 4px; }
</style>
