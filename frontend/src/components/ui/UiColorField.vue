<template>
  <div class="ui-color" :class="{ open, disabled }">
    <button
      ref="triggerEl"
      type="button"
      class="ui-color-trigger"
      :disabled="disabled"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :aria-label="labelledby ? undefined : ariaLabel"
      :aria-labelledby="triggerLabelledby"
      @click="toggle"
      @keydown="onTriggerKey"
    >
      <span class="ui-color-swatch" :style="{ background: modelValue }"></span>
      <span :id="valueId" class="ui-color-hex mono">{{ modelValue }}</span>
      <svg class="ui-color-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <Teleport to="body">
      <Transition name="pop">
        <div v-if="open" ref="layerEl" class="ui-color-popover" :class="{ up: openUp }" :style="popoverStyle" role="dialog" tabindex="-1" :aria-labelledby="labelledby" @keydown="onPopoverKey">
          <div class="ui-color-grid">
            <button
              v-for="hex in ACCENT_PRESETS"
              :key="hex"
              type="button"
              class="ui-color-preset"
              :class="{ current: sameColor(hex, modelValue) }"
              :style="{ background: hex }"
              :aria-label="hex"
              @click="choose(hex)"
            ></button>
          </div>
          <hr class="ui-color-divider" />
          <div class="ui-color-custom-wrap">
            <button type="button" class="ui-color-custom" @click="openCustom">
              <span class="ui-color-swatch" :style="{ background: modelValue }"></span>
              <span>Custom colour&hellip;</span>
            </button>
            <input
              ref="customInput"
              type="color"
              class="ui-color-native"
              :value="modelValue"
              tabindex="-1"
              @input="onCustomInput"
            />
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useFloating } from './useFloating'
import { ACCENT_PRESETS } from '../../utils/clipStyle'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: undefined },
  labelledby: { type: String, default: undefined },
})
const emit = defineEmits(['update:modelValue'])

const { open, openUp, style, triggerEl, layerEl, show: showFloating, close } = useFloating()
const customInput = ref(null)

const uid = Math.random().toString(36).slice(2, 8)
const valueId = `ui-color-${uid}-value`
// Screen readers otherwise only hear the field name (aria-label); pairing it
// with the hex value span announces "<label>, <current value>" instead.
const triggerLabelledby = computed(() => (props.labelledby ? `${props.labelledby} ${valueId}` : undefined))

// The popover has a fixed 212px content width; useFloating's clamp still
// needs that number to keep the right edge on-screen before the layer has
// rendered once (it remeasures against the real element after that).
const popoverStyle = computed(() => ({ ...style, width: '212px' }))

function sameColor(a, b) {
  return (a || '').toLowerCase() === (b || '').toLowerCase()
}

async function show() {
  if (props.disabled) return
  await showFloating()
  layerEl.value?.focus()
}

function toggle() {
  open.value ? close() : show()
}

function choose(hex) {
  if (!sameColor(hex, props.modelValue)) emit('update:modelValue', hex)
  close()
}

function openCustom() {
  customInput.value?.click()
}

function onCustomInput(e) {
  emit('update:modelValue', e.target.value)
}

function onTriggerKey(e) {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
    e.preventDefault()
    show()
  }
}

function onPopoverKey(e) {
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close() }
  else if (e.key === 'Tab') {
    // Tab only needs handling at the popover's edges (first preset going
    // backward, the custom-colour button going forward) — internal Tabs
    // between presets should move normally. Don't preventDefault: refocusing
    // the trigger synchronously here (before the browser runs Tab's default
    // action) means the default action then continues from the trigger's
    // position in the page instead of falling off the end of <body> (the
    // teleported popover's real DOM location).
    const focusables = layerEl.value?.querySelectorAll('button') || []
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const leaving = e.shiftKey ? e.target === first : e.target === last
    if (leaving) close()
  }
}
</script>

<style scoped>
.ui-color { position: relative; min-width: 0; }
.ui-color-trigger {
  width: 100%; height: 36px; display: flex; align-items: center; gap: 8px;
  padding: 0 10px 0 12px; background: #fff; color: var(--ink); border: 1px solid var(--border); border-radius: var(--radius);
  font: 400 13.5px var(--font-sans); cursor: pointer; text-align: left;
  transition: border-color var(--ease), box-shadow var(--ease), background var(--ease);
}
.ui-color-trigger:hover:not(:disabled) { border-color: var(--ink-faint); }
.ui-color-trigger:focus-visible, .open .ui-color-trigger { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.ui-color-trigger:disabled { background: var(--bg-subtle); color: var(--ink-faint); cursor: not-allowed; }
.ui-color-swatch {
  flex-shrink: 0; width: 18px; height: 18px; border-radius: 50%;
  box-shadow: inset 0 0 0 1px rgba(20, 32, 31, .16);
}
.ui-color-hex { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--ink-soft); text-transform: uppercase; }
.ui-color-chevron { flex-shrink: 0; color: var(--ink-soft); transition: transform 160ms ease-out; }
.open .ui-color-chevron { transform: rotate(180deg); }
.ui-color-popover {
  position: fixed; z-index: 70; padding: 10px;
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  box-shadow: 0 8px 24px rgba(20, 32, 31, .10), 0 1px 2px rgba(0,0,0,.04); outline: none;
  transform-origin: top left;
}
.ui-color-popover.up { transform-origin: bottom left; }
.ui-color-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; justify-items: center; }
.ui-color-preset {
  width: 32px; height: 32px; border-radius: 50%; border: none; cursor: pointer; padding: 0;
  box-shadow: inset 0 0 0 1px rgba(20, 32, 31, .12);
  transition: box-shadow var(--ease);
}
.ui-color-preset:hover { box-shadow: inset 0 0 0 1px rgba(20, 32, 31, .12), 0 0 0 2px var(--accent-soft); }
.ui-color-preset.current { box-shadow: 0 0 0 2px #fff, 0 0 0 4px var(--accent); }
.ui-color-divider { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
.ui-color-custom-wrap { position: relative; }
.ui-color-custom {
  width: 100%; display: flex; align-items: center; gap: 8px;
  height: 34px; padding: 0 8px; border: none; background: transparent; border-radius: 6px;
  font-size: 13px; color: var(--ink); cursor: pointer; text-align: left;
}
.ui-color-custom:hover { background: var(--bg-subtle); }
.ui-color-native {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
.mono { font-family: monospace; }
</style>
