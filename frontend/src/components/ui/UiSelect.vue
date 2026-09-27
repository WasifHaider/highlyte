<template>
  <div class="ui-select" :class="{ open, disabled }">
    <button
      :id="id"
      ref="triggerEl"
      type="button"
      class="ui-select-trigger"
      :disabled="disabled"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-label="ariaLabel"
      @click="toggle"
      @keydown="onTriggerKey"
    >
      <span class="ui-select-value">{{ selected?.label ?? '' }}</span>
      <svg class="ui-select-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <Teleport to="body">
      <Transition name="pop">
        <ul
          v-if="open"
          ref="layerEl"
          class="ui-select-list"
          :class="{ up: openUp }"
          :style="style"
          role="listbox"
          tabindex="-1"
          :aria-activedescendant="activeId"
          @keydown="onListKey"
        >
          <li
            v-for="(opt, i) in options"
            :id="optionId(i)"
            :key="opt.value"
            role="option"
            class="ui-select-option"
            :class="{ active: i === active, selected: opt.value === modelValue, disabled: opt.disabled }"
            :aria-selected="opt.value === modelValue"
            :aria-disabled="!!opt.disabled"
            @mouseenter="!opt.disabled && (active = i)"
            @mousedown.prevent
            @click="choose(opt)"
          >
            <span class="ui-select-option-label">{{ opt.label }}</span>
            <svg v-if="opt.value === modelValue" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
          </li>
        </ul>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useFloating } from './useFloating'

const props = defineProps({
  modelValue: { type: [String, Number], default: null },
  options: { type: Array, required: true }, // [{ value, label, disabled? }]
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: undefined },
  id: { type: String, default: undefined },
})
const emit = defineEmits(['update:modelValue'])

const uid = Math.random().toString(36).slice(2, 8)
const { open, openUp, style, triggerEl, layerEl, show: showFloating, close } = useFloating()
const active = ref(-1)

const selected = computed(() => props.options.find(o => o.value === props.modelValue))
const optionId = i => `ui-select-${uid}-${i}`
const activeId = computed(() => (active.value >= 0 ? optionId(active.value) : undefined))

async function show() {
  if (props.disabled) return
  const idx = props.options.findIndex(o => o.value === props.modelValue)
  active.value = idx >= 0 ? idx : firstEnabled(0, 1)
  await showFloating()
  layerEl.value?.focus()
  layerEl.value?.querySelector('.active')?.scrollIntoView({ block: 'nearest' })
}

function toggle() {
  open.value ? close() : show()
}

function choose(opt) {
  if (opt.disabled) return
  if (opt.value !== props.modelValue) emit('update:modelValue', opt.value)
  close()
}

function firstEnabled(from, step) {
  for (let i = from; i >= 0 && i < props.options.length; i += step) {
    if (!props.options[i].disabled) return i
  }
  return -1
}

function move(step) {
  const next = firstEnabled(active.value + step, step)
  if (next !== -1) active.value = next
  nextTick(() => layerEl.value?.querySelector('.active')?.scrollIntoView({ block: 'nearest' }))
}

function onTriggerKey(e) {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
    e.preventDefault()
    show()
  }
}

function onListKey(e) {
  if (e.key === 'ArrowDown') { e.preventDefault(); move(1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
  else if (e.key === 'Home') { e.preventDefault(); active.value = firstEnabled(0, 1) }
  else if (e.key === 'End') { e.preventDefault(); active.value = firstEnabled(props.options.length - 1, -1) }
  else if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    const opt = props.options[active.value]
    if (opt) choose(opt)
  } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close() }
  else if (e.key === 'Tab') close(false)
}
</script>

<style scoped>
.ui-select { position: relative; min-width: 0; }
.ui-select-trigger {
  width: 100%; height: 36px; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 0 10px 0 12px; background: #fff; color: var(--ink); border: 1px solid var(--border); border-radius: var(--radius);
  font: 400 13.5px var(--font-sans); cursor: pointer; text-align: left;
  transition: border-color var(--ease), box-shadow var(--ease), background var(--ease);
}
.ui-select-trigger:hover:not(:disabled) { border-color: var(--ink-faint); }
.ui-select-trigger:focus-visible, .open .ui-select-trigger { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.ui-select-trigger:disabled { background: var(--bg-subtle); color: var(--ink-faint); cursor: not-allowed; }
.ui-select-value { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-select-chevron { flex-shrink: 0; color: var(--ink-soft); transition: transform 160ms ease-out; }
.open .ui-select-chevron { transform: rotate(180deg); }
.ui-select-list {
  position: fixed; z-index: 70; margin: 0; padding: 4px; list-style: none;
  width: max-content; max-width: min(320px, calc(100vw - 16px));
  max-height: 240px; overflow-y: auto; background: #fff; border: 1px solid var(--border);
  border-radius: 10px; box-shadow: 0 8px 24px rgba(20, 32, 31, .10), 0 1px 2px rgba(0,0,0,.04); outline: none;
  transform-origin: top center;
}
.ui-select-list.up { transform-origin: bottom center; }
.ui-select-option {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0;
  padding: 8px 10px; border-radius: 6px; font-size: 13.5px; color: var(--ink); cursor: pointer; white-space: nowrap;
}
.ui-select-option-label { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ui-select-option.active { background: var(--bg-subtle); }
.ui-select-option.selected { color: var(--accent-text); font-weight: 600; }
.ui-select-option.disabled { color: var(--ink-faint); cursor: not-allowed; background: none; }
</style>
