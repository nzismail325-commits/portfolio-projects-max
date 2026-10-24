<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-content">
      <header class="modal-header">
        <h2>{{ isEditing ? '编辑这篇故事' : '写下今天的故事' }}</h2>
        <button class="close-btn" @click="$emit('close')">
          <X :size="24" />
        </button>
      </header>
      <form @submit.prevent="saveDiary">
        <div class="form-group">
          <label for="title">标题</label>
          <input type="text" id="title" v-model="form.title" required />
        </div>
        <div class="form-group form-group-expand">
          <label for="content">内容</label>
          <textarea id="content" rows="5" v-model="form.content" required></textarea>
        </div>
        <div class="form-group">
          <label for="tags">心情标签 (最多三个, 每个最多两字, 用空格分开)</label>
          <input type="text" id="tags" v-model="form.tags" @input="validateTags" />
          <p v-if="tagError" class="error-text">{{ tagError }}</p>
        </div>
        <div class="form-group">
          <label>今天天气怎么样?</label>
          <div class="weather-options">
            <template v-for="option in weatherOptions" :key="option.id">
              <label class="weather-label">
                <input type="radio" :value="option.id" v-model="form.weather" name="weather" />
                <component :is="option.component" :size="24" />
              </label>
            </template>
          </div>
        </div>
        <footer class="modal-footer">
          <button type="button" class="btn-cancel" @click="$emit('close')">取消</button>
          <button type="submit" class="btn-save" :disabled="!!tagError">保存日记</button>
        </footer>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { X, Sun, Cloud, CloudRain, CloudSnow } from 'lucide-vue-next'

const props = defineProps({
  diaryToEdit: { type: Object, default: null }
})

const emit = defineEmits(['close', 'add-diary', 'update-diary'])

const isEditing = computed(() => !!props.diaryToEdit)

const form = reactive({
  id: null,
  title: '',
  content: '',
  tags: '',
  weather: 'sun'
})

onMounted(() => {
  if (isEditing.value) {
    form.id = props.diaryToEdit.id
    form.title = props.diaryToEdit.title
    form.content = props.diaryToEdit.content
    form.tags = props.diaryToEdit.tags.join(' ')
    form.weather = props.diaryToEdit.weather
  }
})

const tagError = ref('')
const weatherOptions = [
  { id: 'sun', name: 'Sun', component: Sun },
  { id: 'cloud', name: 'Cloud', component: Cloud },
  { id: 'rain', name: 'Rain', component: CloudRain },
  { id: 'snow', name: 'Snow', component: CloudSnow }
]

const validateTags = () => {
  const tags = form.tags.split(' ').filter((t) => t)
  if (tags.length > 3) {
    tagError.value = '最多只能添加三个心情标签哦'
    return
  }
  const tooLong = tags.find((t) => t.length > 2)
  if (tooLong) {
    tagError.value = `标签 "${tooLong}" 不能超过两个字哦`
  } else {
    tagError.value = ''
  }
}

const saveDiary = () => {
  if (tagError.value) return
  const tags = form.tags.split(' ').filter((t) => t)
  const diaryData = {
    title: form.title,
    content: form.content,
    excerpt:
      form.content.length > 100 ? form.content.substring(0, 100) + '...' : form.content,
    tags,
    weather: form.weather
  }
  if (isEditing.value) {
    emit('update-diary', form.id, diaryData)
  } else {
    emit('add-diary', diaryData)
  }
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
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
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
.form-group-expand {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}
.form-group-expand textarea {
  flex-grow: 1;
  resize: vertical;
}
.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: rgba(255, 255, 255, 0.8);
}
input[type='text'],
textarea {
  width: 100%;
  padding: 0.8rem;
  background-color: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  color: #fff;
  font-size: 1rem;
}
.error-text {
  color: #ff8a8a;
  font-size: 0.9rem;
  margin-top: 0.5rem;
}
.weather-options {
  display: flex;
  gap: 1rem;
}
.weather-label {
  cursor: pointer;
  padding: 0.5rem;
  border-radius: 8px;
  border: 2px solid transparent;
  transition: all 0.2s ease;
}
.weather-label input {
  display: none;
}
.weather-label:has(input:checked) {
  border-color: var(--color-accent-primary);
  background-color: rgba(209, 163, 164, 0.2);
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
}
.btn-save:disabled {
  background-color: #555;
  cursor: not-allowed;
}
@media (max-width: 768px) {
  .modal-overlay {
    padding: 1rem;
    align-items: flex-start;
    overflow-y: auto;
  }
  .modal-content {
    width: 100%;
    max-width: 100%;
    max-height: calc(100vh - 2rem);
    margin: 1rem 0;
    padding: 1.5rem;
    box-sizing: border-box;
  }
  .modal-header {
    margin-bottom: 1.5rem;
    padding-bottom: 0.8rem;
  }
  .modal-header h2 {
    font-size: 1.3rem;
    line-height: 1.2;
  }
  .close-btn {
    min-width: 44px;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .form-group {
    margin-bottom: 1.2rem;
  }
  .form-group label {
    font-size: 0.9rem;
    margin-bottom: 0.4rem;
  }
  input[type='text'],
  textarea {
    padding: 0.7rem;
    font-size: 16px;
    box-sizing: border-box;
  }
  textarea {
    min-height: 120px;
    max-height: 200px;
  }
  .weather-options {
    gap: 0.8rem;
    flex-wrap: wrap;
  }
  .weather-label {
    padding: 0.6rem;
    min-width: 44px;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal-footer {
    margin-top: 1.5rem;
    gap: 0.8rem;
    flex-direction: column-reverse;
  }
  .btn-cancel,
  .btn-save {
    width: 100%;
    padding: 0.8rem;
    font-size: 1rem;
    min-height: 44px;
  }
}
@media (max-width: 480px) {
  .modal-overlay { padding: 0.5rem; }
  .modal-content { margin: 0.5rem 0; padding: 1rem; }
  .modal-header h2 { font-size: 1.2rem; }
  .form-group { margin-bottom: 1rem; }
  textarea { min-height: 100px; max-height: 150px; }
}
</style>
