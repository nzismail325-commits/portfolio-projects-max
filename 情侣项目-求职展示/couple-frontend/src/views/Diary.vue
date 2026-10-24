<template>
  <div class="diary-page">
    <StarrySky />
    <div class="diary-container">
      <header class="diary-header">
        <div class="header-left">
          <router-link to="/home" class="back-btn">
            <ArrowLeft :size="28" />
          </router-link>
          <h1>我们的日记</h1>
        </div>
        <div class="actions">
          <div class="search-box">
            <Search :size="20" />
            <input type="text" v-model="filters.q" placeholder="在回忆里寻找..." />
          </div>
          <div class="date-filter-container" ref="dateFilterContainerRef">
            <button @click="toggleDateFilter" class="date-filter-btn">
              <CalendarDays :size="20" />
              <span>按日期筛选</span>
            </button>
            <transition name="slide-down">
              <div
                v-if="showDateFilter"
                class="date-filter-popup"
                ref="dateFilterPopupRef"
              >
                <div class="filter-hint">
                  <p>可按年、月、日单独或组合筛选，留空即为不限</p>
                </div>
                <div class="date-inputs">
                  <input type="number" v-model.number="filters.year" placeholder="年份 (YYYY)" />
                  <input type="number" v-model.number="filters.month" placeholder="月份 (MM)" />
                  <input type="number" v-model.number="filters.day" placeholder="日期 (DD)" />
                </div>
                <div class="popup-actions">
                  <button @click="applyDateFilter" class="popup-btn apply">筛选</button>
                  <button @click="clearDateFilter" class="popup-btn clear">清空</button>
                </div>
              </div>
            </transition>
          </div>
          <button @click="openAddModal" class="new-diary-btn desktop-only">
            <Plus :size="20" />
            <span>写新日记</span>
          </button>
        </div>
      </header>

      <main class="diary-list">
        <transition-group name="list" tag="div">
          <DiaryCard
            v-for="(diary, index) in diaries"
            :key="diary.id"
            :diary="diary"
            :current-user-id="currentUserId"
            @delete="promptDelete"
            @edit="openEditModal"
          />
        </transition-group>
        <div v-if="!diaries.length" class="diary-card-placeholder">
          <p>这里将来会是我们共同的回忆...</p>
          <p>每一篇日记，都是一颗星星。</p>
        </div>
      </main>

      <div v-if="activeFiltersText" class="active-filters">
        <span>当前筛选：{{ activeFiltersText }}</span>
        <button @click="clearAllFilters" class="clear-all-btn">
          <X :size="16" />
        </button>
      </div>

      <button @click="openAddModal" class="new-diary-btn fab mobile-only">
        <Plus :size="24" />
      </button>
    </div>

    <AddDiaryModal
      v-if="showAddModal"
      :diary-to-edit="diaryToEdit"
      @close="closeModal"
      @add-diary="addDiary"
      @update-diary="updateDiary"
    />

    <ConfirmDialog
      v-if="showDeleteConfirm"
      title="删除确认"
      message="真的要删除这篇珍贵的回忆吗？这个操作无法撤销。"
      @confirm="confirmDelete"
      @cancel="cancelDelete"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { jwtDecode } from 'jwt-decode'
import { ArrowLeft, Search, CalendarDays, Plus, X } from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import DiaryCard from '../components/DiaryCard.vue'
import AddDiaryModal from '../components/AddDiaryModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import StarrySky from '../components/StarrySky.vue'

const DELETION_ANIMATION_DURATION = 780

const showAddModal = ref(false)
const diaryToEdit = ref(null)

const openAddModal = () => {
  diaryToEdit.value = null
  showAddModal.value = true
}

const openEditModal = (diary) => {
  diaryToEdit.value = diary
  showAddModal.value = true
}

const closeModal = () => {
  showAddModal.value = false
  diaryToEdit.value = null
}

const diaries = ref([])
const currentUserId = ref(null)
const searchTimeout = ref(null)
const showDateFilter = ref(false)
const dateFilterContainerRef = ref(null)
const dateFilterPopupRef = ref(null)

const filters = reactive({ q: '', year: null, month: null, day: null })
const showDeleteConfirm = ref(false)
const diaryIdToDelete = ref(null)

const activeFiltersText = computed(() => {
  const parts = []
  if (filters.q) parts.push(`关键词 "${filters.q}"`)
  if (filters.year || filters.month || filters.day) {
    const dateParts = []
    if (filters.year) dateParts.push(`${filters.year}年`)
    if (filters.month) dateParts.push(`${filters.month}月`)
    if (filters.day) dateParts.push(`${filters.day}日`)
    parts.push(dateParts.join(''))
  }
  return parts.join(' 和 ')
})

