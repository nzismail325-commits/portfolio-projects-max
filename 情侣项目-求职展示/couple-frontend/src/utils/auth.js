import { jwtDecode } from 'jwt-decode'
import socketService from '../services/socket'

export const getUserIdFromToken = () => {
  const token = localStorage.getItem('accessToken')
  if (!token) return null
  try {
    const decoded = jwtDecode(token)
    const userId = Number(decoded.sub)
    return Number.isNaN(userId) ? null : userId
  } catch {
    return null
  }
}

export const getToken = () => {
  try {
    const token = localStorage.getItem('accessToken')
    if (!token) return false
    const decoded = jwtDecode(token)
    const now = Date.now() / 1000
    if (now > decoded.exp) {
      console.log('令牌已过期', {
        当前时间: new Date(now * 1000).toLocaleString(),
        过期时间: new Date(decoded.exp * 1000).toLocaleString()
      })
      return false
    }
    return true
  } catch (err) {
    console.error('检查令牌时出错:', err)
    return false
  }
}

export const clearAuth = (disconnectFn) => {
  localStorage.removeItem('accessToken')
  if (disconnectFn && typeof disconnectFn === 'function') {
    disconnectFn()
  } else if (socketService && typeof socketService.disconnect === 'function') {
    socketService.disconnect()
  }
}
