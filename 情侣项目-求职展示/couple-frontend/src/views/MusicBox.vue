<template>
  <div class="music-box-page">
    <StarrySky />
    <div class="music-box-container">
      <div class="music-header">
        <div class="header-left">
          <router-link to="/home" class="back-btn">
            <ArrowLeft :size="28" />
          </router-link>
          <h1 class="page-title">
            <Music2 :size="24" class="title-icon" /> 音乐盒
          </h1>
          <div class="music-stats">
            <span>共 {{ filteredMusicList.length }} 首歌曲</span>
          </div>
        </div>
        <div class="header-right">
          <div class="search-box">
            <Search :size="16" class="search-icon" />
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索歌曲或上传者..."
              class="search-input"
            />
          </div>
          <button @click="showUploadModal = true" class="upload-btn">
            <Plus :size="16" /> 上传音乐
          </button>
        </div>
      </div>

      <div class="music-list-container">
        <div v-if="isLoading" class="loading-state">
          <div class="spinner"></div>
          <p>正在加载音乐...</p>
        </div>

        <div v-else-if="loadError" class="error-state">
          <p>{{ loadError }}</p>
          <button @click="retryLoad" class="retry-btn">重试</button>
        </div>

        <div v-else class="music-list">
          <div
            v-for="(music, index) in filteredMusicList"
            :key="music.id"
            :class="['music-item', { playing: currentMusic?.id === music.id }]"
            @click="playMusic(music)"
          >
            <div class="music-left">
              <div class="track-indicator">
                <span v-if="currentMusic?.id !== music.id" class="track-number">{{ index + 1 }}</span>
                <div v-else class="playing-indicator">
                  <div class="wave-bar"></div>
                  <div class="wave-bar"></div>
                  <div class="wave-bar"></div>
                </div>
              </div>
              <div class="music-avatar">
                <img
                  v-if="music.author?.avatar"
                  :src="resolveUrl(music.author.avatar)"
                  :alt="music.author.name"
                  class="avatar-img"
                  loading="lazy"
                  decoding="async"
                />
                <div v-else class="avatar-placeholder">
                  <Music2 :size="16" />
                </div>
              </div>
              <div class="song-info">
                <div class="song-title">{{ music.title }}</div>
                <div class="song-meta">
                  <span class="author-name">{{ music.author?.name || '未知用户' }}</span>
                  <span class="separator">·</span>
                  <span class="upload-date">{{ formatUploadDate(music.timestamp) }}</span>
                </div>
              </div>
            </div>
            <div class="music-right">
              <span class="duration">{{ formatDurationText(music.duration) }}</span>
              <div class="music-actions">
                <button
                  v-if="music.author && music.author.id === currentUser?.id"
                  @click.stop="promptDelete(music)"
                  class="action-btn delete-btn"
                  title="删除"
                >
                  <Trash2 :size="14" />
                </button>
              </div>
            </div>
          </div>

          <div v-if="filteredMusicList.length === 0" class="empty-state">
            <Music2 :size="48" class="empty-icon" />
            <p class="empty-text">
              {{ searchQuery ? '没有找到匹配的音乐' : '还没有上传任何音乐' }}
            </p>
            <button v-if="!searchQuery" @click="showUploadModal = true" class="empty-upload-btn">
              <Plus :size="16" /> 上传第一首歌
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部播放器 -->
    <div v-if="currentMusic" class="bottom-player">
      <div class="player-left">
        <div class="current-song">
          <div class="song-cover">
            <Music2 :size="20" />
          </div>
          <div class="song-details">
            <div class="song-title">{{ currentMusic.title }}</div>
            <div class="song-artist">{{ currentMusic.author?.name || '未知' }}</div>
          </div>
        </div>
      </div>
      <div class="player-center">
        <div class="player-controls">
          <button @click="playPrevious" class="control-btn" title="上一首">
            <SkipBack :size="16" />
          </button>
          <button @click="togglePlay" class="play-btn" title="播放/暂停">
            <component :is="isPlaying ? Pause : Play" :size="20" />
          </button>
          <button @click="playNext" class="control-btn" title="下一首">
            <SkipForward :size="16" />
          </button>
        </div>
        <div class="progress-container">
          <span class="time-current">{{ formatDurationText(currentTime) }}</span>
          <div class="progress-bar" @click="seek">
            <div class="progress-bg"></div>
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
            <div class="progress-thumb" :style="{ left: progressPercent + '%' }"></div>
          </div>
          <span class="time-total">{{ formatDurationText(totalDuration) }}</span>
        </div>
      </div>
      <div class="player-right">
        <div class="volume-control">
          <button @click="toggleMute" class="volume-btn">
            <component :is="isMuted ? VolumeX : Volume2" :size="16" />
          </button>
          <div class="volume-slider">
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              v-model.number="volume"
              @input="onVolumeInput"
              class="volume-input"
            />
          </div>
        </div>
        <button @click="cyclePlayMode" class="mode-btn" :title="playModeTitle">
          <component :is="playModeIcon" :size="16" />
        </button>
      </div>
    </div>

    <audio
      ref="audioElement"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      @ended="onEnded"
      @loadstart="onLoadStart"
      style="display: none"
    ></audio>

    <AddMusicModal v-if="showUploadModal" @close="showUploadModal = false" @upload="handleUpload" />

    <div v-if="showDeleteConfirm" class="confirm-modal-overlay">
      <div class="confirm-modal-content">
        <h3 class="confirm-modal-title">确认删除</h3>
        <p class="confirm-modal-text">
          您确定要永久删除歌曲 <span class="confirm-modal-song-title">《{{ musicToDelete.title }}》</span>
          吗？此操作无法撤销。
        </p>
        <div class="confirm-modal-actions">
          <button @click="cancelDelete" class="btn-cancel">取消</button>
          <button @click="confirmDelete" class="btn-confirm-delete">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  ArrowLeft,
  Music2,
  Search,
  Plus,
  Trash2,
  SkipBack,
  SkipForward,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Repeat,
  RotateCcw,
  Shuffle
} from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import { getErrorMessage, getErrorCode } from '../utils/errors'
import AddMusicModal from '../components/AddMusicModal.vue'
import StarrySky from '../components/StarrySky.vue'