const fetchDiaries = async () => {
  try {
    const params = {}
    for (const key in filters) {
      if (filters[key]) params[key] = filters[key]
    }
    const response = await apiClient.get('/api/diaries', { params })
    diaries.value = response.data
  } catch (err) {
    console.error('获取日记列表失败:', err)
  }
}

watch(
  () => filters.q,
  (newVal, oldVal) => {
    if (newVal !== oldVal) {
      clearTimeout(searchTimeout.value)
      searchTimeout.value = setTimeout(() => {
        fetchDiaries()
      }, 500)
    }
  }
)

watch(() => [filters.year, filters.month, filters.day], () => fetchDiaries(), { deep: true })

const toggleDateFilter = async () => {
  const opening = !showDateFilter.value
  showDateFilter.value = opening
  if (opening) {
    await nextTick()
    const popup = dateFilterPopupRef.value
    if (!popup) return
    popup.style.left = 'auto'
    popup.style.right = '0'
    if (popup.getBoundingClientRect().left < 0) {
      popup.style.right = 'auto'
      popup.style.left = '0'
    }
  }
}

const applyDateFilter = () => {
  fetchDiaries()
  showDateFilter.value = false
}

const clearDateFilter = () => {
  filters.year = null
  filters.month = null
  filters.day = null
  fetchDiaries()
  showDateFilter.value = false
}

const clearAllFilters = () => {
  filters.q = ''
  filters.year = null
  filters.month = null
  filters.day = null
  fetchDiaries()
}

const handleGlobalClick = (event) => {
  if (showDateFilter.value && dateFilterContainerRef.value && !dateFilterContainerRef.value.contains(event.target)) {
    showDateFilter.value = false
  }
}

const addLocalDiary = (diary) => {
  diaries.value.unshift(diary)
}

const removeLocalDiary = ({ id }) => {
  const diary = diaries.value.find((d) => d.id === id)
  if (!diary) return
  diary._deleting = true
  setTimeout(() => {
    diaries.value = diaries.value.filter((d) => d.id !== id)
  }, DELETION_ANIMATION_DURATION)
}

const applyUpdatedDiary = (updated) => {
  const index = diaries.value.findIndex((d) => d.id === updated.id)
  if (index === -1) return
  const existing = diaries.value[index]
  existing._updating = true
  setTimeout(() => {
    updated._updating = true
    diaries.value[index] = updated
    setTimeout(() => {
      diaries.value[index]._updating = false
    }, 1200)
  }, 300)
}

const onAvatarUpdated = ({ user_id, avatar_url }) => {
  diaries.value.forEach((diary) => {
    if (diary.author.id === user_id) {
      diary.author.avatar = avatar_url
    }
  })
}

const refreshUserInfo = async () => {
  console.log('日记页面：收到刷新用户信息事件，正在更新数据...')
  await fetchDiaries()
}

onMounted(() => {
  const token = localStorage.getItem('accessToken')
  if (token) {
    try {
      currentUserId.value = Number(jwtDecode(token).sub)
    } catch (err) {
      console.error('解析Token失败:', err)
    }
  }
  fetchDiaries()
  document.addEventListener('click', handleGlobalClick)
  socketService.on('new_diary', addLocalDiary)
  socketService.on('deleted_diary', removeLocalDiary)
  socketService.on('updated_diary', applyUpdatedDiary)
  socketService.on('avatar_updated', onAvatarUpdated)
  window.addEventListener('refresh-user-info', refreshUserInfo)
})

onBeforeUnmount(() => {
  socketService.off('new_diary', addLocalDiary)
  socketService.off('deleted_diary', removeLocalDiary)
  socketService.off('updated_diary', applyUpdatedDiary)
  socketService.off('avatar_updated', onAvatarUpdated)
  document.removeEventListener('click', handleGlobalClick)
  window.removeEventListener('refresh-user-info', refreshUserInfo)
})

const addDiary = async (diaryData) => {
  try {
    await apiClient.post('/api/diaries', diaryData)
    closeModal()
  } catch (err) {
    console.error('创建日记失败:', err)
  }
}

const updateDiary = async (diaryId, diaryData) => {
  try {
    const existing = diaries.value.find((d) => d.id === diaryId)
    if (existing) existing._updating = true
    await apiClient.put(`/api/diaries/${diaryId}`, diaryData)
    closeModal()
  } catch (err) {
    console.error('更新日记失败:', err)
    const existing = diaries.value.find((d) => d.id === diaryId)
    if (existing) existing._updating = false
  }
}

