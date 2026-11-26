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

    <div class="section">
      <h2 class="section-title">Backup Groq key</h2>
      <p class="muted sub-note">
        Optional. A key from a second Groq account, used when your main key hits its daily limit.
        Groq's limits are per account, so another key from the same account doesn't help.
      </p>
      <form class="add-user" @submit.prevent="saveBackup">
        <label class="field">
          <span class="field-label">Backup Groq API key</span>
          <input v-model.trim="backupKey" type="password" class="input" placeholder="gsk_…" autocomplete="off" />
        </label>
        <button type="submit" class="btn btn-primary" :disabled="backupSaving">
          <BusyLabel :busy="backupSaving" idle="Save" busy-text="Saving…" />
        </button>
      </form>
      <Transition name="fade">
        <div v-if="backupError" class="danger-note" role="alert">{{ backupError }}</div>
      </Transition>
      <Transition name="fade">
        <div v-if="backupSaved" class="state-msg" role="status">Saved.</div>
      </Transition>
    </div>

    <div class="section">
      <h2 class="section-title">My brand kit</h2>
      <p class="muted sub-note">
        Your new clips start with these. You can still change any clip in its editor.
      </p>
      <form class="kit" @submit.prevent="saveKit">
        <div class="field">
          <span class="field-label" id="kit-accent-label">Accent colour</span>
          <UiColorField v-model="kit.accent" labelledby="kit-accent-label" />
        </div>
        <div class="field">
          <span class="field-label" id="kit-font-label">Font</span>
          <UiSelect v-model="kit.font" :options="FONTS" labelledby="kit-font-label" />
        </div>
        <div class="field">
          <span class="field-label" id="kit-progress-label">Progress bar</span>
          <UiSelect v-model="kit.progressBar" :options="PROGRESS_BARS" labelledby="kit-progress-label" />
        </div>
        <button type="submit" class="btn btn-primary" :disabled="kitSaving">
          <BusyLabel :busy="kitSaving" idle="Save" busy-text="Saving…" />
        </button>
      </form>
      <Transition name="fade">
        <div v-if="kitError" class="danger-note" role="alert">{{ kitError }}</div>
      </Transition>
      <Transition name="fade">
        <div v-if="kitSaved" class="state-msg" role="status">Saved. New clips will use it.</div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'
import BusyLabel from '../components/ui/BusyLabel.vue'
import UiColorField from '../components/ui/UiColorField.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import { DEFAULT_BRAND_KIT, FONTS, PROGRESS_BARS } from '../utils/clipStyle'

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

const backupKey = ref(auth.me?.groqBackupKey || '')
const backupSaving = ref(false)
const backupError = ref('')
const backupSaved = ref(false)
let backupSavedTimer = null

async function saveBackup() {
  backupError.value = ''
  backupSaving.value = true
  try {
    await auth.setGroqBackupKey(backupKey.value)
    backupSaved.value = true
    clearTimeout(backupSavedTimer)
    backupSavedTimer = setTimeout(() => { backupSaved.value = false }, SAVED_MESSAGE_MS)
  } catch (e) {
    backupError.value = apiErrorMessage(e, "Couldn't save your backup Groq key.")
  } finally {
    backupSaving.value = false
  }
}

const kit = reactive({ ...DEFAULT_BRAND_KIT, ...(auth.me?.brandKit || {}) })
const kitSaving = ref(false)
const kitError = ref('')
const kitSaved = ref(false)
let kitSavedTimer = null

async function saveKit() {
  kitError.value = ''
  kitSaving.value = true
  try {
    await auth.setBrandKit({ ...kit })
    kitSaved.value = true
    clearTimeout(kitSavedTimer)
    kitSavedTimer = setTimeout(() => { kitSaved.value = false }, SAVED_MESSAGE_MS)
  } catch (e) {
    kitError.value = apiErrorMessage(e, "Couldn't save your brand kit.")
  } finally {
    kitSaving.value = false
  }
}

onUnmounted(() => {
  clearTimeout(savedTimer)
  clearTimeout(backupSavedTimer)
  clearTimeout(kitSavedTimer)
})
</script>

<style scoped>
.page { max-width: 760px; }
.page-head .sub { margin: 6px 0 0; }
.section { margin-top: 32px; }

.sub-note { margin: 6px 0 0; font-size: 13px; }
.add-user { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin-top: 16px; }
.field { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 5px; }
.field .input { width: 100%; }
.kit { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)) auto; gap: 10px; align-items: end; margin-top: 16px; }
.kit .field { min-width: 0; }
@media (max-width: 720px) { .kit { grid-template-columns: 1fr; } }

.danger-note { margin-top: 10px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 10px 0 0; }
</style>
