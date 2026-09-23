<template>
  <div class="clip-row" :class="{ playing: isPlaying }">
    <div class="checkbox" :class="{ checked: isSelected }" @click="$emit('toggle')">
      <span v-if="isSelected">✓</span>
    </div>

    <div class="play-btn" :class="{ playing: isPlaying }" @click="$emit('play')">
      <div class="play-icon"></div>
    </div>

    <div class="clip-body">
      <div class="clip-meta-row">
        <span class="clip-range">{{ clip.startLabel }} – {{ clip.endLabel }}</span>
        <span class="clip-duration">{{ clip.durationLabel }}</span>
        <span class="clip-tag">{{ clip.tag }}</span>
      </div>
      <div class="clip-snippet">"{{ snippet }}"</div>
      <div class="waveform">
        <div v-for="(h, i) in waveform" :key="i" class="bar" :style="{ height: h + '%', animationDelay: (i * 0.04) + 's' }"></div>
      </div>
      <audio
        v-if="isPlaying"
        ref="audioEl"
        :src="downloadUrl"
        autoplay
        @ended="$emit('play')"
        class="native-audio"
        controls
      ></audio>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { clipDownloadUrl } from '../services/highlyteApi'

const props = defineProps({
  clip: { type: Object, required: true },
  isSelected: { type: Boolean, default: false },
  isPlaying: { type: Boolean, default: false },
})
defineEmits(['toggle', 'play'])

const snippet = computed(() => {
  const t = props.clip.text || ''
  return t.length > 220 ? t.slice(0, 217) + '…' : t
})

const downloadUrl = computed(() => clipDownloadUrl(props.clip.downloadUrl))

// Deterministic pseudo-waveform derived from clip id, purely decorative.
const waveform = computed(() => {
  const seed = [...(props.clip.id || '')].reduce((a, c) => a + c.charCodeAt(0), 0)
  const bars = []
  for (let i = 0; i < 18; i++) {
    const v = 30 + Math.abs(Math.sin(i * 0.7 + seed)) * 55 + Math.abs(Math.cos(i * 1.3 + seed * 2)) * 15
    bars.push(Math.round(Math.min(95, v)))
  }
  return bars
})
</script>

<style scoped>
.clip-row {
  display: flex; gap: 16px; align-items: flex-start;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px;
  transition: border-color .15s ease, background .15s ease;
}
.clip-row.playing { background: var(--accent-soft); border-color: var(--accent); }

.checkbox {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0; margin-top: 2px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: #fff; transition: all .15s ease;
  background: #fff; border: 1.5px solid var(--border);
}
.checkbox.checked { background: var(--accent); border-color: var(--accent); }

.play-btn {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all .15s ease; background: #fff; border: 1px solid var(--border);
}
.play-btn.playing { background: var(--accent); border-color: var(--accent); }
.play-icon {
  width: 0; height: 0; border-top: 6px solid transparent; border-bottom: 6px solid transparent;
  border-left: 9px solid var(--ink); margin-left: 2px;
}
.play-btn.playing .play-icon { width: 10px; height: 10px; background: #fff; border-radius: 2px; border: none; margin: 0; }

.clip-body { flex: 1; min-width: 0; }
.clip-meta-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.clip-range { font-family: monospace; font-size: 12.5px; color: var(--ink-soft); }
.clip-duration { font-size: 11px; color: var(--ink-faint); }
.clip-tag { background: var(--accent-soft); color: var(--accent-text); font-size: 11.5px; font-weight: 600; padding: 3px 10px; border-radius: 999px; }
.clip-snippet { margin-top: 9px; font-family: var(--font-serif); font-style: italic; font-size: 15.5px; line-height: 1.5; }
.waveform { margin-top: 12px; display: flex; align-items: flex-end; gap: 2.5px; height: 24px; }
.waveform .bar { width: 3px; border-radius: 2px; background: var(--border); }
.clip-row.playing .waveform .bar { background: var(--accent); animation: wavePulse .9s ease-in-out infinite; }
.native-audio { margin-top: 10px; width: 100%; height: 32px; }
</style>
