<template>
  <div class="chat-page">
    <StarrySky />
    <div class="chat-container">
      <header class="chat-header">
        <router-link to="/home" class="back-btn">
          <ArrowLeft :size="24" />
        </router-link>
        <div class="recipient-info">
          <h2>{{ partner?.role || '...' }}</h2>
          <span :class="['status', partnerStatus]">
            {{ partnerStatus === 'online' ? '在线中' : '离线中' }}
          </span>
        </div>
        <button class="more-options-btn" @click="toggleSidePanel">
          <Ellipsis :size="24" />
        </button>
      </header>

      <div v-if="historyMode" class="history-mode-banner">
        <span>正在查看 {{ searchDate }} 的历史记录</span>
        <button @click="returnToCurrent" class="return-btn"> 返回当前聊天 </button>
      </div>

      <main class="message-list" ref="messageListRef">
        <div v-if="hasMoreMessages" class="load-more-container">
          <button @click="loadMoreMessages" class="load-more-btn" :disabled="isLoadingMore">
            {{ isLoadingMore ? '加载中...' : '加载更多消息' }}
          </button>
        </div>
        <div
          v-for="message in messages"
          :key="message.id"
          :class="['message-row', messageDirection(message)]"
        >
          <template v-if="messageDirection(message) === 'sent'">
            <div class="bubble-wrapper">
              <div :class="['bubble', bubbleClass(message), { 'image-bubble': message.message_type === 'image' }]">
                <p v-if="message.message_type === 'text'">{{ message.content }}</p>
                <img
                  v-else
                  :src="resolveUrl(message.content)"
                  alt="聊天图片"
                  class="chat-image"
                  loading="lazy"
                  decoding="async"
                  @load="handleImageLoaded(message)"
                  @error="handleImageLoaded(message)"
                  @click="openImageViewer(message)"
                />
              </div>
              <span class="timestamp">{{ formatTimestamp(message.timestamp) }}</span>
            </div>
            <img
              :src="avatarFor(message)"
              alt="Avatar"
              :class="['avatar', { 'clickable-avatar': messageDirection(message) === 'sent' }]"
              loading="lazy"
              decoding="async"
              @click="triggerAvatarUpload"
            />
          </template>
          <template v-else>
            <img
              :src="avatarFor(message)"
              alt="Avatar"
              class="avatar"
              loading="lazy"
              decoding="async"
            />
            <div class="bubble-wrapper">
              <div :class="['bubble', bubbleClass(message), { 'image-bubble': message.message_type === 'image' }]">
                <p v-if="message.message_type === 'text'">{{ message.content }}</p>
                <img
                  v-else
                  :src="resolveUrl(message.content)"
                  alt="聊天图片"
                  class="chat-image"
                  loading="lazy"
                  decoding="async"
                  @load="handleImageLoaded(message)"
                  @error="handleImageLoaded(message)"
                  @click="openImageViewer(message)"
                />
              </div>
              <span class="timestamp">{{ formatTimestamp(message.timestamp) }}</span>
            </div>
          </template>
        </div>
      </main>

      <div
        v-if="showNewMessageIndicator"
        :class="['new-message-indicator', newMessageBubbleClass]"
        @click="scrollToBottomAndClear"
      >
        <span>↓ {{ newMessageBannerText }}</span>
      </div>

      <footer class="chat-footer">
        <div class="actions-container">
          <button
            @mousedown.prevent
            @click.stop="toggleActionMenu"
            class="action-btn"
          >
            <CirclePlus :size="24" />
          </button>
          <transition name="slide-up">
            <div v-if="showActionMenu" class="action-menu">
              <button @click="openAlbum" class="menu-item">
                <Image :size="28" /><span>相册</span>
              </button>
              <button @click="openCamera" class="menu-item">
                <Camera :size="28" /><span>相机</span>
              </button>
            </div>
          </transition>
        </div>
        <input
          type="text"
          class="message-input"
          placeholder="输入消息..."
          @focus="showActionMenu = false"
          ref="messageInputRef"
          v-model="newMessage"
          @keydown.enter="sendTextMessage"
        />
        <button @click="sendTextMessage" class="send-btn">
          <Send :size="22" />
        </button>
      </footer>
    </div>

    <transition name="slide-from-right">
      <div v-if="showSidePanel" class="side-panel-overlay" @click="closeSidePanel">
        <div class="side-panel" @click.stop>
          <div class="panel-header">
            <h3>更多选项</h3>
            <button @click="closeSidePanel" class="close-panel-btn">
              <X :size="24" />
            </button>
          </div>
          <div class="panel-content">
            <div class="panel-section">
              <h4>按日期查找记录</h4>
              <div class="date-search-container">
                <input type="date" v-model="searchDate" class="date-input" />
                <button @click="searchByDate" class="search-button">查找</button>
              </div>
            </div>
            <div class="panel-section">
              <h4>背景音乐</h4>
              <div class="music-control-container">
                <span>{{ isChatMusicPlaying ? '正在播放' : '已暂停' }}</span>
                <button @click="toggleChatMusic" class="music-toggle-btn">
                  {{ isChatMusicPlaying ? '暂停' : '播放' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <div v-if="imageViewerVisible" class="image-viewer" @click="closeImageViewer">
      <div class="image-viewer-content" @click.stop>
        <img :src="imageViewerUrl" alt="大图" class="full-image" />
        <div class="image-viewer-actions">
          <button @click="downloadImage" class="action-button">
            <Download :size="24" /><span>下载</span>
          </button>
          <button @click="closeImageViewer" class="action-button">
            <X :size="24" /><span>关闭</span>
          </button>
        </div>
      </div>
    </div>

    <input type="file" ref="albumInputRef" @change="handleImageSelected" hidden accept="image/*" />
    <input type="file" ref="cameraInputRef" @change="handleImageSelected" hidden accept="image/*" capture="user" />
    <input type="file" ref="avatarInputRef" @change="handleAvatarSelected" hidden accept="image/*" />
    <audio ref="audioRef" :src="chatBgmUrl" loop></audio>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { jwtDecode } from 'jwt-decode'
import {
  ArrowLeft,
  Ellipsis,
  CirclePlus,
  Image,
  Camera,
  Send,
  X,
  Download
} from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import { getErrorMessage, withPrefix } from '../utils/errors'
import StarrySky from '../components/StarrySky.vue'
import chatBgm from '../assets/罗生门.mp3'

const PAGE_SIZE = 10

const messageListRef = ref(null)
const showActionMenu = ref(false)
const messageInputRef = ref(null)
const newMessage = ref('')
const albumInputRef = ref(null)
const cameraInputRef = ref(null)
const avatarInputRef = ref(null)
const audioRef = ref(null)
const showSidePanel = ref(false)
const searchDate = ref(new Date().toISOString().split('T')[0])
const chatBgmUrl = ref(chatBgm)
const isChatMusicPlaying = ref(false)
const messages = ref([])
const messageIds = ref(new Set())
const currentUserId = ref(null)
const users = ref([])
const partnerStatus = ref('offline')
const isLoadingHistory = ref(false)
const hasMoreMessages = ref(true)
const oldestMessageId = ref(null)
const showNewMessageIndicator = ref(false)
const lastUnseenMessage = ref(null)

const currentMusicUser = computed(() => users.value.find((u) => u.id === currentUserId.value))
const partner = computed(() => users.value.find((u) => u.id !== currentUserId.value))
const newMessageTimestampText = computed(() =>
  lastUnseenMessage.value ? formatTimestamp(lastUnseenMessage.value) : ''
)
const newMessageBannerText = computed(
  () =>
    lastUnseenMessage.value
      ? `收到来自 ${users.value.find((u) => u.id === lastUnseenMessage.value.sender_id)?.role || ''} 的新消息`
      : '您有新消息'
)

const formatTimestamp = (iso) => {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  const sameDay =
    now.getFullYear() === date.getFullYear() &&
    now.getMonth() === date.getMonth() &&
    now.getDate() === date.getDate()
  const sameYear = now.getFullYear() === date.getFullYear()
  const pad = (num) => num.toString().padStart(2, '0')
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (sameDay) return time
  if (sameYear) return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`
}

const resolveUrl = (url) =>
  !url || url.startsWith('http') || url.startsWith('blob:') || url.startsWith('/') ? url : `/${url}`

const compressImage = (file, { maxDimension = 1280, quality = 0.78 } = {}) => {
  if (!file.type.startsWith('image/') || file.type === 'image/gif') {
    return Promise.resolve(file)
  }
  return new Promise((resolve) => {
    const objectUrl = URL.createObjectURL(file)
    const img = new window.Image()
    img.onload = () => {
      URL.revokeObjectURL(objectUrl)
      const scale = Math.min(1, maxDimension / Math.max(img.width, img.height))
      if (scale === 1 && file.size <= 220 * 1024) {
        resolve(file)
        return
      }
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(img.width * scale))
      canvas.height = Math.max(1, Math.round(img.height * scale))
      const context = canvas.getContext('2d')
      if (!context) {
        resolve(file)
        return
      }
      context.drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(
        (blob) => {
          if (!blob || blob.size >= file.size) {
            resolve(file)
            return
          }
          resolve(
            new File(
              [blob],
              `${file.name.replace(/\.[^.]+$/, '') || 'image'}.jpg`,
              { type: 'image/jpeg', lastModified: Date.now() }
            )
          )
        },
        'image/jpeg',
        quality
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      resolve(file)
    }
    img.src = objectUrl
  })
}

const pendingImageLoads = ref(new Set())
const isWaitingImages = ref(false)

const handleImageLoaded = (message) => {
  if (!pendingImageLoads.value.delete(message.id)) return
  if (isWaitingImages.value && pendingImageLoads.value.size === 0) {
    setTimeout(() => {
      scrollToBottom('auto')
      isWaitingImages.value = false
    }, 100)
    return
  }
  const list = messageListRef.value
  if (!list) return
  const isLast = messages.value.length > 0 && messages.value[messages.value.length - 1].id === message.id
  if (!isLast) return
  if (message.sender_id === currentUserId.value) {
    scrollToBottom('smooth')
    return
  }
  const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 300
  if (nearBottom && !showNewMessageIndicator.value) scrollToBottom('smooth')
}

const scrollToBottom = (behavior = 'auto') => {
  nextTick(() => {
    if (messageListRef.value) {
      const el = messageListRef.value
      el.scrollTo({ top: el.scrollHeight, behavior })
      if (behavior === 'auto') {
        setTimeout(() => {
          if (el.scrollTop < el.scrollHeight - el.clientHeight - 10) {
            el.scrollTo({ top: el.scrollHeight, behavior: 'auto' })
          }
        }, 100)
      }
    }
  })
}

const fetchUsers = async () => {
  try {
    const response = await apiClient.get('/api/users')
    users.value = response.data
  } catch (err) {
    console.error('获取用户信息失败:', err)
  }
}

let socketBound = false
const bindSocketEvents = () => {
  unbindSocketEvents()
  socketService.on('new_message', onNewMessage)
  socketService.on('status_update', onStatusUpdate)
  socketService.on('avatar_updated', onAvatarUpdated)
}

const unbindSocketEvents = () => {
  socketService.off('new_message', onNewMessage)
  socketService.off('status_update', onStatusUpdate)
  socketService.off('avatar_updated', onAvatarUpdated)
}

const replaceMessages = (list) => {
  messages.value = list
  messageIds.value = new Set(list.map((m) => m.id))
}

const appendMessages = (list) => {
  const fresh = list.filter((m) => !messageIds.value.has(m.id))
  if (fresh.length === 0) return []
  fresh.forEach((m) => messageIds.value.add(m.id))
  messages.value = [...messages.value, ...fresh]
  return fresh
}

const prependMessages = (list) => {
  const fresh = list.filter((m) => !messageIds.value.has(m.id))
  if (fresh.length === 0) return []
  fresh.forEach((m) => messageIds.value.add(m.id))
  messages.value = [...fresh, ...messages.value]
  return fresh
}

let lastSendTime = 0

const onNewMessage = (message) => {
  if (messageIds.value.has(message.id)) return
  const own = message.sender_id === currentUserId.value
  const list = messageListRef.value
  const nearBottom = list ? list.scrollHeight - list.scrollTop - list.clientHeight < 100 : true
  messageIds.value.add(message.id)
  messages.value.push(message)
  if (own || nearBottom) {
    scrollToBottom('smooth')
    showNewMessageIndicator.value = false
    lastUnseenMessage.value = null
  } else {
    showNewMessageIndicator.value = true
    lastUnseenMessage.value = message
  }
}

const onStatusUpdate = ({ user_id, status }) => {
  if (currentUserId.value && user_id !== currentUserId.value) {
    partnerStatus.value = status
  }
}

const onAvatarUpdated = ({ user_id, avatar_url }) => {
  const user = users.value.find((u) => u.id === user_id)
  if (user) user.avatar = avatar_url
}

const handleScroll = () => {
  const el = messageListRef.value
  if (!el) return
  if (el.scrollTop < 1 && hasMoreMessages.value && !isLoadingHistory.value && !historyMode.value) {
    loadMoreMessages()
  }
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 10) {
    showNewMessageIndicator.value = false
    lastUnseenMessage.value = null
  }
}

const scrollToBottomAndClear = () => {
  scrollToBottom('smooth')
  showNewMessageIndicator.value = false
  lastUnseenMessage.value = null
}

const fetchInitialMessages = async (initial = true) => {
  try {
    const params = { limit: PAGE_SIZE }
    if (!initial && messages.value.length > 0) {
      params.after_id = messages.value[messages.value.length - 1].id
    }
    const response = await apiClient.get('/api/chat/messages', { params })
    if (response.data.length > 0) {
      const list = messageListRef.value
      const nearBottom = list ? list.scrollHeight - list.scrollTop - list.clientHeight < 100 : true
      if (initial) {
        replaceMessages(response.data)
        oldestMessageId.value = response.data[0]?.id
      } else if (params.after_id) {
        appendMessages(response.data)
      }
      hasMoreMessages.value = initial && response.data.length >= PAGE_SIZE
      if (initial) {
        isWaitingImages.value = true
        const imageMessages = response.data.filter((m) => m.message_type === 'image')
        pendingImageLoads.value.clear()
        imageMessages.forEach((m) => pendingImageLoads.value.add(m.id))
        if (imageMessages.length === 0) {
          setTimeout(() => {
            scrollToBottom()
            isWaitingImages.value = false
          }, 50)
        } else {
          setTimeout(() => {
            if (isWaitingImages.value) {
              scrollToBottom()
              isWaitingImages.value = false
              pendingImageLoads.value.clear()
            }
          }, 3000)
        }
      } else if (params.after_id && response.data.length > 0) {
        if (nearBottom) scrollToBottom('smooth')
        else {
          showNewMessageIndicator.value = true
          lastUnseenMessage.value = response.data[response.data.length - 1]
        }
      }
    } else if (initial) {
      hasMoreMessages.value = false
    }
  } catch (err) {
    console.error('加载聊天记录失败:', err)
  }
}

const syncNewMessages = async (force = false) => {
  if (historyMode.value) return
  if (!force && socketService.socket?.connected) return
  if (Date.now() - lastSendTime < 5000) return
  await fetchInitialMessages(false)
}

const loadMoreMessages = async () => {
  if (isLoadingHistory.value || !hasMoreMessages.value) return
  isLoadingHistory.value = true
  const delay = new Promise((resolve) => setTimeout(resolve, 1000))
  try {
    const params = { before_id: oldestMessageId.value, limit: PAGE_SIZE }
    const [response] = await Promise.all([
      apiClient.get('/api/chat/messages', { params }),
      delay
    ])
    if (response.data.length > 0) {
      const list = messageListRef.value
      const prevHeight = list.scrollHeight
      const prevTop = list.scrollTop
      if (prependMessages(response.data).length === 0) {
        hasMoreMessages.value = response.data.length >= PAGE_SIZE
        return
      }
      oldestMessageId.value = response.data[0]?.id
      hasMoreMessages.value = response.data.length >= PAGE_SIZE
      nextTick(() => {
        const diff = list.scrollHeight - prevHeight
        if (diff > 0) list.scrollTop = prevTop + diff
      })
    } else {
      hasMoreMessages.value = false
    }
  } catch (err) {
    console.error('加载更多消息失败:', err)
    window.$toast.error('无法加载更多消息')
  } finally {
    isLoadingHistory.value = false
  }
}

const sendTextMessage = () => {
  const content = newMessage.value.trim()
  if (!content) return
  lastSendTime = Date.now()
  socketService.socket.emit('send_message', {
    sender_id: currentUserId.value,
    content,
    message_type: 'text'
  })
  newMessage.value = ''
}

const openAlbum = () => albumInputRef.value?.click()
const openCamera = () => cameraInputRef.value?.click()

const handleImageSelected = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  showActionMenu.value = false
  if (!file.type.startsWith('image/')) {
    window.$toast.error('请选择一个图片文件')
    return
  }
  const compressed = await compressImage(file, { maxDimension: 1280, quality: 0.78 })
  const formData = new FormData()
  formData.append('file', compressed)
  try {
    const response = await apiClient.post('/api/upload/image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        Math.round((progressEvent.loaded * 100) / progressEvent.total)
      }
    })
    if (response.data.url) {
      lastSendTime = Date.now()
      socketService.socket.emit('send_message', {
        sender_id: currentUserId.value,
        content: response.data.url,
        message_type: 'image'
      })
    }
  } catch (err) {
    console.error('图片上传失败:', err)
    window.$toast.error(withPrefix('图片上传失败', getErrorMessage(err, '请稍后重试')))
  } finally {
    event.target.value = null
  }
}

const triggerAvatarUpload = () => avatarInputRef.value?.click()

const handleAvatarSelected = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    window.$toast.error('请选择一个图片文件')
    return
  }
  const compressed = await compressImage(file, { maxDimension: 512, quality: 0.82 })
  const formData = new FormData()
  formData.append('file', compressed)
  const toastId = window.$toast.info('正在上传头像...', { timeout: false })
  try {
    const response = await apiClient.post('/api/user/avatar', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    if (response.data.url) {
      window.$toast.update(toastId, {
        content: '头像更新成功!',
        options: { type: 'success', timeout: 3000 }
      })
    }
  } catch (err) {
    console.error('头像上传失败:', err)
    window.$toast.update(toastId, {
      content: withPrefix('头像上传失败', getErrorMessage(err, '请稍后重试')),
      options: { type: 'error', timeout: 5000 }
    })
  } finally {
    event.target.value = null
  }
}

let reconnectHandler = null
let visibilityHandler = null
let refreshUserInfoHandler = null
let syncAllStatesHandler = null
let syncInterval = null

const handleSocketReconnected = () => {
  if (!currentUserId.value) return
  socketService.updateUserStatus('online')
  setTimeout(() => {
    const since = Date.now() - lastSendTime
    if (since < 5000) {
      setTimeout(() => syncNewMessages(true), 5000 - since)
    } else {
      syncNewMessages(true)
    }
  }, 200)
}

const handleVisibilityChange = () => {
  if (!currentUserId.value || !socketService.socket.connected) return
  socketService.updateUserStatus(document.visibilityState === 'visible' ? 'online' : 'offline')
}

const handleRefreshUserInfo = () => {
  fetchUsers()
  const since = Date.now() - lastSendTime
  if (since < 5000) {
    setTimeout(() => syncNewMessages(true), 5000 - since)
  } else {
    syncNewMessages(true)
  }
}

const handleSyncAllStates = async () => {
  await fetchUsers()
  if (currentUserId.value && socketService.socket.connected) {
    try {
      await apiClient.post('/api/sync-status', {
        status: document.visibilityState === 'visible' ? 'online' : 'offline'
      })
    } catch (err) {
      console.error('状态同步失败:', err)
    }
  }
  const since = Date.now() - lastSendTime
  if (since < 5000) {
    setTimeout(() => syncNewMessages(true), 5000 - since)
  } else {
    await syncNewMessages(true)
  }
}

const toggleSidePanel = () => {
  showSidePanel.value = !showSidePanel.value
}

const closeSidePanel = () => {
  showSidePanel.value = false
}

const toggleChatMusic = async () => {
  if (!audioRef.value) return
  try {
    if (isChatMusicPlaying.value) {
      audioRef.value.pause()
      isChatMusicPlaying.value = false
    } else {
      await audioRef.value.play()
      isChatMusicPlaying.value = true
    }
  } catch (err) {
    console.error('音乐播放/暂停失败:', err)
    window.$toast.error('无法播放音乐')
  }
}

const historyMode = ref(false)

const searchByDate = async () => {
  if (!searchDate.value) {
    window.$toast.info('请先选择一个日期')
    return
  }
  const toastId = window.$toast.info(`正在查找 ${searchDate.value} 的聊天记录...`, { timeout: false })
  try {
    historyMode.value = true
    showNewMessageIndicator.value = false
    lastUnseenMessage.value = null
    const response = await apiClient.get('/api/chat/messages', {
      params: { date: searchDate.value, limit: 100 }
    })
    if (response.data && response.data.length > 0) {
      replaceMessages(response.data)
      hasMoreMessages.value = false
      nextTick(() => {
        if (messageListRef.value) messageListRef.value.scrollTop = 0
      })
      window.$toast.update(toastId, {
        content: `已加载 ${searchDate.value} 的 ${response.data.length} 条记录`,
        options: { type: 'success', timeout: 4000 }
      })
      closeSidePanel()
    } else {
      window.$toast.update(toastId, {
        content: `在 ${searchDate.value} 没有找到聊天记录`,
        options: { type: 'info', timeout: 4000 }
      })
      historyMode.value = false
    }
  } catch (err) {
    console.error('按日期查找聊天记录失败:', err)
    window.$toast.update(toastId, {
      content: '查找失败，请稍后再试',
      options: { type: 'error', timeout: 4000 }
    })
    historyMode.value = false
  }
}

const returnToCurrent = async () => {
  if (!historyMode.value) return
  const toastId = window.$toast.info('正在返回当前聊天...', { timeout: false })
  try {
    await fetchInitialMessages(true)
    historyMode.value = false
    hasMoreMessages.value = true
    showNewMessageIndicator.value = false
    lastUnseenMessage.value = null
    scrollToBottom()
    window.$toast.update(toastId, {
      content: '已返回当前聊天',
      options: { type: 'success', timeout: 2000 }
    })
  } catch (err) {
    console.error('返回当前聊天失败:', err)
    window.$toast.update(toastId, {
      content: '返回失败，请刷新页面',
      options: { type: 'error', timeout: 3000 }
    })
    historyMode.value = false
  }
}

onMounted(async () => {
  if (localStorage.getItem('accessToken')) {
    try {
      currentUserId.value = Number(jwtDecode(localStorage.getItem('accessToken')).sub)
    } catch (err) {
      console.error('Token 解析失败:', err)
      return
    }
  }
  await fetchUsers()
  if (currentUserId.value) {
    await fetchInitialMessages(true)
    bindSocketEvents()
    socketService.enterChat(currentUserId.value)
    window.addEventListener('socket-reconnected', handleSocketReconnected)
    window.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('refresh-user-info', handleRefreshUserInfo)
    window.addEventListener('sync-all-states', handleSyncAllStates)
    syncInterval = setInterval(syncNewMessages, 120000)
    if (audioRef.value) {
      setTimeout(() => {
        audioRef.value
          .play()
          .then(() => {
            isChatMusicPlaying.value = true
          })
          .catch((err) => {
            console.warn('音乐自动播放失败，需要用户交互。', err)
            isChatMusicPlaying.value = false
          })
      }, 500)
    }
  }
  document.addEventListener('click', handleDocumentClick)
  messageListRef.value?.addEventListener('scroll', handleScroll)
})

onBeforeUnmount(() => {
  if (currentUserId.value) {
    socketService.leaveChat()
    unbindSocketEvents()
    window.removeEventListener('socket-reconnected', handleSocketReconnected)
    window.removeEventListener('visibilitychange', handleVisibilityChange)
    window.removeEventListener('refresh-user-info', handleRefreshUserInfo)
    window.removeEventListener('sync-all-states', handleSyncAllStates)
  }
  if (syncInterval) {
    clearInterval(syncInterval)
    syncInterval = null
  }
  document.removeEventListener('click', handleDocumentClick)
  messageListRef.value?.removeEventListener('scroll', handleScroll)
})

const messageDirection = (message) =>
  message.sender_id === currentUserId.value ? 'sent' : 'received'

const bubbleClass = (message) => {
  const user = users.value.find((u) => u.id === message.sender_id)
  if (user?.role === '女朋友') return 'girlfriend-bubble'
  if (user?.role === '男朋友') return 'boyfriend-bubble'
  return ''
}

const avatarFor = (message) => {
  const user = users.value.find((u) => u.id === message.sender_id)
  return user ? resolveUrl(user.avatar) : ''
}

const newMessageBubbleClass = computed(() =>
  lastUnseenMessage.value ? bubbleClass(lastUnseenMessage.value) : ''
)

const toggleActionMenu = () => {
  if (!showActionMenu.value) {
    messageInputRef.value?.blur()
  }
  showActionMenu.value = !showActionMenu.value
}

const handleDocumentClick = () => {
  if (showActionMenu.value) showActionMenu.value = false
}

const imageViewerVisible = ref(false)
const imageViewerUrl = ref('')
const viewingMessage = ref(null)

const openImageViewer = (message) => {
  imageViewerUrl.value = resolveUrl(message.content)
  viewingMessage.value = message
  imageViewerVisible.value = true
  document.body.style.overflow = 'hidden'
}

const closeImageViewer = () => {
  imageViewerVisible.value = false
  document.body.style.overflow = ''
}

const downloadImage = async () => {
  if (!imageViewerUrl.value) return
  const toastId = window.$toast.info('正在准备下载，请稍候...', {
    timeout: false,
    closeButton: false,
    closeOnClick: false,
    draggable: false
  })
  try {
    const response = await fetch(imageViewerUrl.value)
    if (!response.ok) throw new Error('无法获取图片资源')
    const blob = await response.blob()
    const objectUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.style.display = 'none'
    link.href = objectUrl
    const filename = imageViewerUrl.value.split('/').pop() || 'image.jpg'
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(objectUrl)
    window.$toast.update(toastId, {
      content: '下载已开始！',
      options: { type: 'success', timeout: 5000, closeButton: true, closeOnClick: true, draggable: true }
    })
  } catch (err) {
    console.error('下载图片失败:', err)
    window.$toast.update(toastId, {
      content: '下载失败，请稍后重试或尝试右键保存。',
      options: { type: 'error', timeout: 5000, closeButton: true, closeOnClick: true, draggable: true }
    })
  }
}
</script>

<style scoped>
.chat-page {
  height: 100dvh;
  width: 100vw;
  background: radial-gradient(ellipse at bottom, #1b2735, #090a0f);
  display: flex;
  justify-content: center;
  color: #fff;
  overflow: hidden;
}
.chat-container {
  width: 100%;
  max-width: 800px;
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  background-color: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
}
.back-btn,
.more-options-btn {
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
}
.recipient-info { text-align: center; }
.recipient-info h2 {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 600;
}
.recipient-info .status {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.6);
}
.recipient-info .status.online:before {
  content: '●';
  color: #2ecc71;
  margin-right: 0.4rem;
  font-size: 0.9rem;
}
.recipient-info .status.offline:before {
  content: '●';
  color: #95a5a6;
  margin-right: 0.4rem;
  font-size: 0.9rem;
}
.history-mode-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.8rem 1.5rem;
  z-index: 30;
  background-color: rgba(44, 62, 80, 0.65);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}
.history-mode-banner span {
  color: rgba(255, 255, 255, 0.9);
  font-weight: 600;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}
.return-btn {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  padding: 0.5rem 1rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  text-shadow: none;
}
.return-btn:hover {
  background-color: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.3);
  transform: translateY(-1px);
}
.load-more-container {
  display: flex;
  justify-content: center;
  padding: 1rem 0;
  margin-bottom: 1rem;
}
.load-more-btn {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  padding: 0.5rem 1.2rem;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s ease;
}
.load-more-btn:hover:not(:disabled) {
  background-color: rgba(255, 255, 255, 0.2);
}
.load-more-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.message-list {
  flex-grow: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.message-row {
  display: flex;
  align-items: flex-end;
  gap: 0.8rem;
}
.message-row.sent { justify-content: flex-end; }
.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
  transition: transform 0.2s ease;
  object-fit: cover;
  align-self: center;
}
.message-row.sent .avatar { order: 2; margin-bottom: 10px; }
.message-row.received .avatar { margin-bottom: 10px; }
.clickable-avatar { cursor: pointer; }
.clickable-avatar:hover {
  transform: scale(1.1);
  box-shadow: 0 4px 12px rgba(255, 255, 255, 0.2);
}
.bubble-wrapper {
  display: flex;
  flex-direction: column;
  max-width: 75%;
}
.message-row.sent .bubble-wrapper { align-items: flex-end; }
.message-row.received .bubble-wrapper { align-items: flex-start; }
.bubble {
  padding: 0.8rem 1.2rem;
  line-height: 1.5;
  color: #fff;
  border-radius: 20px;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  word-break: break-word;
}
.bubble p { margin: 0; }
.message-row.received .bubble { border-bottom-left-radius: 5px; }
.message-row.sent .bubble { border-bottom-right-radius: 5px; }
.girlfriend-bubble {
  background: linear-gradient(135deg, #e77f8d, #c184a4);
}
.boyfriend-bubble {
  background: linear-gradient(135deg, #5b99c7, #4ca1af);
}
.image-bubble {
  padding: 0.4rem;
  background: transparent !important;
  box-shadow: none !important;
}
.chat-image {
  max-width: 200px;
  max-height: 200px;
  border-radius: 12px;
  display: block;
  object-fit: cover;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  transition: transform 0.2s ease;
}
.chat-image:hover { transform: scale(1.03); }
.timestamp {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  margin-top: 6px;
  padding: 0 8px;
}
.new-message-indicator {
  position: absolute;
  bottom: 90px;
  left: 50%;
  transform: translate(-50%);
  color: #fff;
  padding: 0.6rem 1.2rem;
  border-radius: 20px;
  cursor: pointer;
  z-index: 15;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
  transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  opacity: 0.95;
}
.girlfriend-bubble.new-message-indicator,
.new-message-indicator.girlfriend-bubble {
  background: linear-gradient(135deg, #e77f8d, #c184a4);
}
.boyfriend-bubble.new-message-indicator,
.new-message-indicator.boyfriend-bubble {
  background: linear-gradient(135deg, #5b99c7, #4ca1af);
}
.new-message-indicator:hover {
  opacity: 1;
  transform: translate(-50%) scale(1.05);
}
.new-message-indicator span {
  font-weight: 600;
  font-size: 0.9rem;
}
.chat-footer {
  display: flex;
  align-items: flex-end;
  padding: 0.8rem 1.2rem;
  gap: 0.8rem;
  background-color: #1c2a38;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  position: relative;
  z-index: 20;
}
.actions-container {
  position: relative;
  display: flex;
  align-items: center;
}
.action-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  padding: 0.5rem;
  transition: color 0.3s ease;
}
.action-btn:hover { color: #fff; }
.action-menu {
  position: absolute;
  bottom: calc(100% + 10px);
  left: -0.5rem;
  display: flex;
  gap: 1.5rem;
  background-color: #34495e;
  padding: 1rem;
  border-radius: 12px;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.25);
  z-index: 10;
}
.menu-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
  font-size: 0.8rem;
  width: 60px;
}
.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(20px);
}
.message-input {
  flex-grow: 1;
  background-color: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  padding: 0.8rem 1.2rem;
  color: #fff;
  font-size: 1rem;
  outline: none;
  resize: none;
  line-height: 1.5;
}
.send-btn {
  background-color: var(--color-accent-primary);
  border-radius: 50%;
  width: 44px;
  height: 44px;
  display: flex;
  justify-content: center;
  align-items: center;
  color: #fff;
  border: none;
  cursor: pointer;
}
.image-viewer {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.9);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 100;
  padding: 20px;
  box-sizing: border-box;
  animation: fade-in 0.3s ease;
}
@keyframes fade-in {
  0% { opacity: 0; }
  100% { opacity: 1; }
}
.image-viewer-content {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  max-width: 100%;
  max-height: 100%;
}
.full-image {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 5px 25px rgba(0, 0, 0, 0.5);
  flex-shrink: 1;
  min-height: 0;
}
.image-viewer-actions {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  gap: 20px;
  margin-top: 20px;
  padding: 10px;
  background-color: rgba(0, 0, 0, 0.5);
  border-radius: 12px;
}
.action-button {
  display: flex;
  flex-direction: column;
  align-items: center;
  background-color: transparent;
  border: none;
  border-radius: 10px;
  color: #fff;
  cursor: pointer;
  padding: 5px 15px;
  transition: all 0.2s ease;
}
.action-button:hover {
  background-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}
.action-button span {
  margin-top: 5px;
  font-size: 0.9rem;
}
@media (min-width: 768px) {
  .image-viewer-content {
    max-width: 65vw;
    max-height: 90vh;
  }
}
@media (max-width: 767px) {
  .image-viewer-actions { width: 90%; }
}
.side-panel-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
}
.side-panel {
  width: 80%;
  max-width: 350px;
  height: 100%;
  background-color: #1c2a38;
  box-shadow: -5px 0 25px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
}
.panel-header h3 {
  margin: 0;
  font-size: 1.2rem;
}
.close-panel-btn {
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
  padding: 5px;
}
.panel-content {
  padding: 1.5rem;
  overflow-y: auto;
  flex-grow: 1;
}
.panel-section { margin-bottom: 2rem; }
.panel-section h4 {
  margin-top: 0;
  margin-bottom: 1rem;
  font-size: 1rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.8);
}
.date-search-container,
.music-control-container {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.date-input {
  flex-grow: 1;
  background-color: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  padding: 0.6rem;
  color: #fff;
  font-family: inherit;
}
.search-button,
.music-toggle-btn {
  background-color: var(--color-accent-primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.6rem 1rem;
  cursor: pointer;
  transition: background-color 0.2s;
}
.search-button:hover,
.music-toggle-btn:hover {
  filter: brightness(1.1);
}
.music-control-container span {
  flex-grow: 1;
  font-style: italic;
  color: rgba(255, 255, 255, 0.7);
}
.slide-from-right-enter-active,
.slide-from-right-leave-active {
  transition: background-color 0.4s ease;
}
.slide-from-right-enter-active .side-panel,
.slide-from-right-leave-active .side-panel {
  transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-from-right-enter-from,
.slide-from-right-leave-to {
  background-color: transparent;
}
.slide-from-right-enter-from .side-panel,
.slide-from-right-leave-to .side-panel {
  transform: translate(100%);
}
</style>
