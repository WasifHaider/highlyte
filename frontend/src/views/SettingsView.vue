<template>
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">Settings</h1>
      <p class="sub muted">{{ auth.me?.user.email }}</p>
    </div>

    <div class="section">
      <h2 class="section-title">My Groq key</h2>
      <p class="muted sub-note">
        Used to pick and caption your clips. Get a free key at
        <a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com/keys</a>.
      </p>
      <form class="add-user" @submit.prevent="save">
        <label class="field">
          <span class="field-label">Groq API key</span>
          <input v-model.trim="groqKey" type="password" class="input" placeholder="gsk_…" autocomplete="off" />
        </label>
        <button type="submit" class="btn btn-primary" :disabled="saving">
          <BusyLabel :busy="saving" idle="Save" busy-text="Saving…" />
        </button>
      </form>
      <Transition name="fade">
        <div v-if="error" class="danger-note" role="alert">{{ error }}</div>
      </Transition>
      <Transition name="fade">
        <div v-if="saved" class="state-msg" role="status">Saved.</div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, ref } from 'vue'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'
import BusyLabel from '../components/ui/BusyLabel.vue'

const SAVED_MESSAGE_MS = 2000

const auth = useAuthStore()
const groqKey = ref(auth.me?.groqKey || '')
const saving = ref(false)
const error = ref('')
const saved = ref(false)
let savedTimer = null

async function save() {
  error.value = ''
  saving.value = true
  try {
    await auth.setGroqKey(groqKey.value)
    saved.value = true
    clearTimeout(savedTimer)
    savedTimer = setTimeout(() => { saved.value = false }, SAVED_MESSAGE_MS)
  } catch (e) {
    error.value = apiErrorMessage(e, "Couldn't save your Groq key.")
  } finally {
    saving.value = false
  }
}

onUnmounted(() => clearTimeout(savedTimer))
</script>

<style scoped>
.page { max-width: 760px; }
.page-head .sub { margin: 6px 0 0; }
.section { margin-top: 32px; }

.sub-note { margin: 6px 0 0; font-size: 13px; }
.add-user { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin-top: 16px; }
.field { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 5px; }
.field .input { width: 100%; }

.danger-note { margin-top: 10px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 10px 0 0; }
</style>
