import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import JobView from '../views/JobView.vue'
import LoginView from '../views/LoginView.vue'
import ProjectsView from '../views/ProjectsView.vue'
import SignupView from '../views/SignupView.vue'
import TeamView from '../views/TeamView.vue'
import { useAuthStore } from '../stores/authStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/signup', name: 'signup', component: SignupView, meta: { public: true } },
    { path: '/', name: 'home', component: HomeView },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/jobs/:id', name: 'job', component: JobView, props: true },
    { path: '/team', name: 'team', component: TeamView, meta: { adminOnly: true } },
    // Library was replaced by Projects; keep old links working.
    { path: '/library', redirect: '/projects' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.load()
  if (to.meta.public) return auth.loggedIn ? { path: '/' } : true
  if (!auth.loggedIn) return { path: '/login', query: { next: to.fullPath } }
  if (to.meta.adminOnly && !auth.isAdmin) return { path: '/' }
  return true
})

export default router
