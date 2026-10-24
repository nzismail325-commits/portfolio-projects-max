import { io } from 'socket.io-client'
import { ref } from 'vue'
import { jwtDecode } from 'jwt-decode'

export const connectionStatus = ref('disconnected')

class SocketService {
  socket
  lastUserId = null
  connectPromise = null
  heartbeatInterval = null
  heartbeatTimeout = null
  heartbeatLatency = 10000
  serverHeartbeatTimeout = 30000

  constructor() {
    this.socket = io('', {
      autoConnect: false,
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 2000,
      reconnectionDelayMax: 10000,
      timeout: 20000,
      path: '/socket.io',
      upgrade: true,
      rememberUpgrade: true
    })
    this.socket.on('connect', this.handleConnect.bind(this))
    this.socket.on('disconnect', this.handleDisconnect.bind(this))
    this.socket.on('connect_error', this.handleConnectError.bind(this))
    this.socket.on('heartbeat_response', this.handleHeartbeatResponse.bind(this))
    this.socket.on('force_logout', this.handleForceLogout.bind(this))
  }

  handleConnect() {
    console.log('Socket.IO 已连接/重连成功。')
    connectionStatus.value = 'connected'
    this.connectPromise = null
    this.startHeartbeat()
    if (this.lastUserId) {
      this.handleReconnect()
    }
  }

  handleDisconnect() {
    console.log('Socket.IO 连接已断开，正在尝试重连...')
    connectionStatus.value = this.socket.io.opts.reconnection ? 'reconnecting' : 'disconnected'
    this.stopHeartbeat()
  }

  handleConnectError(error) {
    console.error('Socket.IO 连接错误:', error)
    connectionStatus.value = 'reconnecting'
    this.stopHeartbeat()
  }

  connect() {
    if (this.socket.connected) return Promise.resolve()
    if (this.connectPromise) return this.connectPromise
    if (
      connectionStatus.value === 'connecting' ||
      connectionStatus.value === 'reconnecting'
    ) {
      this.connectPromise = new Promise((resolve, reject) => {
        const check = () => {
          if (this.socket.connected) {
            this.connectPromise = null
            resolve()
          } else if (connectionStatus.value === 'disconnected') {
            this.connectPromise = null
            reject(new Error('Connection failed'))
          } else {
            setTimeout(check, 100)
          }
        }
        check()
      })
      return this.connectPromise
    }
    connectionStatus.value = 'connecting'
    this.socket.connect()
    this.connectPromise = new Promise((resolve, reject) => {
      this.socket.once('connect', () => {
        this.connectPromise = null
        resolve()
      })
      this.socket.once('connect_error', (err) => {
        this.connectPromise = null
        reject(err)
      })
    })
    return this.connectPromise
  }

  disconnect() {
    if (!this.socket) return
    console.log('手动断开 Socket.IO 连接')
    this.socket.io.opts.reconnection = false
    this.stopHeartbeat()
    this.socket.disconnect()
    this.lastUserId = null
    this.connectPromise = null
    connectionStatus.value = 'disconnected'
    setTimeout(() => {
      if (this.socket) {
        this.socket.io.opts.reconnection = true
      }
    }, 500)
  }

  startHeartbeat() {
    this.stopHeartbeat()
    this.sendHeartbeat()
    this.heartbeatInterval = setInterval(this.sendHeartbeat.bind(this), this.heartbeatLatency)
  }

  stopHeartbeat() {
    clearInterval(this.heartbeatInterval)
    clearTimeout(this.heartbeatTimeout)
    this.heartbeatInterval = null
    this.heartbeatTimeout = null
  }

  sendHeartbeat() {
    if (!this.socket.connected) return
    clearTimeout(this.heartbeatTimeout)
    this.heartbeatTimeout = setTimeout(() => {
      console.warn('服务器心跳响应超时，主动断开以触发重连流程。')
      connectionStatus.value = 'reconnecting'
      if (this.socket.io.engine) {
        this.socket.io.engine.close()
      }
    }, this.serverHeartbeatTimeout)
    this.socket.emit('heartbeat', { user_id: this.lastUserId })
  }

