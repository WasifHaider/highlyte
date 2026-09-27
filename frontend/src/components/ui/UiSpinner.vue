<template>
  <svg
    class="ui-spinner"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    aria-hidden="true"
  ><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>
</template>

<script setup>
defineProps({
  size: { type: [Number, String], default: 14 },
})
</script>

<style scoped>
.ui-spinner { animation: spin .8s linear infinite; flex-shrink: 0; }
</style>
