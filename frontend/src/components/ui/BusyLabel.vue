<template>
  <span class="busy-label">
    <span class="cell" :aria-hidden="busy ? 'true' : undefined">{{ idle }}</span>
    <span class="cell busy-cell" :aria-hidden="busy ? undefined : 'true'">
      <UiSpinner v-if="busy" :size="spinnerSize" />{{ busyText }}
    </span>
  </span>
</template>

<script setup>
// A button's label that swaps to a spinner + busy text without changing the
// button's width. Both states are stacked in the same CSS grid cell (one
// `visibility: hidden` at a time), so the grid track's auto size is always
// the max of the two — the button never grows or shrinks when it toggles,
// with no min-width guess needed.
import UiSpinner from './UiSpinner.vue'

defineProps({
  busy: { type: Boolean, default: false },
  idle: { type: String, required: true },
  busyText: { type: String, required: true },
  spinnerSize: { type: [Number, String], default: 13 },
})
</script>

<style scoped>
.busy-label { display: inline-grid; }
.busy-label .cell {
  grid-area: 1 / 1;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  white-space: nowrap;
}
.busy-label .cell[aria-hidden="true"] { visibility: hidden; pointer-events: none; }
</style>
