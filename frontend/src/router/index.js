import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import JobView from '../views/JobView.vue'
import ProjectsView from '../views/ProjectsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/jobs/:id', name: 'job', component: JobView, props: true },
    // Library was replaced by Projects; keep old links working.
    { path: '/library', redirect: '/projects' },
  ],
})

export default router
