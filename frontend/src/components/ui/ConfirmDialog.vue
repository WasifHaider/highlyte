<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="backdrop" @mousedown.self="cancel">
        <div ref="dialog" class="dialog card" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-body">
          <h2 id="confirm-title" class="title">{{ title }}</h2>
          <p id="confirm-body" class="body muted"><slot /></p>
          <p v-if="error" class="danger-note" role="alert">{{ error }}</p>
          <div class="actions">
            <button ref="cancelBtn" type="button" class="btn btn-secondary" :disabled="busy" @click="cancel">Cancel</button>
            <button type="button" class="btn confirm-btn" :class="{ danger }" :disabled="busy" @click="$emit('confirm')">
              <BusyLabel :busy="busy" :idle="confirmLabel" :busy-text="busyLabel" />
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'
import BusyLabel from './BusyLabel.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  confirmLabel: { type: String, default: 'Confirm' },
  busyLabel: { type: String, default: 'Working…' },
  danger: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['confirm', 'cancel'])

const dialog = ref(null)
const cancelBtn = ref(null)
let previouslyFocused = null

function cancel() {
  if (!props.busy) emit('cancel')
}

// Escape cancels; Tab stays inside the dialog.
function onKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    cancel()
  } else if (e.key === 'Tab' && dialog.value) {
    const items = [...dialog.value.querySelectorAll('button:not(:disabled)')]
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }
}

// Focus starts on Cancel so a stray Enter never deletes anything.
watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    previouslyFocused = document.activeElement
    window.addEventListener('keydown', onKeydown)
    await nextTick()
    cancelBtn.value?.focus()
  } else {
    window.removeEventListener('keydown', onKeydown)
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 100; background: rgba(16, 24, 24, 0.45);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}
.dialog { width: min(100%, 420px); padding: 22px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2); }
.title { margin: 0; font-size: 16px; font-weight: 600; }
.body { margin: 0; font-size: 13.5px; line-height: 1.5; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.confirm-btn { background: var(--accent); color: #fff; }
.confirm-btn.danger { background: var(--danger); }
.confirm-btn.danger:hover:not(:disabled) { background: #912018; }
</style>
