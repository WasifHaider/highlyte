<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <img src="/logo-mark.svg" alt="" width="36" height="36" class="logo" />
      <h1>Log in to Highlyte</h1>
      <label class="field">
        <span>Email</span>
        <input v-model.trim="email" type="email" autocomplete="username" required />
      </label>
      <label class="field">
        <span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <div v-if="error" class="error" role="alert">{{ error }}</div>
      <button type="submit" :disabled="busy">{{ busy ? 'Logging in…' : 'Log in' }}</button>
      <p class="note">Users: ask your team admin for your login.</p>
      <p class="switch">New team? <router-link to="/signup">Create a team</router-link></p>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import '../styles/auth.css'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'
import { safeNext } from '../utils/authRedirect'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await auth.login(email.value, password.value)
    router.replace(safeNext(route.query.next))
  } catch (e) {
    error.value = apiErrorMessage(e, 'Login failed. Please try again.')
  } finally {
    busy.value = false
  }
}
</script>
