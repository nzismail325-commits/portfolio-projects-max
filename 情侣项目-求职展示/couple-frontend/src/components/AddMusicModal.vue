<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-content">
      <header class="modal-header">
        <h2>上传新的音乐</h2>
        <button class="close-btn" @click="$emit('close')">
          <X :size="24" />
        </button>
      </header>
      <form @submit.prevent="submitUpload">
        <div class="form-group">
          <label for="title">歌曲标题</label>
          <input
            type="text"
            id="title"
            v-model="title"
            required
            placeholder="例如：我们最爱的那首歌"
          />
        </div>
        <div class="form-group">
          <label for="music-file">选择音乐文件</label>
          <div class="file-input-wrapper">
            <input type="file" id="music-file" @change="handleFileChange" required accept="audio/*" />
            <span class="file-input-label">{{ file ? file.name : '选择一个文件...' }}</span>
          </div>
        </div>
        <footer class="modal-footer">
          <button type="button" class="btn-cancel" @click="$emit('close')">取消</button>
          <button type="submit" class="btn-save" :disabled="!file || !title || isValidating">
            <span v-if="isValidating">验证中...</span>
            <span v-else>上传</span>
          </button>
        </footer>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'

const emit = defineEmits(['close', 'upload'])

const title = ref('')
const file = ref(null)
const duration = ref(0)
const isValidating = ref(false)
let validationTimeout = null
let validationAudio = null

const cleanup = () => {
  if (validationTimeout) {
    clearTimeout(validationTimeout)
    validationTimeout = null
  }
  if (validationAudio) {
    validationAudio.src = ''
    validationAudio = null
  }
}

onBeforeUnmount(cleanup)

const handleFileChange = (event) => {
  cleanup()
  const selected = event.target.files[0]
  file.value = null
  duration.value = 0
  if (selected) {
    isValidating.value = true
    file.value = selected
    if (!title.value) {
      title.value = selected.name.replace(/\.[^/.]+$/, '')
    }
    const filename = selected.name
    const lastDot = filename.lastIndexOf('.')
    let ext = ''
    if (lastDot > 0 && lastDot < filename.length - 1) {
      ext = filename.substring(lastDot + 1).toLowerCase()
    } else {
      ext = ''
    }
    const objectUrl = URL.createObjectURL(selected)
    validationAudio = new Audio(objectUrl)
    const finish = () => {
      isValidating.value = false
      clearTimeout(validationTimeout)
      URL.revokeObjectURL(objectUrl)
      validationAudio = null
    }
    validationAudio.addEventListener('loadedmetadata', () => {
      if (
        validationAudio.duration === 0 ||
        isNaN(validationAudio.duration) ||
        !isFinite(validationAudio.duration)
      ) {
        window.$toast.error('音频文件可能已损坏或格式不支持')
        file.value = null
      } else if (validationAudio.duration < 1) {
        window.$toast.error('音频文件时长过短')
        file.value = null
      } else if (validationAudio.duration > 3600) {
        window.$toast.error('音频文件时长过长，建议1小时以内')
        file.value = null
      } else {
        duration.value = validationAudio.duration
        window.$toast.success(
          `音频验证成功，时长: ${Math.floor(validationAudio.duration / 60)}:${(Math.floor(validationAudio.duration) % 60).toString().padStart(2, '0')}`
        )
      }
      finish()
    })
    validationAudio.addEventListener('error', () => {
      window.$toast.error('无法解析音频文件，文件可能已损坏或格式不受支持。')
      file.value = null
      finish()
    })
    validationTimeout = setTimeout(() => {
      window.$toast.error('音频文件验证超时')
      file.value = null
      finish()
    }, 5000)
  } else {
    isValidating.value = false
  }
}

const submitUpload = () => {
  if (!file.value || !title.value || isValidating.value) return
  emit('upload', { title: title.value, file: file.value, duration: duration.value })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  -webkit-backdrop-filter: blur(5px);
  backdrop-filter: blur(5px);
}
.modal-content {
  background: #2c3e50;
  padding: 2rem;
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  color: #fff;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}
.modal-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--color-accent-secondary);
}
.close-btn {
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
}
.form-group {
  margin-bottom: 1.5rem;
}
.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: rgba(255, 255, 255, 0.8);
}
input[type='text'] {
  width: 100%;
  padding: 0.8rem;
  background-color: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  color: #fff;
  font-size: 1rem;
}
.file-input-wrapper {
  position: relative;
  width: 100%;
  height: 48px;
  border: 1px dashed rgba(255, 255, 255, 0.4);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s ease;
}
.file-input-wrapper:hover {
  border-color: var(--color-accent-primary);
  background-color: rgba(209, 163, 164, 0.1);
}
#music-file {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}
.file-input-label {
  color: rgba(255, 255, 255, 0.6);
  font-style: italic;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  margin-top: 2rem;
}
.btn-cancel,
.btn-save {
  padding: 0.8rem 1.5rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.3s ease;
}
.btn-cancel {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.btn-save {
  background-color: var(--color-accent-primary);
  color: #fff;
  min-width: 90px;
}
.btn-save:disabled {
  background-color: #555;
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
