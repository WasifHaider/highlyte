<template>
  <Transition :name="isMobile ? 'slide-up' : 'slide-right'">
    <aside
      v-if="clip && clip.spec"
      class="edit-panel"
      aria-labelledby="edit-panel-title"
      :role="isMobile ? 'dialog' : undefined"
      :aria-modal="isMobile ? 'true' : undefined"
    >
      <div class="panel-inner">
        <div class="panel-header">
          <div class="panel-heading">
            <h2 id="edit-panel-title" class="panel-title">Edit clip</h2>
            <div class="panel-subtitle faint tabular">{{ clip.startLabel }}–{{ clip.endLabel }}</div>
            <Transition name="fade">
              <div v-if="saving" class="save-status faint" role="status">Saving…</div>
              <div v-else-if="showSaved" class="save-status faint" role="status">Saved</div>
            </Transition>
          </div>
          <button ref="closeBtn" class="close-btn" @click="jobStore.closeEditor()" aria-label="Close edit panel">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>

        <Transition name="fade" mode="out-in">
          <div class="panel-body" :key="clip.id">
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
              <label class="field" for="edit-layout-select">
                <span class="field-label">Layout</span>
                <UiSelect
                  id="edit-layout-select"
                  :model-value="clip.style.layout"
                  :options="layoutOptions"
                  :disabled="!!clip.pendingAction"
                  @update:model-value="v => set({ layout: v })"
                />
              </label>
              <label class="field" for="edit-captions-select">
                <span class="field-label">Captions</span>
                <UiSelect
                  id="edit-captions-select"
                  :model-value="clip.style.captionPreset"
                  :options="captionOptions"
                  :disabled="!!clip.pendingAction"
                  @update:model-value="v => set({ captionPreset: v })"
                />
              </label>
              <label class="field" for="edit-position-select">
                <span class="field-label">Position</span>
                <UiSelect
                  id="edit-position-select"
                  :model-value="clip.style.captionPosition"
                  :options="positionOptions"
                  :disabled="clip.style.layout === 'split' || !!clip.pendingAction"
                  @update:model-value="v => set({ captionPosition: v })"
                />
              </label>
              <div class="field">
                <span class="field-label">Accent colour</span>
                <UiColorField
                  aria-label="Accent colour"
                  :model-value="clip.style.accent"
                  :disabled="!!clip.pendingAction"
                  @update:model-value="v => set({ accent: v })"
                />
              </div>
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
        </Transition>
      </div>
    </aside>
  </Transition>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useJobStore } from '../stores/jobStore'
import CaptionEditor from './CaptionEditor.vue'
import UiSelect from './ui/UiSelect.vue'
import UiColorField from './ui/UiColorField.vue'
import { LAYOUTS, PRESETS, layoutAllowed } from '../utils/clipStyle'
import { toClipTime } from '@renderer/lib/timeline'

const SAVED_MESSAGE_MS = 1500

const jobStore = useJobStore()
const clip = computed(() => jobStore.clips.find(c => c.id === jobStore.editingClipId))
const clipTime = computed(() => toClipTime(clip.value.spec))
const closeBtn = ref(null)

// Quiet "Saving…"/"Saved" feedback for style and trim changes, derived from
// the store's existing (debounced) save-tracking maps; purely additive, it
// doesn't touch save behaviour.
const saving = computed(() => !!clip.value && jobStore.savingClip(clip.value.id))
const showSaved = ref(false)
let savedTimer = null
watch(saving, (isSaving, wasSaving) => {
  clearTimeout(savedTimer)
  if (!isSaving && wasSaving) {
    showSaved.value = true
    savedTimer = setTimeout(() => { showSaved.value = false }, SAVED_MESSAGE_MS)
  } else {
    showSaved.value = false
  }
})
// A different clip's save state must not leak "Saved" onto the newly opened one.
watch(clip, () => {
  clearTimeout(savedTimer)
  showSaved.value = false
})

