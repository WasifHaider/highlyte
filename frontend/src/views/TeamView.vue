<template>
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">Team</h1>
      <p class="sub muted">{{ auth.me?.team.name }} · add the people who should share these projects.</p>
    </div>

    <div class="section">
      <h2 class="section-title">Team members</h2>
      <div v-if="loading" class="state-msg">Loading…</div>
      <div v-else-if="listError" class="state-msg error">{{ listError }}</div>
      <table v-else class="members">
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Joined</th>
            <th class="col-action"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td class="cell-email" data-label="Email">{{ u.email }}</td>
            <td data-label="Role">
              <span class="chip" :class="{ 'chip-accent': u.role === 'admin' }">{{ u.role === 'admin' ? 'Admin' : 'User' }}</span>
            </td>
            <td class="cell-joined faint tabular" data-label="Joined">{{ relativeTime(u.createdAt) }}</td>
            <td class="col-action">
              <button v-if="u.role !== 'admin'" type="button" class="btn btn-ghost btn-sm" :disabled="removingId === u.id" @click="remove(u)">Remove</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2 class="section-title">Add a user</h2>
      <form class="add-user" @submit.prevent="add">
        <label class="field">
          <span class="field-label">Email</span>
          <input v-model.trim="newEmail" type="email" class="input" placeholder="name@company.com" required />
        </label>
        <button type="submit" class="btn btn-primary" :disabled="adding">{{ adding ? 'Adding…' : 'Add user' }}</button>
      </form>
      <div v-if="addError" class="danger-note" role="alert">{{ addError }}</div>

      <div v-if="created" class="created card" role="status">
        <div class="created-title">User added</div>
        <div class="creds">
          <div><span>Email</span><code>{{ created.email }}</code></div>
          <div><span>Password</span><code>{{ created.password }}</code></div>
        </div>
        <div class="created-actions">
          <button type="button" class="btn btn-secondary btn-sm" @click="copyCreds">{{ copied ? 'Copied' : 'Copy login' }}</button>
          <button type="button" class="btn btn-ghost btn-sm" @click="closeCreated">Done</button>
        </div>
        <p class="subtle-note">This password is shown only once. Copy it now and send it to the user.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../stores/authStore'
import { addTeamUser, apiErrorMessage, listTeamUsers, removeTeamUser } from '../services/highlyteApi'
import { relativeTime } from '../utils/time'

const COPIED_MESSAGE_MS = 2000

const auth = useAuthStore()
const users = ref([])
const loading = ref(true)
const listError = ref('')
const newEmail = ref('')
const adding = ref(false)
const addError = ref('')
const created = ref(null) // { email, password } until the admin dismisses it
const copied = ref(false)
const removingId = ref(null)
let copiedTimer = null

async function load() {
  try {
    users.value = await listTeamUsers()
    listError.value = ''
  } catch (e) {
    listError.value = apiErrorMessage(e, "Couldn't load your team.")
  } finally {
    loading.value = false
  }
}

async function add() {
  addError.value = ''
  adding.value = true
  try {
    const result = await addTeamUser(newEmail.value)
    created.value = { email: result.user.email, password: result.password }
    users.value = [...users.value, result.user]
    newEmail.value = ''
  } catch (e) {
    addError.value = apiErrorMessage(e, "Couldn't add that user.")
  } finally {
    adding.value = false
  }
}

async function copyCreds() {
  await navigator.clipboard.writeText(`Email: ${created.value.email}\nPassword: ${created.value.password}`)
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, COPIED_MESSAGE_MS)
}

// The password is never retrievable again, so dropping it here is final.
function closeCreated() {
  created.value = null
  copied.value = false
}

async function remove(user) {
  if (!window.confirm(`Remove ${user.email}? They won't be able to log in.`)) return
  removingId.value = user.id
  try {
    await removeTeamUser(user.id)
    users.value = users.value.filter(u => u.id !== user.id)
  } catch (e) {
    listError.value = apiErrorMessage(e, "Couldn't remove that user.")
  } finally {
    removingId.value = null
  }
}

onMounted(load)
onUnmounted(() => clearTimeout(copiedTimer))
</script>

<style scoped>
.page { max-width: 760px; }
.page-head .sub { margin: 6px 0 0; }
.section { margin-top: 40px; }
.section:first-of-type { margin-top: 32px; }

.members { width: 100%; border-collapse: collapse; margin-top: 16px; }
.members th {
  text-align: left; font-size: 12.5px; font-weight: 500; color: var(--ink-faint);
  padding: 0 0 10px; border-bottom: 1px solid var(--border);
}
.members td { padding: 12px 0; border-bottom: 1px solid var(--border); font-size: 14px; vertical-align: middle; }
.members tr:last-child td { border-bottom: none; }
.cell-email { font-size: 14px; font-weight: 500; }
.cell-joined { font-size: 13px; }
.col-action { text-align: right; width: 1%; white-space: nowrap; }

.add-user { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin-top: 16px; }
.field { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 5px; }
.field .input { width: 100%; }

.danger-note { margin-top: 10px; }

.created { margin-top: 18px; padding: 16px 18px; }
.created-title { font-weight: 600; margin-bottom: 10px; }
.creds { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.creds span { display: inline-block; width: 80px; color: var(--ink-soft); }
.creds code { font-size: 14px; background: var(--accent-soft); padding: 2px 8px; border-radius: 6px; }
.created-actions { display: flex; gap: 8px; margin-top: 12px; }
.created .subtle-note { margin-top: 10px; }

.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: var(--danger); }

@media (max-width: 480px) {
  .members thead { display: none; }
  .members, .members tbody, .members tr, .members td { display: block; width: 100%; }
  .members tr { padding: 12px 0; border-bottom: 1px solid var(--border); }
  .members td { padding: 2px 0; border-bottom: none; }
  .cell-joined { display: inline-block; margin-top: 6px; margin-right: 10px; }
  td[data-label="Role"] { display: inline-block; margin-top: 6px; }
  .col-action { text-align: left; margin-top: 8px; }
}
</style>
