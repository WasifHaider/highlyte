<template>
  <aside v-if="clip && clip.spec" class="edit-panel">
    <div class="panel-inner">
      <div class="panel-header">
        <div class="panel-heading">
          <h2 class="panel-title">Edit clip</h2>
          <div class="panel-subtitle faint tabular">{{ clip.startLabel }}–{{ clip.endLabel }}</div>
        </div>
        <button class="close-btn" @click="jobStore.closeEditor()" aria-label="Close edit panel">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>

      <div class="panel-body">
        <label class="field">
          <span class="field-label">Hook title</span>
          <input type="text" class="input" :value="clip.style.hookTitle || ''" maxlength="80" :disabled="!!clip.pendingAction"
            @input="set({ hookTitle: $event.target.value || null })" />
        </label>
        <label class="check">
          <input type="checkbox" :checked="clip.style.showHook" :disabled="!!clip.pendingAction" @change="set({ showHook: $event.target.checked })" />
          <span class="muted">Show hook title</span>
        </label>

        <div class="grid-2">
          <label class="field">
            <span class="field-label">Layout</span>
            <select class="select" :value="clip.style.layout" :disabled="!!clip.pendingAction" @change="set({ layout: $event.target.value })">
              <option v-for="l in LAYOUTS" :key="l.value" :value="l.value" :disabled="!layoutAllowed(l.value, clipTime.reframe)">
                {{ l.label }}{{ l.value === clipTime.reframe.auto ? ' (auto)' : '' }}
              </option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">Captions</span>
            <select class="select" :value="clip.style.captionPreset" :disabled="!!clip.pendingAction" @change="set({ captionPreset: $event.target.value })">
              <option v-for="p in PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">Position</span>
            <select class="select" :value="clip.style.captionPosition" :disabled="clip.style.layout === 'split' || !!clip.pendingAction"
              @change="set({ captionPosition: $event.target.value })">
              <option value="lower">Lower third</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">Accent colour</span>
            <div class="accent-box">
              <input type="color" :value="clip.style.accent" :disabled="!!clip.pendingAction" @input="set({ accent: $event.target.value })" />
              <span class="accent-hex mono">{{ clip.style.accent }}</span>
            </div>
          </label>
        </div>

        <div v-if="clip.spec.wordsApprox" class="approx-note faint">Approximate caption sync</div>

        <hr class="divider" />

        <div :class="{ 'controls-disabled': clip.pendingAction }">
          <CaptionEditor :key="clip.id" :clip-id="clip.id" :words="clip.spec.words" :edited="!!clip.captionsEdited"
            :start="clip.spec.version === 2 ? clip.spec.start : null" :end="clip.spec.version === 2 ? clip.spec.end : null"
            :revision="clip.revision || 0" :pending="!!clip.pendingAction"
            @draft="w => jobStore.setCaptionDraft(clip.id, w)" />
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useJobStore } from '../stores/jobStore'
import CaptionEditor from './CaptionEditor.vue'
import { LAYOUTS, PRESETS, layoutAllowed } from '../utils/clipStyle'
import { toClipTime } from '@renderer/lib/timeline'

const jobStore = useJobStore()
const clip = computed(() => jobStore.clips.find(c => c.id === jobStore.editingClipId))
const clipTime = computed(() => toClipTime(clip.value.spec))

function set(patch) {
  jobStore.updateStyle(clip.value.id, patch)
}

function onKeydown(e) {
  if (e.key === 'Escape' && jobStore.editingClipId) jobStore.closeEditor()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

// Below 1024px the panel is a full-screen sheet over the page, not a side
// column, so the page behind it must not scroll while it's open.
watch(clip, (value) => {
  document.body.style.overflow = value && window.innerWidth < 1024 ? 'hidden' : ''
}, { immediate: true })
</script>

<style scoped>
.edit-panel {
  width: 320px; flex-shrink: 0; border-left: 1px solid var(--border); background: #fff;
  position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto;
}
.panel-inner { padding: 24px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; }
.panel-title { font-size: 15px; font-weight: 600; margin: 0; }
.panel-subtitle { font-size: 12.5px; margin-top: 4px; }
.close-btn {
  border: none; background: transparent; color: var(--ink-faint); cursor: pointer; padding: 2px;
  display: inline-flex; align-items: center; justify-content: center;
}
.close-btn:hover { color: var(--ink); }
.panel-body { display: flex; flex-direction: column; gap: 20px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 12.5px; font-weight: 500; }
.check { display: flex; align-items: center; gap: 8px; font-size: 12.5px; margin-top: -12px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.accent-box {
  display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 8px;
  border: 1px solid var(--border); border-radius: var(--radius); background: #fff;
}
.accent-box input[type="color"] { width: 20px; height: 20px; border-radius: 4px; border: none; padding: 0; cursor: pointer; }
.accent-hex { font-size: 12px; color: var(--ink-soft); text-transform: uppercase; }
.mono { font-family: monospace; }
.approx-note { font-size: 12px; }
.divider { border: none; border-top: 1px solid var(--border); margin: 0; }
/* CSS-only disable: a pending swap/regenerate is blocked here by dimming and
   swallowing clicks. CaptionEditor also closes itself when the action starts
   (its `pending` prop), so it is never left open and unreachable. */
.controls-disabled { opacity: .6; pointer-events: none; }

@media (max-width: 1023px) {
  .edit-panel {
    position: fixed; inset: 0; top: 0; height: 100vh; width: 100%;
    z-index: 60; border-left: none;
  }
}
</style>
