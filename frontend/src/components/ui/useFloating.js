import { nextTick, onBeforeUnmount, reactive, ref } from 'vue'

// Shared open/position/outside-click/scroll-dismiss logic for the floating
// layers (UiSelect's listbox, UiColorField's popover). Both render their
// layer through <Teleport to="body"> so it can escape the edit panel's
// `overflow-y: auto` (which computes overflow-x to auto too, clipping any
// panel-relative absolutely-positioned popover). Positioning is therefore
// `position: fixed`, computed from the trigger's own getBoundingClientRect()
// rather than CSS anchoring.
const VIEWPORT_MARGIN = 8
const OPEN_UP_THRESHOLD = 240

export function useFloating() {
  const open = ref(false)
  const openUp = ref(false)
  const triggerEl = ref(null)
  const layerEl = ref(null)
  const style = reactive({ left: '0px', top: 'auto', bottom: 'auto', minWidth: '0px' })

  function computePosition() {
    const trigger = triggerEl.value
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    openUp.value = window.innerHeight - rect.bottom < OPEN_UP_THRESHOLD && rect.top > OPEN_UP_THRESHOLD

    // Before the layer itself has rendered (first paint of `show()`) we don't
    // know its real width yet, so fall back to the trigger's width; once
    // mounted we remeasure against the actual layer for the right-edge clamp.
    const layerWidth = layerEl.value?.getBoundingClientRect().width || rect.width
    const maxLeft = Math.max(VIEWPORT_MARGIN, window.innerWidth - VIEWPORT_MARGIN - layerWidth)
    const left = Math.min(Math.max(rect.left, VIEWPORT_MARGIN), maxLeft)

    style.left = `${left}px`
    style.minWidth = `${rect.width}px`
    if (openUp.value) {
      style.bottom = `${window.innerHeight - rect.top + 4}px`
      style.top = 'auto'
    } else {
      style.top = `${rect.bottom + 4}px`
      style.bottom = 'auto'
    }
  }

  function isInside(target) {
    return !!(triggerEl.value?.contains(target) || layerEl.value?.contains(target))
  }

  function onOutside(e) {
    if (!isInside(e.target)) close(false)
  }

  function onScroll(e) {
    // Scrolling *inside* the layer itself (a long option list) must not
    // dismiss it; scrolling any other ancestor should. `scroll` doesn't
    // bubble, so this is registered on the capture phase of window, which
    // still observes it on the way down regardless of where it originated.
    if (layerEl.value?.contains(e.target)) return
    close(false)
  }

  function onResize() {
    close(false)
  }

  function addGlobalListeners() {
    document.addEventListener('pointerdown', onOutside, true)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
  }

  function removeGlobalListeners() {
    document.removeEventListener('pointerdown', onOutside, true)
    window.removeEventListener('scroll', onScroll, true)
    window.removeEventListener('resize', onResize)
  }

  async function show() {
    if (open.value) return
    open.value = true
    computePosition()
    addGlobalListeners()
    await nextTick()
    computePosition()
  }

  function close(refocus = true) {
    if (!open.value) return
    open.value = false
    removeGlobalListeners()
    if (refocus) triggerEl.value?.focus()
  }

  function toggle() {
    open.value ? close() : show()
  }

  onBeforeUnmount(removeGlobalListeners)

  return { open, openUp, style, triggerEl, layerEl, show, close, toggle }
}
