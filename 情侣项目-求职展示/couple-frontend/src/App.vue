<template>
  <ToastConfig />
  <router-view v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
  <audio ref="bgmPlayer" loop></audio>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import ToastConfig from './components/ToastConfig.vue'
import socketService, { connectionStatus } from './services/socket'
import { getUserIdFromToken, getToken, clearAuth } from './utils/auth'
import bgmUrl from './assets/bgm.mp3'

const route = useRoute()
const bgmPlayer = ref(null)
let bgmStarted = false
let bgmCurrentTime = 0
let connectToastTimer = null
let wasReconnecting = false
let wasConnecting = false

watch(
  connectionStatus,
  (newStatus, oldStatus) => {
    window.$toast.dismiss('global-connection-status')
    if (connectToastTimer) {
      clearTimeout(connectToastTimer)
      connectToastTimer = null
    }
    if (newStatus === 'connecting') {
      connectToastTimer = setTimeout(() => {
        window.$toast.info('正在连接服务器...', {
          id: 'global-connection-status',
          timeout: false,
          dedupe: false
        })
      }, 500)
    } else if (newStatus === 'reconnecting') {
      wasReconnecting = true
      window.$toast.warning('连接已中断，正在尝试恢复连接...', {
        id: 'global-connection-status',
        timeout: false,
        dedupe: false
      })
    } else if (newStatus === 'connected') {
      if (
        oldStatus === 'reconnecting' ||
        oldStatus === 'connecting'
      ) {
        if (wasReconnecting || wasConnecting || oldStatus === 'reconnecting') {
          window.$toast.success('已恢复与服务器的连接', { timeout: 3000 })
        }
      }
      wasReconnecting = false
      wasConnecting = true
    } else if (newStatus === 'disconnected') {
      wasReconnecting = false
      wasConnecting = false
    }
  }
)

const connectAndJoin = async (userId) => {
  if (!userId) return
  try {
    await socketService.connect()
    socketService.joinRoom(userId)
  } catch (err) {
    console.error('App.vue: Socket 连接失败:', err)
  }
}

const playBgm = () => {
  const player = bgmPlayer.value
  if (bgmStarted && player && player.paused) {
    if (player.src !== bgmUrl) {
      player.src = bgmUrl
    }
    if (bgmCurrentTime > 0) {
      player.currentTime = bgmCurrentTime
    }
    player.play().catch((err) => console.error('背景音乐播放失败:', err))
  }
}

const pauseBgm = () => {
  const player = bgmPlayer.value
  if (player && !player.paused) {
    player.pause()
    bgmCurrentTime = player.currentTime
  }
}

watch(
  () => route.path,
  (path) => {
    if (path === '/chat' || path === '/music') {
      pauseBgm()
    } else {
      playBgm()
    }
  },
  { immediate: true }
)

const startBgmOnInteraction = () => {
  bgmStarted = true
  if (route.path !== '/chat' && route.path !== '/music') {
    playBgm()
  }
  window.removeEventListener('click', startBgmOnInteraction)
  window.removeEventListener('keydown', startBgmOnInteraction)
}

const handleVisibilityChange = async () => {
  if (!bgmPlayer.value) return
  if (document.visibilityState === 'visible') {
    console.log('页面从后台切换到前台，检查连接状态...')
    if (socketService.socket.connected) {
      console.log('连接正常，同步用户状态...')
      if (route.path === '/chat') socketService.updateUserStatus('online')
    } else {
      console.log('检测到连接已断开，尝试重新连接...')
      try {
        await connectAndJoin(lastUserId.value)
      } catch (err) {
        console.error('重连失败:', err)
      }
    }
  } else {
    console.log('页面切换到后台')
    if (socketService.socket.connected && route.path === '/chat') {
      socketService.updateUserStatus('offline')
    }
  }
}

const onGlobalNewMessage = (notification) => {
  if (route.path !== '/chat' && document.visibilityState === 'visible') {
    window.$toast.info(notification.message)
  }
}

const lastUserId = ref(null)

onMounted(() => {
  if (getToken()) {
    try {
      lastUserId.value = getUserIdFromToken()
      connectAndJoin(lastUserId.value)
    } catch (err) {
      console.error('Token 解析失败:', err)
      clearAuth(socketService)
    }
  } else {
    clearAuth(socketService)
  }
  socketService.on('global_new_message', onGlobalNewMessage)
  window.addEventListener('click', startBgmOnInteraction)
  window.addEventListener('keydown', startBgmOnInteraction)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  socketService.off('global_new_message', onGlobalNewMessage)
  window.removeEventListener('click', startBgmOnInteraction)
  window.removeEventListener('keydown', startBgmOnInteraction)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
