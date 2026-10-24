<template>
  <div class="home-page">
    <StarrySky />
    <div class="content-container">
      <div class="welcome-section">
        <h1>{{ welcomeMessage }}</h1>
        <p>很高兴再次见到你。</p>
      </div>
      <nav class="nav-container">
        <button
          @click="prevPage"
          class="nav-arrow"
          :disabled="currentPage === 0"
        >
          <ChevronLeft :size="28" />
        </button>
        <div :class="['nav-grid', itemsClass]">
          <router-link
            v-for="item in visibleItems"
            :key="item.name"
            :to="item.route"
            class="nav-card"
          >
            <component :is="item.icon" :size="40" :stroke-width="1.5" />
            <span>{{ item.name }}</span>
          </router-link>
        </div>
        <button
          @click="nextPage"
          class="nav-arrow"
          :disabled="currentPage >= totalPages"
        >
          <ChevronRight :size="28" />
        </button>
      </nav>
      <div class="pagination-dots">
        <span
          v-for="n in totalPages + 1"
          :key="n"
          :class="['dot', { active: currentPage === n - 1 }]"
          @click="currentPage = n - 1"
        ></span>
      </div>
      <div
        class="logout-section"
        :style="{ animationDelay: `${0.5 + navItems.length * 0.15}s` }"
      >
        <button @click="handleLogout" class="logout-btn">
          <LogOut :size="18" />
          <span>退出登录</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import {
  ChevronLeft,
  ChevronRight,
  BookHeart,
  MessagesSquare,
  TreePine,
  Music,
  Heart,
  Star,
  Film,
  MapPin,
  Calendar,
  Settings,
  LogOut
} from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import { resetLoginState } from '../stores/loginState'
import StarrySky from '../components/StarrySky.vue'

const router = useRouter()
const role = ref('')

const welcomeMessage = computed(() =>
  role.value ? `晚上好，我最亲爱的${role.value}。` : '欢迎回家。'
)

onMounted(async () => {
  try {
    const response = await apiClient.get('/api/profile')
    if (response.data && response.data.role) {
      role.value = response.data.role
      if (sessionStorage.getItem('justLoggedIn') === 'true') {
        window.$toast.success('欢迎回来！')
        sessionStorage.removeItem('justLoggedIn')
      }
    }
  } catch (err) {
    console.error('获取用户信息失败 (Home.vue):', err)
  }
})

const navItems = ref([
  { name: '浪漫日记', route: '/diary', icon: BookHeart },
  { name: '私密聊天', route: '/chat', icon: MessagesSquare },
  { name: '爱情花园', route: '/garden', icon: TreePine },
  { name: '音乐盒', route: '/music', icon: Music },
  { name: '纪念日', route: '#', icon: Heart },
  { name: '共同愿望', route: '#', icon: Star },
  { name: '电影清单', route: '#', icon: Film },
  { name: '旅行足迹', route: '#', icon: MapPin },
  { name: '重要日子', route: '#', icon: Calendar },
  { name: '情侣空间', route: '#', icon: Settings }
])

const currentPage = ref(0)
const itemsPerPage = ref(6)

const totalPages = computed(() =>
  Math.ceil(navItems.value.length / itemsPerPage.value) - 1
)

const visibleItems = computed(() => {
  const start = currentPage.value * itemsPerPage.value
  const end = start + itemsPerPage.value
  return navItems.value.slice(start, end)
})

const itemsClass = computed(() => {
  const count = visibleItems.value.length
  return count <= 2 ? `items-${count}` : ''
})

const nextPage = () => {
  if (currentPage.value < totalPages.value) currentPage.value++
}

const prevPage = () => {
  if (currentPage.value > 0) currentPage.value--
}

const updateItemsPerPage = () => {
  itemsPerPage.value = window.innerWidth <= 768 ? 4 : 6
  if (currentPage.value > totalPages.value) {
    currentPage.value = totalPages.value
  }
}

onMounted(() => {
  updateItemsPerPage()
  window.addEventListener('resize', updateItemsPerPage)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateItemsPerPage)
})

const handleLogout = async () => {
  window.$toast.info('正在安全退出...')
  localStorage.removeItem('accessToken')
  socketService.disconnect()
  resetLoginState()
  await new Promise((resolve) => setTimeout(resolve, 500))
  window.$toast.success('您已安全退出登录')
  router.push('/login')
}
</script>

