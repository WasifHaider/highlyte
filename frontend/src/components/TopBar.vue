<template>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand-group">
        <router-link to="/" class="brand" aria-label="Highlyte home">
          <img src="/logo-mark.svg" alt="" class="brand-mark" width="28" height="28" />
          <span class="brand-label">Highlyte</span>
        </router-link>
        <nav class="tabs">
          <router-link to="/" class="tab" exact-active-class="tab-active">Home</router-link>
          <router-link
            to="/projects"
            class="tab"
            active-class="tab-active"
            :class="{ 'tab-active': route.path.startsWith('/jobs/') }"
          >Projects</router-link>
          <!-- A clips page belongs to a project, so the Projects tab stays highlighted there. -->
          <router-link v-if="auth.isAdmin" to="/team" class="tab" active-class="tab-active">Team</router-link>
        </nav>
      </div>
      <div class="right-group">
        <div v-if="route.name !== 'home'" class="linkgroup">
          <input
            v-model="url"
            type="text"
            placeholder="Paste a YouTube link"
            class="input link-input"
            @keyup.enter="onGenerate"
          />
          <div class="segmented" role="group" aria-label="Spoken language">
            <button
              v-for="opt in LANGUAGES"
              :key="opt.value"
              type="button"
              :aria-pressed="language === opt.value"
              @click="language = opt.value"
            >{{ opt.label }}</button>
          </div>
          <button class="btn btn-primary link-generate" :disabled="submitting || !url" @click="onGenerate">
            {{ submitting ? 'Starting…' : 'Generate' }}
          </button>
        </div>
        <div class="account">
          <button class="btn btn-secondary" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
            <span class="account-label">{{ auth.me?.team.name || 'Account' }}</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <div v-if="menuOpen" class="account-menu card" role="menu">
            <div class="account-email faint">{{ auth.me?.user.email }}</div>
            <button class="btn btn-ghost logout" role="menuitem" @click="onLogout">Log out</button>
          </div>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGenerate } from '../composables/useGenerate'
import { useAuthStore } from '../stores/authStore'
import { useJobStore } from '../stores/jobStore'

const route = useRoute()
const router = useRouter()
const { url, language, submitting, LANGUAGES, onGenerate } = useGenerate()
const auth = useAuthStore()
const jobStore = useJobStore()
const menuOpen = ref(false)

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
  height: 56px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  padding: 0 16px;
}
@media (min-width: 768px) { .topbar { padding: 0 24px; } }
.topbar-inner {
  max-width: 1120px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.brand-group { display: flex; align-items: center; gap: 24px; }
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-brand);
  font-size: 20px;
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}
.brand-mark { display: block; width: 28px; height: 28px; }
.tabs { display: flex; gap: 4px; }
.tab {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-soft);
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 8px;
  transition: color var(--ease), background var(--ease);
}
.tab:hover { color: var(--ink); background: var(--accent-soft); }
.tab-active { color: var(--accent-text); background: var(--accent-soft); }
.right-group { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; justify-content: flex-end; }
/* Input, language switch and Generate read as one control: shared borders,
   squared inner corners, one height. min-width: 0 lets the input shrink so
   the group never spills under the account button. */
.linkgroup { display: flex; align-items: stretch; flex: 1; min-width: 0; max-width: 480px; height: 36px; }
@media (max-width: 1024px) { .linkgroup { display: none; } }
.link-input { flex: 1; min-width: 120px; height: 36px; border-radius: var(--radius) 0 0 var(--radius); }
.linkgroup .segmented {
  flex-shrink: 0; align-items: center; height: 36px; border-radius: 0; border-left: 0; border-right: 0;
}
.linkgroup .segmented button { height: 30px; }
.link-generate { flex-shrink: 0; height: 36px; border-radius: 0 var(--radius) var(--radius) 0; }
.link-generate:disabled { opacity: 1; background: var(--accent); color: rgba(255,255,255,.7); }
.account { position: relative; flex-shrink: 0; }
.account-menu {
  position: absolute; right: 0; top: calc(100% + 6px); min-width: 200px; padding: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04); z-index: 30;
}
.account-email { padding: 4px 6px 10px; border-bottom: 1px solid var(--border); margin-bottom: 8px; word-break: break-all; font-size: 12.5px; }
.logout { width: 100%; justify-content: flex-start; }
.account-label { max-width: 96px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 640px) {
  .topbar-inner { gap: 8px; }
  .brand-group { gap: 12px; }
  .brand-label { display: none; }
  .tab { padding: 0 8px; font-size: 12.5px; }
  /* An admin with a long team name must still fit: brand mark (28) + gap (12)
     + Home/Projects/Team tabs (~46 + 75 + 46 with 4px gaps = ~175) = ~215,
     + topbar-inner gap (8) + account button (padding 8+8 + label 64 + icon
     14 + btn gap 6 + border 2 = ~102) = ~325px, inside the 343px available
     at a 375px viewport (375 - 2*16 .topbar padding). */
  .account .btn { padding: 0 8px; }
  .account-label { max-width: 64px; }
}
</style>