  handleHeartbeatResponse() {
    clearTimeout(this.heartbeatTimeout)
  }

  async joinRoom(userId) {
    this.lastUserId = userId
    if (this.socket.connected) {
      try {
        await this.emitWithAck('join_room', { user_id: userId })
        console.log(`已确认加入房间 (${userId})`)
      } catch (err) {
        console.warn(`加入房间 (${userId}) 未收到确认:`, err)
      }
    }
  }

  emitWithAck(event, data, timeoutMs = 5000) {
    return new Promise((resolve, reject) => {
      this.socket.timeout(timeoutMs).emit(event, data, (err, response) => {
        if (err) {
          reject(err)
          return
        }
        if (response && response.ok === false) {
          reject(new Error(response.error || `${event} failed`))
          return
        }
        resolve(response)
      })
    })
  }

  updateUserStatus(status) {
    if (this.lastUserId && this.socket.connected) {
      this.socket.emit('status_update', { user_id: this.lastUserId, status })
    }
  }

  enterChat(userId) {
    this.lastUserId = userId
    this.updateUserStatus('online')
  }

  leaveChat() {
    this.updateUserStatus('offline')
  }

  enterGarden(userId) {
    this.lastUserId = userId
    this.updateGardenStatus('online')
  }

  leaveGarden() {
    this.updateGardenStatus('offline')
  }

  updateGardenStatus(status) {
    if (this.lastUserId && this.socket.connected) {
      this.socket.emit('garden_status_update', { user_id: this.lastUserId, status })
      console.log(`已更新花园状态: ${status}`)
    }
  }

  handleReconnect() {
    if (this.lastUserId && this.socket.connected) {
      console.log(`准备恢复用户 ${this.lastUserId} 的连接状态`)
      this.joinRoom(this.lastUserId)
      window.dispatchEvent(
        new CustomEvent('socket-reconnected', { detail: { userId: this.lastUserId } })
      )
    }
  }

  handleForceLogout(data) {
    console.log('收到强制登出事件:', data)
    try {
      const token = localStorage.getItem('accessToken')
      if (!token) return
      if (jwtDecode(token).jti === data.jti) {
        console.log('该设备需要下线，清理数据并断开连接。')
        localStorage.removeItem('accessToken')
        this.disconnect()
        this.showForceLogoutNotification()
      }
    } catch (err) {
      console.error('处理强制登出事件失败:', err)
    }
  }

  showForceLogoutNotification() {
    if (document.getElementById('force-logout-modal')) return
    const overlay = document.createElement('div')
    overlay.id = 'force-logout-modal'
    overlay.style.position = 'fixed'
    overlay.style.top = '0'
    overlay.style.left = '0'
    overlay.style.width = '100%'
    overlay.style.height = '100%'
    overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.8)'
    overlay.style.display = 'flex'
    overlay.style.justifyContent = 'center'
    overlay.style.alignItems = 'center'
    overlay.style.zIndex = '9999'
    overlay.innerHTML = `
      <div style="background-color: rgba(255, 255, 255, 0.15); backdrop-filter: blur(10px); padding: 30px; border-radius: 10px; text-align: center; max-width: 80%; color: white;">
        <h2 style="margin-bottom: 20px; color: #ff6b6b;">您的账号已在其他设备登录</h2>
        <p style="margin-bottom: 30px;">当前会话已结束，请重新登录。</p>
        <button id="force-logout-relogin-btn" style="padding: 10px 20px; background-color: #D1A3A4; color: white; border: none; border-radius: 5px; cursor: pointer;">重新登录</button>
      </div>
    `
    document.body.appendChild(overlay)
    document.getElementById('force-logout-relogin-btn').onclick = function () {
      window.location.href = '/login'
    }
  }

  on(event, callback) {
    if (this.socket) {
      this.socket.on(event, callback)
    }
  }

  off(event, callback) {
    if (this.socket) {
      if (callback) {
        this.socket.off(event, callback)
      } else {
        this.socket.off(event)
      }
    }
  }
}

const socketService = new SocketService()
export default socketService
