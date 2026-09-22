<template>
  <div class="topbar">
    <div class="topbar-inner">
      <router-link to="/" class="brand">Highlyte</router-link>
      <input
        v-model="url"
        type="text"
        placeholder="Paste a YouTube link"
        @keyup.enter="onGenerate"
      />
      <button :disabled="submitting || !url" @click="onGenerate">
        {{ submitting ? 'Starting…' : 'Generate' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useJobStore } from '../stores/jobStore'

const url = ref('')
const submitting = ref(false)
const router = useRouter()
const jobStore = useJobStore()

async function onGenerate() {
  if (!url.value || submitting.value) return
  submitting.value = true
  try {
    const jobId = await jobStore.submitUrl(url.value)
    router.push({ name: 'job', params: { id: jobId } })
  } catch (e) {
    jobStore.error = e?.message || 'Failed to start job'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(250,246,239,0.92);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--border);
}
.topbar-inner {
  max-width: 800px;
  margin: 0 auto;
  padding: 16px 24px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.brand {
  flex-shrink: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ink);
  text-decoration: none;
}
input {
  flex: 1;
  min-width: 220px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--ink);
  outline: none;
}
button {
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  color: #fff;
  background: var(--accent);
}
button:disabled {
  cursor: default;
  background: rgba(212,112,58,0.55);
}
</style>
