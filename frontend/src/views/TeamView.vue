<template>
  <div class="page">
    <div class="page-head">
      <h1>Team</h1>
      <p class="sub">{{ auth.me?.team.name }} · add the people who should share these projects.</p>
    </div>

    <form class="add-user" @submit.prevent="add">
      <label class="field">
        <span>Add a user by email</span>
        <input v-model.trim="newEmail" type="email" placeholder="name@company.com" required />
      </label>
      <button type="submit" :disabled="adding">{{ adding ? 'Adding…' : 'Add user' }}</button>
    </form>
    <div v-if="addError" class="error" role="alert">{{ addError }}</div>

    <div v-if="created" class="created" role="status">
      <div class="created-title">User added</div>
      <div class="creds">
        <div><span>Email</span><code>{{ created.email }}</code></div>
        <div><span>Password</span><code>{{ created.password }}</code></div>
      </div>
      <div class="created-actions">
        <button class="copy" @click="copyCreds">{{ copied ? 'Copied' : 'Copy login' }}</button>
        <button class="done" @click="closeCreated">Done</button>
      </div>
      <p class="warn">This password is shown only once. Copy it now and send it to the user.</p>
    </div>

    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="listError" class="state-msg error">{{ listError }}</div>
    <ul v-else class="members">
      <li v-for="u in users" :key="u.id" class="member">
        <div class="who">
          <span class="email">{{ u.email }}</span>
          <span class="badge" :class="u.role">{{ u.role === 'admin' ? 'Admin' : 'User' }}</span>
        </div>
        <span class="added">Added {{ relativeTime(u.createdAt) }}</span>
        <button v-if="u.role !== 'admin'" class="remove" :disabled="removingId === u.id" @click="remove(u)">Remove</button>
      </li>
    </ul>
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
.page { max-width: 760px; margin: 0 auto; padding: 40px 24px 120px; }
.page-head h1 { font-family: var(--font-serif); font-size: 28px; font-weight: 500; margin: 0; }
.sub { font-size: 13.5px; color: var(--ink-soft); margin: 6px 0 24px; }
.add-user { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.field { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--ink-soft); }
.field input {
  font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; background: #fff;
}
button {
  border: none; border-radius: 8px; padding: 10px 16px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
button[disabled] { opacity: .6; cursor: default; }
.error { margin-top: 10px; background: #FBEAE3; border: 1px solid #E8B79E; color: #9C3B14; border-radius: 8px; padding: 9px 12px; font-size: 13px; }
.created { margin-top: 18px; background: var(--surface); border: 1px solid var(--accent); border-radius: 12px; padding: 16px 18px; }
.created-title { font-weight: 600; margin-bottom: 10px; }
.creds { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.creds span { display: inline-block; width: 80px; color: var(--ink-soft); }
.creds code { font-size: 14px; background: var(--accent-soft); padding: 2px 8px; border-radius: 6px; }
.created-actions { display: flex; gap: 8px; margin-top: 12px; }
.created-actions .done { background: #fff; color: var(--ink); border: 1px solid var(--border); }
.warn { margin: 10px 0 0; font-size: 12.5px; color: #8A5A00; }
.members { list-style: none; padding: 0; margin: 28px 0 0; display: flex; flex-direction: column; gap: 8px; }
.member {
  display: flex; align-items: center; gap: 12px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px;
}
.who { flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; }
.email { font-size: 14px; overflow: hidden; text-overflow: ellipsis; }
.badge { font-size: 11.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-text); }
.badge.admin { background: #FFF4D6; color: #8A5A00; }
.added { font-size: 12px; color: var(--ink-faint); }
.remove { background: #fff; color: #9C3B14; border: 1px solid #E8B79E; padding: 6px 12px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
</style>