const layoutOptions = computed(() => LAYOUTS.map(l => ({
  value: l.value,
  label: l.label + (l.value === clipTime.value.reframe.auto ? ' (auto)' : ''),
  disabled: !layoutAllowed(l.value, clipTime.value.reframe),
})))
const captionOptions = PRESETS.map(p => ({ value: p.value, label: p.label }))
const positionOptions = [
  { value: 'lower', label: 'Lower third' },
  { value: 'middle', label: 'Middle' },
]

function set(patch) {
  jobStore.updateStyle(clip.value.id, patch)
}

function onKeydown(e) {
  if (e.key === 'Escape' && jobStore.editingClipId) jobStore.closeEditor()
}

// Below 1024px the panel is a full-screen sheet over the page, not a side
// column, so the page behind it must not scroll while it's open. Driven off
// a media query listener (not just a clip watcher) so resizing the viewport
// across the breakpoint while the sheet is open updates the lock too.
const mobileSheetQuery = window.matchMedia('(max-width: 1023px)')
const isMobile = ref(mobileSheetQuery.matches)
function updateScrollLock() {
  document.body.style.overflow = clip.value && mobileSheetQuery.matches ? 'hidden' : ''
}
function updateIsMobile() {
  isMobile.value = mobileSheetQuery.matches
}

// The triggering Edit button (ClipCard) is whatever had focus right before
// the panel opened; storing it here lets close() hand focus back to it.
let previouslyFocused = null

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  mobileSheetQuery.addEventListener('change', updateScrollLock)
  mobileSheetQuery.addEventListener('change', updateIsMobile)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  mobileSheetQuery.removeEventListener('change', updateScrollLock)
  mobileSheetQuery.removeEventListener('change', updateIsMobile)
  document.body.style.overflow = ''
  clearTimeout(savedTimer)
})

watch(clip, (newClip, oldClip) => {
  updateScrollLock()
  if (newClip && !oldClip) {
    previouslyFocused = document.activeElement
    nextTick(() => closeBtn.value?.focus())
  } else if (!newClip && oldClip) {
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }
}, { immediate: true })
</script>

<style scoped>
.edit-panel {
  /* Wide enough that two-column selects and caption lines aren't truncated. */
  width: clamp(380px, 34vw, 460px); flex-shrink: 0; margin-left: auto; border-left: 1px solid var(--border); background: #fff;
  position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto;
}
.panel-inner { padding: 24px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; }
.panel-title { font-size: 15px; font-weight: 600; margin: 0; }
.panel-subtitle { font-size: 12.5px; margin-top: 4px; }
.save-status { font-size: 12px; margin-top: 4px; }
.close-btn {
  border: none; background: transparent; color: var(--ink-faint); cursor: pointer; padding: 2px;
  display: inline-flex; align-items: center; justify-content: center;
}
.close-btn:hover { color: var(--ink); }
.panel-body { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
/* The outgoing clip's fields fade out under the incoming ones during the
   cross-fade; block clicks on them so a stray click can't land on a field
   that belongs to the clip already being replaced. */
.panel-body.fade-leave-active { pointer-events: none; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; width: 100%; }
.field-label { font-size: 12.5px; font-weight: 500; }
.check { display: flex; align-items: center; gap: 8px; font-size: 12.5px; margin-top: -12px; }
.grid-2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.approx-note { font-size: 12px; }
.divider { border: none; border-top: 1px solid var(--border); margin: 0; }
/* CSS-only disable: a pending swap/regenerate is blocked here by dimming and
   swallowing clicks. CaptionEditor also closes itself when the action starts
   (its `pending` prop), so it is never left open and unreachable. */
.controls-disabled { opacity: .6; pointer-events: none; }

@media (max-width: 1023px) {
  .edit-panel {
    position: fixed; inset: 0; top: 0; width: 100%;
    height: 100vh; height: 100dvh;
    z-index: 60; border-left: none;
  }
}
</style>
