<template>
  <div class="topbar">
    <div class="topbar-inner">
      <router-link to="/" class="brand" aria-label="Highlyte home">
        <img src="/logo-mark.svg" alt="" class="brand-mark" width="28" height="28" />
        <span>Highlyte</span>
      </router-link>
      <nav class="tabs">
        <router-link to="/" class="tab" exact-active-class="tab-active">Home</router-link>
        <router-link
          to="/projects"
          class="tab"
          active-class="tab-active"
          :class="{ 'tab-active': $route.path.startsWith('/jobs/') }"
        >Projects</router-link>
        <!-- A clips page belongs to a project, so the Projects tab stays highlighted there. -->
        <router-link v-if="auth.isAdmin" to="/team" class="tab" active-class="tab-active">Team</router-link>
      </nav>
      <input
        v-model="url"
        type="text"
        placeholder="Paste a YouTube link"
        @keyup.enter="onGenerate"
      />
      <button class="generate" :disabled="submitting || !url" @click="onGenerate">
        {{ submitting ? 'Starting…' : 'Generate' }}
      </button>
      <div class="account">
        <button class="account-btn" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
          {{ auth.me?.team.name || 'Account' }} ▾
        </button>
        <div v-if="menuOpen" class="account-menu" role="menu">
          <div class="account-email">{{ auth.me?.user.email }}</div>
          <button class="logout" role="menuitem" @click="onLogout">Log out</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useJobStore } from '../stores/jobStore'
import { useAuthStore } from '../stores/authStore'

const url = ref('')
const submitting = ref(false)
const router = useRouter()
const jobStore = useJobStore()
const auth = useAuthStore()
const menuOpen = ref(false)

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

async function onLogout() {
  menuOpen.value = false
  await auth.logout()
  jobStore.stopPolling()
  jobStore.$reset() // don't show this account's clips to the next person
  router.replace('/login')
}
</script>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(240,237,228,0.92);
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
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: 'Sora', var(--font-sans);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--ink);
  text-decoration: none;
}
.brand-mark {
  display: block;
  width: 28px;
  height: 28px;
}
.tabs {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.tab {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-soft);
  text-decoration: none;
  padding: 7px 12px;
  border-radius: 8px;
  transition: color .15s ease, background .15s ease;
}
.tab:hover { color: var(--ink); background: var(--accent-soft); }
.tab-active { color: var(--accent-text); background: var(--accent-soft); }
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
.generate {
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
.generate:disabled {
  cursor: default;
  background: rgba(0,71,65,0.45);
}
.account { position: relative; flex-shrink: 0; }
.account-btn {
  background: var(--surface); color: var(--ink); border: 1px solid var(--border);
  border-radius: 10px; padding: 9px 12px; font-size: 13px; font-weight: 600; cursor: pointer;
}
.account-menu {
  position: absolute; right: 0; top: calc(100% + 6px); min-width: 200px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.08); z-index: 30;
}
.account-email { font-size: 12.5px; color: var(--ink-soft); padding: 4px 6px 10px; border-bottom: 1px solid var(--border); margin-bottom: 8px; word-break: break-all; }
.logout { width: 100%; text-align: left; background: none; color: #9C3B14; border: none; padding: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
</style>