const musicList = ref([])
const currentMusic = ref(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const totalDuration = ref(0)
const volume = ref(1)
const isMuted = ref(false)
const audioElement = ref(null)
const playMode = ref('order')
const isLoading = ref(true)
const searchQuery = ref('')
const showUploadModal = ref(false)
const currentUser = ref(null)
const showDeleteConfirm = ref(false)
const musicToDelete = ref({ id: null, title: '' })
const loadError = ref(null)

const playModeIcon = computed(() => {
  switch (playMode.value) {
    case 'random':
      return Shuffle
    case 'repeat':
      return RotateCcw
    default:
      return Repeat
  }
})

const playModeTitle = computed(() => {
  switch (playMode.value) {
    case 'random':
      return '随机播放'
    case 'repeat':
      return '单曲循环'
    default:
      return '顺序播放'
  }
})

const filteredMusicList = computed(() => {
  if (!searchQuery.value) return musicList.value
  const query = searchQuery.value.toLowerCase()
  return musicList.value.filter(
    (music) =>
      music.title.toLowerCase().includes(query) ||
      music.author?.name.toLowerCase().includes(query)
  )
})

const progressPercent = computed(() =>
  totalDuration.value ? (currentTime.value / totalDuration.value) * 100 : 0
)

const playMusic = (music) => {
  if (!music || !music.url) {
    console.error('无法播放: 音乐对象或URL无效', music)
    window.$toast.error('无法播放此音乐文件')
    return
  }
  if (currentMusic.value?.id === music.id) {
    togglePlay()
    return
  }
  currentMusic.value = music
  if (audioElement.value) {
    const url = resolveUrl(music.url)
    console.log('原始URL:', music.url)
    console.log('处理后URL:', url)
    audioElement.value.src = url
    audioElement.value.load()
    audioElement.value.addEventListener(
      'loadedmetadata',
      () => {
        if (
          audioElement.value.duration === 0 ||
          isNaN(audioElement.value.duration)
        ) {
          window.$toast.warning(`"${music.title}" 可能是损坏的音频文件`)
        }
      },
      { once: true }
    )
    audioElement.value
      .play()
      .then(() => {
        isPlaying.value = true
      })
      .catch((err) => {
        console.error('播放失败:', err)
        console.log('尝试播放的URL:', url)
        if (err.name === 'NotSupportedError') {
          window.$toast.error(`不支持的音频格式: ${music.title}`)
        } else if (err.name === 'NotAllowedError') {
          window.$toast.error('浏览器阻止了音频播放，请手动点击播放')
        } else {
          window.$toast.error(`播放失败: ${music.title} - ${err.message}`)
        }
        isPlaying.value = false
      })
  }
}

const togglePlay = () => {
  if (!audioElement.value || !currentMusic.value) return
  if (isPlaying.value) {
    audioElement.value.pause()
    isPlaying.value = false
  } else {
    const promise = audioElement.value.play()
    if (promise !== undefined) {
      promise
        .then(() => {
          isPlaying.value = true
        })
        .catch((err) => {
          console.error('播放/暂停切换失败:', err)
          isPlaying.value = false
          if (err.name === 'NotSupportedError') {
            window.$toast.error('音频源无效，请尝试播放其他歌曲。')
          } else {
            window.$toast.error('播放失败，请稍后重试。')
          }
        })
    }
  }
}

const playPrevious = () => {
  const index = filteredMusicList.value.findIndex((m) => m.id === currentMusic.value?.id)
  if (index > 0) {
    playMusic(filteredMusicList.value[index - 1])
  } else if (filteredMusicList.value.length > 0) {
    playMusic(filteredMusicList.value[filteredMusicList.value.length - 1])
  }
}

const playNext = () => {
  const index = filteredMusicList.value.findIndex((m) => m.id === currentMusic.value?.id)
  if (index < filteredMusicList.value.length - 1) {
    playMusic(filteredMusicList.value[index + 1])
  } else if (filteredMusicList.value.length > 0) {
    playMusic(filteredMusicList.value[0])
  }
}

const cyclePlayMode = () => {
  const modes = ['order', 'random', 'repeat']
  const index = modes.indexOf(playMode.value)
  playMode.value = modes[(index + 1) % modes.length]
}

const toggleMute = () => {
  if (!audioElement.value) return
  audioElement.value.muted = !audioElement.value.muted
  isMuted.value = audioElement.value.muted
}

const onVolumeInput = () => {
  if (!audioElement.value) return
  audioElement.value.volume = volume.value
  if (volume.value > 0 && isMuted.value) {
    isMuted.value = false
    audioElement.value.muted = false
  }
}

const seek = (event) => {
  if (!audioElement.value || !totalDuration.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  const time = ((event.clientX - rect.left) / rect.width) * totalDuration.value
  audioElement.value.currentTime = time
  currentTime.value = time
}

const onTimeUpdate = () => {
  if (audioElement.value) currentTime.value = audioElement.value.currentTime
}

const onLoadedMetadata = () => {
  if (audioElement.value) totalDuration.value = audioElement.value.duration
}

const onEnded = () => {
  isPlaying.value = false
  if (playMode.value === 'repeat') {
    audioElement.value.currentTime = 0
    audioElement.value.play()
    isPlaying.value = true
  } else if (playMode.value === 'random') {
    const index = Math.floor(Math.random() * filteredMusicList.value.length)
    playMusic(filteredMusicList.value[index])
  } else {
    playNext()
  }
}

const onLoadStart = () => {
  currentTime.value = 0
  totalDuration.value = 0
}

const formatDurationText = (seconds) => {
  if (!seconds) return '0:00'
  const minutes = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${minutes}:${secs.toString().padStart(2, '0')}`
}

const formatDurationDisplay = (seconds) => formatDurationText(seconds)

const formatUploadDate = (timestamp) =>
  timestamp
    ? new Date(timestamp).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
    : ''

const resolveUrl = (url) => {
  if (!url || url.startsWith('http') || url.startsWith('blob:')) return url
  return url
}

const handleUpload = async (uploadData) => {
  if (!currentUser.value) {
    window.$toast.error('无法上传音乐，用户信息加载失败！')
    return
  }
  const formData = new FormData()
  formData.append('title', uploadData.title)
  formData.append('file', uploadData.file)
  formData.append('duration', Math.round(uploadData.duration))
  try {
    await apiClient.post('/api/music/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    showUploadModal.value = false
    window.$toast.success('音乐上传成功！')
  } catch (err) {
    console.error('上传音乐失败:', err)
    const code = getErrorCode(err)
    let message = getErrorMessage(err, '上传失败，请稍后再试')
    if (code === 'UNSUPPORTED_FORMAT') {
      message = `${message}\n提示：手机录音通常为 m4a 或 aac 格式，现在已支持。`
    } else if (code === 'FILE_TOO_LARGE') {
      message = `${message}\n建议：可以使用音频压缩软件减小文件大小。`
    }
    window.$toast.error(message, { timeout: 6000 })
  }
}

const deleteMusic = async (musicId) => {
  try {
    await apiClient.delete(`/api/music/${musicId}`)
    if (currentMusic.value?.id === musicId) {
      currentMusic.value = null
      isPlaying.value = false
      if (audioElement.value) {
        audioElement.value.pause()
        audioElement.value.src = ''
      }
    }
    window.$toast.success('音乐删除成功！')
  } catch (err) {
    console.error('删除音乐失败:', err)
    window.$toast.error(getErrorMessage(err, '删除失败，请稍后再试'))
  }
}

const promptDelete = (music) => {
  musicToDelete.value = { id: music.id, title: music.title }
  showDeleteConfirm.value = true
}

const confirmDelete = () => {
  if (musicToDelete.value.id) deleteMusic(musicToDelete.value.id)
  cancelDelete()
}

const cancelDelete = () => {
  showDeleteConfirm.value = false
  musicToDelete.value = { id: null, title: '' }
}

const fetchMusicList = async () => {
  try {
    const response = (await apiClient.get('/api/music/')).data
    if (currentMusic.value) {
      const stillExists = response.some((m) => m.id === currentMusic.value.id)
      if (!stillExists) {
        window.$toast.info('正在播放的歌曲已被删除')
        if (audioElement.value) {
          audioElement.value.pause()
          audioElement.value.src = ''
        }
        currentMusic.value = null
        isPlaying.value = false
        currentTime.value = 0
        totalDuration.value = 0
      }
    }
    musicList.value = response
    searchQuery.value = ''
    loadError.value = null
  } catch (err) {
    console.error('加载音乐列表失败:', err)
    loadError.value = getErrorMessage(err, '无法加载音乐列表，请稍后再试')
  }
}

const onMusicUpdated = () => {
  console.log("收到 'music_updated' 事件，正在刷新列表...")
  fetchMusicList()
}

const retryLoad = () => {
  fetchMusicList()
}

onMounted(async () => {
  isLoading.value = true
  await Promise.all([
    fetchMusicList(),
    (async () => {
      try {
        const response = await apiClient.get('/api/profile')
        currentUser.value = response.data
      } catch (err) {
        console.error('加载用户信息失败:', err)
      }
    })()
  ])
  isLoading.value = false
  socketService.on('music_updated', onMusicUpdated)
})

onBeforeUnmount(() => {
  socketService.off('music_updated', onMusicUpdated)
  if (audioElement.value && !audioElement.value.paused) {
    audioElement.value.pause()
  }
})
</script>

<style scoped>
.music-box-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
.music-box-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1.5rem 2rem 0;
  position: relative;
  z-index: 1;
  overflow: hidden;
}
.music-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}
.back-btn {
  color: rgba(255, 255, 255, 0.7);
  transition: color 0.3s ease;
}
.back-btn:hover { color: #fff; }
.page-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.8rem;
  font-weight: 600;
  color: #fff;
  margin: 0;
  font-family: 'Lora', 思源宋体, serif;
}
.title-icon { color: var(--color-accent-primary); }
.music-stats {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.9rem;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 12px;
  color: rgba(255, 255, 255, 0.5);
}
.search-input {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  padding: 8px 12px 8px 36px;
  color: #fff;
  font-size: 0.9rem;
  width: 250px;
  transition: all 0.3s ease;
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
.search-input:focus {
  outline: none;
  border-color: var(--color-accent-primary);
  background: rgba(209, 163, 164, 0.1);
  box-shadow: 0 0 15px rgba(209, 163, 164, 0.3);
}
.search-input::placeholder {
  color: rgba(255, 255, 255, 0.5);
}
.upload-btn {
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  border: none;
  border-radius: 20px;
  padding: 8px 16px;
  color: #fff;
  font-size: 0.9rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 15px rgba(209, 163, 164, 0.3);
}
.upload-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(209, 163, 164, 0.4);
}
.music-list-container {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.music-list {
  flex: 1;
  overflow-y: auto;
  padding-right: 1rem;
}
.music-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  margin: 0 -1rem 4px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s ease;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.music-item:last-child { border-bottom: none; }
.music-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-bottom-color: transparent;
}
.music-item.playing {
  background: linear-gradient(135deg, rgba(209, 163, 164, 0.15), rgba(209, 163, 164, 0.05));
  border-bottom-color: transparent;
}
.music-item.playing:hover {
  background: linear-gradient(135deg, rgba(209, 163, 164, 0.2), rgba(209, 163, 164, 0.1));
}
.music-left {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  flex: 1;
  min-width: 0;
}
.track-indicator {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.track-number {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.9rem;
  font-weight: 500;
}
.playing-indicator {
  display: flex;
  gap: 2px;
  align-items: center;
  justify-content: center;
}
.wave-bar {
  width: 3px;
  height: 12px;
  background: var(--color-accent-primary);
  border-radius: 2px;
  animation: wave 1.5s ease-in-out infinite;
}
.wave-bar:nth-child(2) { animation-delay: 0.2s; }
.wave-bar:nth-child(3) { animation-delay: 0.4s; }
@keyframes wave {
  0%, 100% { height: 6px; }
  50% { height: 16px; }
}
.music-avatar {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
}
.avatar-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--color-accent-primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}
.avatar-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  border: 2px solid var(--color-accent-primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}
.song-info {
  flex: 1;
  min-width: 0;
}
.song-title {
  color: #fff;
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}
.song-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.85rem;
}
.author-name { font-weight: 500; }
.separator { opacity: 0.6; }
.upload-date { opacity: 0.8; }
.music-right {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  flex-shrink: 0;
}
.duration {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.9rem;
  font-weight: 500;
  min-width: 45px;
  text-align: right;
}
.music-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.action-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.action-btn:hover { color: rgba(255, 255, 255, 0.9); }
.delete-btn:hover { color: #ff8a8a; }
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: calc(100% - 2rem);
  color: rgba(255, 255, 255, 0.6);
  text-align: center;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02));
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  -webkit-backdrop-filter: blur(15px);
  backdrop-filter: blur(15px);
}
.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.5;
}
.empty-text {
  margin-bottom: 1.5rem;
  font-size: 1.1rem;
}
.empty-upload-btn {
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  border: none;
  border-radius: 20px;
  padding: 10px 20px;
  color: #fff;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 15px rgba(209, 163, 164, 0.3);
}
.empty-upload-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(209, 163, 164, 0.4);
}
.bottom-player {
  background: rgba(15, 15, 20, 0.8);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding: 1rem 2rem;
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: 2rem;
  align-items: center;
  position: sticky;
  bottom: 0;
  z-index: 10;
}
.player-left {
  display: flex;
  align-items: center;
}
.current-song {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.song-cover {
  width: 50px;
  height: 50px;
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.song-details { overflow: hidden; }
.song-artist {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.85rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.player-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.player-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.control-btn,
.play-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  padding: 8px;
  border-radius: 50%;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.play-btn {
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  color: #fff;
  width: 44px;
  height: 44px;
  box-shadow: 0 4px 15px rgba(209, 163, 164, 0.3);
}
.control-btn:hover,
.play-btn:hover { transform: scale(1.1); }
.play-btn:hover {
  box-shadow: 0 6px 20px rgba(209, 163, 164, 0.4);
}
.progress-container {
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  max-width: 500px;
}
.time-current,
.time-total {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.8rem;
  min-width: 35px;
  text-align: center;
}
.progress-bar {
  flex: 1;
  height: 6px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
  position: relative;
  cursor: pointer;
}
.progress-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}
.progress-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: linear-gradient(90deg, var(--color-accent-primary), #c19394);
  border-radius: 3px;
  transition: width 0.1s ease;
}
.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: #fff;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  opacity: 0;
  transition: opacity 0.3s ease;
}
.progress-bar:hover .progress-thumb { opacity: 1; }
.player-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 1rem;
}
.volume-control {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.volume-btn,
.mode-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  padding: 6px;
  border-radius: 4px;
  transition: all 0.3s ease;
}
.volume-btn:hover,
.mode-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}
.volume-slider { width: 80px; }
.volume-input {
  width: 100%;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  outline: none;
  -webkit-appearance: none;
  cursor: pointer;
}
.volume-input::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  background: #fff;
  border-radius: 50%;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
}
.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: rgba(255, 255, 255, 0.8);
}
.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}
@keyframes spin {
  100% { transform: rotate(360deg); }
}
.retry-btn {
  background: linear-gradient(135deg, var(--color-accent-primary), #c19394);
  border: none;
  border-radius: 20px;
  padding: 10px 20px;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-top: 1rem;
}
.retry-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(209, 163, 164, 0.4);
}
.confirm-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1001;
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
.confirm-modal-content {
  background: linear-gradient(145deg, #2c3e50, #1e2a38);
  padding: 2rem 2.5rem;
  border-radius: 16px;
  width: 90%;
  max-width: 420px;
  color: #fff;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  text-align: center;
}
.confirm-modal-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--color-accent-secondary);
  margin-top: 0;
  margin-bottom: 1rem;
}
.confirm-modal-text {
  font-size: 1rem;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 2.5rem;
}
.confirm-modal-song-title {
  font-weight: 700;
  color: var(--color-accent-primary);
}
.confirm-modal-actions {
  display: flex;
  justify-content: center;
  gap: 1rem;
}
.confirm-modal-actions .btn-cancel,
.confirm-modal-actions .btn-confirm-delete {
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 0.95rem;
  font-weight: 500;
  transition: all 0.3s ease;
  min-width: 120px;
}
.confirm-modal-actions .btn-cancel {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.confirm-modal-actions .btn-cancel:hover {
  background-color: rgba(255, 255, 255, 0.2);
}
.confirm-modal-actions .btn-confirm-delete {
  background: linear-gradient(135deg, #e74c3c, #c0392b);
  color: #fff;
  box-shadow: 0 4px 15px rgba(231, 76, 60, 0.3);
}
.confirm-modal-actions .btn-confirm-delete:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(231, 76, 60, 0.4);
}
@media (max-width: 1024px) {
  .music-box-container {
    padding: 1rem 1.5rem 0;
  }
  .music-header {
    padding: 1rem 0;
    flex-direction: column;
    gap: 1rem;
    align-items: stretch;
  }
  .header-right {
    width: 100%;
    justify-content: space-between;
  }
  .search-input { width: 200px; }
  .bottom-player {
    grid-template-columns: 1fr 2fr auto;
    padding: 1rem;
  }
}
@media (max-width: 768px) {
  .music-box-container {
    padding: 0.75rem 1rem 0;
  }
  .music-header { padding: 0.75rem 0; }
  .search-input { width: 150px; }
  .music-item,
  .music-item:hover,
  .music-item.playing {
    margin: 0 0 4px;
    padding: 1rem;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.1);
  }
  .music-item {
    background: rgba(255, 255, 255, 0.02);
  }
  .music-item:hover {
    background: rgba(255, 255, 255, 0.05);
  }
  .music-left { gap: 0.75rem; }
  .music-avatar {
    width: 40px;
    height: 40px;
  }
  .song-title { font-size: 1rem; }
  .song-meta { font-size: 0.8rem; }
  .bottom-player {
    grid-template-columns: 1fr;
    gap: 1rem;
    text-align: center;
    padding: 0.75rem 1rem;
  }
  .player-left,
  .player-right {
    justify-content: center;
  }
  .progress-container { max-width: 300px; }
  .volume-slider { width: 60px; }
}
.music-list::-webkit-scrollbar { width: 6px; }
.music-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}
.music-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.3);
  border-radius: 3px;
}
.music-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.5);
}
</style>
