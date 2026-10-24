import axios from 'axios'
import router from '../router'
import { getToken, clearAuth } from '../utils/auth'
import socketService from '../services/socket'

const apiClient = axios.create({
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000
})

apiClient.interceptors.request.use(
  (config) => {
    if (!config.url.includes('/api/auth/login') && !getToken()) {
      clearAuth(socketService)
      if (router.currentRoute.value.path !== '/login') {
        router.push('/login')
      }
      return Promise.reject(new Error('令牌已过期'))
    }
    const token = localStorage.getItem('accessToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      if (error.response.status === 401 && router.currentRoute.value.path !== '/login') {
        clearAuth(socketService)
      }
      return Promise.reject(error)
    }
    console.error('Network Error or Timeout:', error.message)
    return Promise.reject(error)
  }
)

export default apiClient
