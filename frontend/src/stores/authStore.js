import { defineStore } from 'pinia'
import { getMe, login as apiLogin, logout as apiLogout, signup as apiSignup } from '../services/highlyteApi'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    me: null, // { user: {id, email}, team: {id, name}, role } when logged in
    checked: false, // whether we've asked the backend who we are yet
  }),
  getters: {
    loggedIn: state => !!state.me,
    isAdmin: state => state.me?.role === 'admin',
  },
  actions: {
    async load() {
      try {
        this.me = await getMe()
      } catch {
        this.me = null
      } finally {
        this.checked = true
      }
    },
    async login(email, password) {
      this.me = await apiLogin(email, password)
      this.checked = true
    },
    async signup(teamName, email, password) {
      this.me = await apiSignup(teamName, email, password)
      this.checked = true
    },
    async logout() {
      try {
        await apiLogout()
      } finally {
        this.me = null
      }
    },
  },
})