<style scoped>
@keyframes fadeInSlideUp {
  0% { opacity: 0; transform: translateY(30px); }
  100% { opacity: 1; transform: translateY(0); }
}
.home-page {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100dvh;
  width: 100vw;
  background: radial-gradient(ellipse at bottom, #1b2735, #090a0f);
  color: #fff;
  overflow-y: auto;
  overflow-x: hidden;
  font-family: KaiTi, 楷体, serif;
  position: relative;
  padding: 2rem 1rem;
  box-sizing: border-box;
}
.content-container {
  text-align: center;
  position: relative;
  z-index: 10;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.welcome-section {
  opacity: 0;
  animation: fadeInSlideUp 1s ease-out 0.2s forwards;
  margin-bottom: 4rem;
}
.welcome-section h1 {
  font-family: 'Lora', 思源宋体, serif;
  font-size: 3rem;
  margin: 0;
  font-weight: 400;
  color: var(--color-accent-secondary);
  text-shadow:
    0px 1px 2px rgba(0, 0, 0, 0.5),
    0 0 10px rgba(255, 255, 255, 0.7),
    0 0 15px rgba(227, 197, 152, 0.3);
  overflow-wrap: break-word;
  word-break: break-word;
}
.welcome-section p {
  font-size: 1.2rem;
  opacity: 0.8;
  margin-top: 0.5rem;
  color: #eee;
}
.nav-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  max-width: 520px;
  margin: 1.5rem auto;
  box-sizing: border-box;
  overflow: hidden;
}
.nav-grid {
  display: grid;
  grid-template-columns: repeat(3, 110px);
  gap: 1.5rem;
  justify-content: center;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.nav-grid.items-2 {
  grid-template-columns: repeat(2, 110px);
}
.nav-grid.items-1 {
  grid-template-columns: 110px;
}
.nav-card {
  background-color: rgba(209, 163, 164, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.18);
  box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
  border-radius: 12px;
  padding: 1.2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.8rem;
  color: #fff;
  text-decoration: none;
  font-size: 0.9rem;
  transition: all 0.3s ease;
  width: 110px;
  height: 110px;
}
.nav-card:hover {
  transform: translateY(-8px);
  box-shadow:
    0 8px 25px rgba(0, 0, 0, 0.3),
    0 0 20px var(--color-accent-primary);
  border-color: var(--color-accent-primary);
  color: var(--color-accent-primary);
}
.nav-arrow {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 1rem;
  transition: all 0.3s ease;
}
.nav-arrow:hover:not(:disabled) {
  color: #fff;
  transform: scale(1.2);
}
.nav-arrow:disabled {
  opacity: 0.2;
  cursor: not-allowed;
}
.pagination-dots {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: rgba(255, 255, 255, 0.3);
  transition: all 0.3s ease;
  cursor: pointer;
}
.dot.active {
  background-color: #fff;
  transform: scale(1.2);
}
.dot:hover {
  background-color: rgba(255, 255, 255, 0.6);
}
.logout-section {
  opacity: 0;
  animation: fadeInSlideUp 0.8s ease-out forwards;
  margin-top: 4rem;
}
.logout-btn {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  font-size: 1rem;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  transition: all 0.3s ease;
  font-family: KaiTi, 楷体, serif;
}
.logout-btn:hover {
  color: #fff;
}
@media (max-width: 768px) {
  .home-page {
    padding: 1rem 0.5rem;
  }
  .welcome-section h1 {
    font-size: 2rem;
    line-height: 1.2;
  }
  .welcome-section {
    margin-bottom: 2rem;
  }
  .nav-container {
    gap: 0.25rem;
    max-width: 100%;
    margin: 1rem auto;
  }
  .nav-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
    max-width: 280px;
    margin: 0 auto;
  }
  .nav-card {
    width: auto;
    height: auto;
    aspect-ratio: 1 / 1;
    padding: 1rem 0.5rem;
    font-size: 0.8rem;
  }
  .nav-arrow {
    padding: 0.5rem;
    min-width: 44px;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .pagination-dots {
    margin-bottom: 2rem;
  }
  .logout-section {
    margin-top: 2rem;
  }
}
</style>