const promptDelete = (diaryId) => {
  diaryIdToDelete.value = diaryId
  showDeleteConfirm.value = true
}

const confirmDelete = async () => {
  try {
    const diaryId = diaryIdToDelete.value
    const diary = diaries.value.find((d) => d.id === diaryId)
    if (diary) diary._deleting = true
    await apiClient.delete(`/api/diaries/${diaryId}`)
    showDeleteConfirm.value = false
    diaryIdToDelete.value = null
  } catch (err) {
    console.error('删除日记失败:', err)
    const diary = diaries.value.find((d) => d.id === diaryIdToDelete.value)
    if (diary) diary._deleting = false
    showDeleteConfirm.value = false
    diaryIdToDelete.value = null
  }
}

const cancelDelete = () => {
  showDeleteConfirm.value = false
  diaryIdToDelete.value = null
}
</script>

<style scoped>
.diary-page {
  height: 100dvh;
  width: 100vw;
  background: radial-gradient(ellipse at bottom, #1b2735, #090a0f);
  color: #fff;
  display: flex;
  justify-content: center;
  overflow: hidden;
  overflow-x: hidden;
  font-family: KaiTi, 楷体, serif;
  position: relative;
  box-sizing: border-box;
}
.diary-container {
  width: 100%;
  max-width: 1000px;
  height: 100%;
  padding: 2rem 3rem;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}
.diary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
  gap: 1.5rem;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.back-btn {
  color: rgba(255, 255, 255, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.3s ease;
}
.back-btn:hover {
  color: #fff;
}
.diary-header h1 {
  font-family: 'Lora', 思源宋体, serif;
  font-size: 2.2rem;
  font-weight: 400;
  margin: 0;
  color: var(--color-accent-secondary);
  text-shadow: 0 0 10px rgba(227, 197, 152, 0.5);
}
.actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background-color: rgba(255, 255, 255, 0.1);
  padding: 0.5rem 1rem;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6);
}
.search-box input {
  background: transparent;
  border: none;
  outline: none;
  color: #fff;
  font-size: 1rem;
  width: 150px;
  box-sizing: border-box;
}
.search-box input::placeholder {
  color: rgba(255, 255, 255, 0.5);
}
.new-diary-btn {
  background-color: var(--color-accent-primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.6rem 1.2rem;
  font-size: 1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: KaiTi, 楷体, serif;
  transition: all 0.3s ease;
}
.new-diary-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 5px 15px rgba(209, 163, 164, 0.3);
}
.fab {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  padding: 0;
  justify-content: center;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3);
  z-index: 100;
}
.mobile-only { display: none; }
.desktop-only { display: flex; }
.diary-list {
  flex-grow: 1;
  overflow-y: auto;
  padding-top: 2rem;
  padding-right: 1rem;
  margin-right: -1rem;
}
.diary-card-placeholder {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 300px;
  padding: 6rem 1rem;
  color: rgba(255, 255, 255, 0.4);
  text-align: center;
  font-size: 1.2rem;
  line-height: 1.8;
  border: 2px dashed rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  align-items: center;
}
.date-filter-container { position: relative; }
.date-filter-btn {
  background-color: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: all 0.3s ease;
}
.date-filter-btn:hover {
  background-color: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.3);
}
.date-filter-popup {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  background-color: rgba(44, 62, 80, 0.5);
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.5);
  z-index: 110;
  border: 1px solid rgba(255, 255, 255, 0.1);
  width: 280px;
  -webkit-backdrop-filter: blur(1px);
  backdrop-filter: blur(1px);
  box-sizing: border-box;
}
.filter-hint {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 1rem;
  padding: 0.6rem;
  background-color: rgba(0, 0, 0, 0.15);
  border-radius: 6px;
  text-align: center;
  line-height: 1.4;
}
.filter-hint p { margin: 0; }
.date-inputs {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  margin-bottom: 1rem;
}
.date-inputs input {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: #fff;
  padding: 0.6rem;
  width: 100%;
}
.popup-actions {
  display: flex;
  justify-content: space-between;
}
.popup-btn {
  flex: 1;
  padding: 0.6rem;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.3s ease;
}
.popup-btn.apply {
  background-color: var(--color-accent-primary);
  color: #fff;
  margin-right: 0.5rem;
}
.popup-btn.apply:hover {
  background-color: #c19394;
}
.popup-btn.clear {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.popup-btn.clear:hover {
  background-color: rgba(255, 255, 255, 0.2);
}
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
.active-filters {
  flex-shrink: 0;
  padding: 0.5rem 1.5rem;
  background-color: rgba(209, 163, 164, 0.1);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--color-accent-secondary);
  font-size: 0.9rem;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  z-index: 20;
}
.clear-all-btn {
  background: none;
  border: none;
  color: var(--color-accent-secondary);
  opacity: 0.7;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.clear-all-btn:hover { opacity: 1; }
/* 列表过渡 */
.list-enter-active,
.list-leave-active {
  transition:
    opacity 0.78s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.78s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: opacity, transform;
}
.list-enter-from,
.list-leave-to {
  opacity: 0;
  transform: translate3d(0, 18px, 0);
}
.list-move {
  transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}
:deep(.diary-card.deleting) {
  transition:
    opacity 0.78s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.78s cubic-bezier(0.22, 1, 0.36, 1) !important;
  will-change: opacity, transform;
}
:deep(.diary-card.updating) {
  transition:
    border-color 1.5s ease,
    box-shadow 1.5s ease !important;
  box-shadow: 0 0 25px var(--color-accent-primary) !important;
}
@media (max-width: 768px) {
  .diary-page { overflow-y: auto; }
  .diary-container {
    padding: 1rem;
    max-width: 100%;
    box-sizing: border-box;
  }
  .diary-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
    padding-bottom: 1rem;
  }
  .header-left {
    width: 100%;
    justify-content: flex-start;
  }
  .back-btn {
    min-width: 44px;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .actions {
    width: 100%;
    margin-top: 0;
    gap: 0.8rem;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
  .search-box {
    flex-grow: 1;
    min-width: 200px;
  }
  .search-box input {
    width: 100%;
    font-size: 16px;
  }
  .diary-header h1 {
    font-size: 1.6rem;
    line-height: 1.2;
  }
  .desktop-only { display: none; }
  .mobile-only { display: flex; }
  .date-filter-popup {
    position: absolute;
    top: calc(100% + 10px);
    left: 0;
    right: auto;
    width: calc(100vw - 3rem);
    max-width: 320px;
    transform: none;
    margin: 0;
  }
  .date-filter-btn {
    padding: 0.6rem 0.8rem;
    font-size: 0.9rem;
    min-width: 44px;
    min-height: 44px;
  }
  .diary-list {
    padding-top: 1rem;
    padding-right: 0;
    margin-right: 0;
  }
  .diary-card-placeholder {
    font-size: 1rem;
    padding: 3rem 1rem;
    min-height: 200px;
  }
  .fab {
    bottom: 1.5rem;
    right: 1.5rem;
    width: 56px;
    height: 56px;
  }
  :deep(.diary-card) {
    padding: 1rem;
    margin-bottom: 1rem;
    box-shadow: none;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    transform: translateZ(0);
  }
  .list-enter-active,
  .list-leave-active {
    transition-duration: 0.78s;
  }
  .list-enter-from,
  .list-leave-to {
    transform: translate3d(0, 14px, 0);
  }
  .list-move { transition: none; }
  :deep(.diary-card.deleting) {
    transition-duration: 0.78s !important;
  }
  :deep(.diary-card:hover) {
    transform: none;
    box-shadow: none;
  }
  :deep(.diary-card.updating) {
    box-shadow: none !important;
  }
  :deep(.card-header) {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.8rem;
  }
  :deep(.card-title) {
    font-size: 1.2rem;
    line-height: 1.3;
  }
  :deep(.card-excerpt) {
    font-size: 0.9rem;
    line-height: 1.4;
  }
  :deep(.card-footer) {
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  :deep(.card-actions) { gap: 0.5rem; }
  :deep(.card-actions button) {
    min-width: 44px;
    min-height: 44px;
    padding: 0.5rem;
  }
}
@media (max-width: 480px) {
  .diary-container { padding: 0.5rem; }
  .diary-header h1 { font-size: 1.4rem; }
  .search-box { min-width: 150px; }
  .date-filter-popup {
    width: calc(100vw - 1rem);
    max-width: 280px;
    padding: 0.8rem;
  }
  .filter-hint { font-size: 0.8rem; padding: 0.5rem; }
  .date-inputs input { padding: 0.5rem; font-size: 16px; }
  .popup-btn { padding: 0.5rem; font-size: 0.9rem; }
  .fab {
    bottom: 1rem;
    right: 1rem;
    width: 52px;
    height: 52px;
  }
  :deep(.diary-card) { padding: 0.8rem; }
  :deep(.card-title) { font-size: 1.1rem; }
  :deep(.card-excerpt) { font-size: 0.85rem; }
}
</style>
