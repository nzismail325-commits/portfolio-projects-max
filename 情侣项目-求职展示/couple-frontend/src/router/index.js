import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Home from '../views/Home.vue'
import Diary from '../views/Diary.vue'
import Chat from '../views/Chat.vue'
import LoveGarden from '../views/LoveGarden.vue'
import MusicBox from '../views/MusicBox.vue'
import { getToken, clearAuth, getUserIdFromToken } from '../utils/auth'
import { resetLoginState } from '../stores/loginState'
import { connectionStatus } from '../services/socket'
import socketService from '../services/socket'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'Login', component: Login },
  { path: '/home', name: 'Home', component: Home, meta: { requiresAuth: true } },
  { path: '/diary', name: 'Diary', component: Diary, meta: { requiresAuth: true } },
  { path: '/chat', name: 'Chat', component: Chat, meta: { requiresAuth: true } },
  { path: '/garden', name: 'LoveGarden', component: LoveGarden, meta: { requiresAuth: true } },
  { path: '/music', name: 'MusicBox', component: MusicBox, meta: { requiresAuth: true } }
]

const router = createRouter({
  history: createWebHistory('/'),
  routes
})

router.beforeEach((to, from, next) => {
  if (to.path === '/login') {
    resetLoginState()
  }
  const tokenValid = getToken()
  if (to.meta.requiresAuth && from.name && connectionStatus.value === 'reconnecting') {
    next(false)
    return
  }
  if (to.matched.some((record) => record.meta.requiresAuth)) {
    if (tokenValid) {
      next()
    } else {
      clearAuth(socketService)
      next('/login')
    }
  } else if (to.path === '/login' && tokenValid) {
    next('/home')
  } else {
    next()
  }
})

export { getUserIdFromToken }
export default router
