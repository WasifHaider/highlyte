<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <img src="/logo-mark.svg" alt="" width="36" height="36" class="logo" />
      <h1>Create your team</h1>
      <label class="field">
        <span>Team name</span>
        <input v-model="teamName" type="text" maxlength="80" required />
      </label>
      <label class="field">
        <span>Your email (team admin)</span>
        <input v-model.trim="email" type="email" autocomplete="username" required />
      </label>
      <label class="field">
        <span>Password (at least {{ MIN_PASSWORD }} characters)</span>
        <input v-model="password" type="password" autocomplete="new-password" required />
      </label>
      <label class="field">
        <span>Confirm password</span>
        <input v-model="confirm" type="password" autocomplete="new-password" required />
      </label>
      <div v-if="error" class="error" role="alert">{{ error }}</div>
      <button type="submit" :disabled="busy">{{ busy ? 'Creating…' : 'Create team' }}</button>
      <p class="note">Only the team admin signs up. You'll add your users from the Team page.</p>
      <p class="switch">Already have a login? <router-link to="/login">Log in</router-link></p>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import '../styles/auth.css'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'

const MIN_PASSWORD = 8

const router = useRouter()
const auth = useAuthStore()
const teamName = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!teamName.value.trim()) {
    error.value = 'Enter a team name.'
    return
  }
  if (password.value.length < MIN_PASSWORD) {
    error.value = `Password must be at least ${MIN_PASSWORD} characters.`
    return
  }
  if (password.value !== confirm.value) {
    error.value = "Passwords don't match."
    return
  }
  busy.value = true
  try {
    await auth.signup(teamName.value.trim(), email.value, password.value)
    router.replace('/')
  } catch (e) {
    error.value = apiErrorMessage(e, 'Signup failed. Please try again.')
  } finally {
    busy.value = false
  }
}
</script>
