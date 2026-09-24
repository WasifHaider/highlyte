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
