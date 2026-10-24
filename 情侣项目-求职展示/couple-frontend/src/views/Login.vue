<template>
  <div class="login-page">
    <StarrySky />
    <div class="layout-container">
      <div class="quote-section">
        <p class="quote-text">
          "I seem to have loved you in numberless forms, numberless times…<br />
          in life after life, in age after age, forever."
        </p>
        <p class="quote-author">- Rabindranath Tagore</p>
      </div>
      <div class="login-section">
        <div class="login-box">
          <HeartHandshake class="logo" :size="48" :stroke-width="1.5" />
          <h2 class="title">我们的小屋</h2>
          <form @submit.prevent="handleLogin">
            <div class="input-group">
              <User class="icon" :size="20" />
              <input type="text" v-model="username" placeholder="你的昵称" required />
            </div>
            <div class="input-group">
              <Lock class="icon" :size="20" />
              <input type="password" v-model="password" placeholder="你们的密码" required />
            </div>
            <button
              type="submit"
              class="login-btn"
              :disabled="isLoading"
              ref="loginBtnRef"
            >
              {{ isLoading ? '正在进入...' : '进入' }}
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { HeartHandshake, User, Lock } from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import { resetLoginState } from '../stores/loginState'
import { v4 as uuidv4 } from 'uuid'
import { getErrorMessage, withPrefix } from '../utils/errors'
import StarrySky from '../components/StarrySky.vue'

const router = useRouter()
const username = ref('')
const password = ref('')
const loginBtnRef = ref(null)
const isLoading = ref(false)

onMounted(() => {
  resetLoginState()
  socketService.disconnect()
})

const getDeviceId = () => {
  let deviceId = localStorage.getItem('deviceId')
  if (!deviceId) {
    deviceId = uuidv4()
    localStorage.setItem('deviceId', deviceId)
  }
  return deviceId
}

const handleLogin = async (event) => {
  if (isLoading.value) return
  isLoading.value = true
  spawnHearts(event)
  try {
    const deviceId = getDeviceId()
    const response = await apiClient.post('/api/auth/login', {
      username: username.value,
      password: password.value,
      device_id: deviceId
    })
    if (response.data?.access_token && response.data?.user_id) {
      localStorage.setItem('accessToken', response.data.access_token)
      sessionStorage.setItem('justLoggedIn', 'true')
      await socketService.connect()
      socketService.joinRoom(response.data.user_id)
      router.push('/home')
    } else {
      window.$toast.error('登录失败: 无效的服务器响应')
      isLoading.value = false
    }
  } catch (err) {
    window.$toast.error(withPrefix('登录失败', getErrorMessage(err, '请检查账号或密码')))
    isLoading.value = false
  }
}

const spawnHearts = (event) => {
  const btn = loginBtnRef.value
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  for (let i = 0; i < 20; i++) {
    const particle = document.createElement('span')
    particle.classList.add('particle')
    particle.innerHTML = '♥'
    const size = Math.random() * 20 + 5
    particle.style.width = `${size}px`
    particle.style.height = `${size}px`
    particle.style.fontSize = `${size}px`
    const angle = Math.random() * 360
    const distance = Math.random() * 80 + 20
    const translateX = Math.cos(angle * (Math.PI / 180)) * distance
    const translateY = Math.sin(angle * (Math.PI / 180)) * distance
    particle.style.setProperty('--x', `${translateX}px`)
    particle.style.setProperty('--y', `${translateY}px`)
    particle.style.left = `${x - size / 2}px`
    particle.style.top = `${y - size / 2}px`
    btn.appendChild(particle)
    setTimeout(() => {
      particle.remove()
    }, 1000)
  }
}
</script>

<style scoped>
@keyframes text-float {
  0% { transform: translateY(0); }
  50% { transform: translateY(-16px); }
  100% { transform: translateY(0); }
}
@keyframes gentle-float {
  0% { transform: translateY(0); }
  50% { transform: translateY(-15px); }
  100% { transform: translateY(0); }
}
@keyframes fadeInSlideUp {
  0% { opacity: 0; transform: translateY(20px); }
  100% { opacity: 1; transform: translateY(0); }
}
@keyframes heart-burst {
  0% { transform: translate(0) scale(1); opacity: 1; }
  100% { transform: translate(var(--x), var(--y)) scale(0); opacity: 0; }
}
:deep(.particle) {
  position: absolute;
  color: var(--color-accent-primary);
  animation: heart-burst 1s ease-out forwards;
  pointer-events: none;
}
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100dvh;
  width: 100vw;
  overflow-y: auto;
  overflow-x: hidden;
  background: radial-gradient(ellipse at bottom, #1b2735, #090a0f);
  position: relative;
  padding: 1rem;
  box-sizing: border-box;
}
.layout-container {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  width: 100%;
  max-width: 1100px;
  align-items: center;
  gap: 2rem;
  box-sizing: border-box;
}
.quote-section {
  color: var(--color-accent-secondary);
  text-shadow:
    0px 1px 2px rgba(0, 0, 0, 0.5),
    0 0 10px rgba(255, 255, 255, 0.7),
    0 0 15px rgba(227, 197, 152, 0.3);
  text-align: center;
  padding-right: 0;
  opacity: 0;
  animation:
    fadeInSlideUp 1s ease-out 0.2s forwards,
    text-float 8s ease-in-out infinite 1s;
  position: relative;
  will-change: transform;
}
.quote-text {
  font-family: 'Dancing Script', cursive;
  font-size: 2.2rem;
  font-weight: 700;
  line-height: 1.5;
  margin: 0;
}
.quote-author {
  font-family: 'Dancing Script', cursive;
  font-size: 1.5rem;
  margin-top: 1.5rem;
  text-align: right;
  padding-right: 2rem;
}
.login-section {
  display: flex;
  justify-content: flex-start;
}
.login-box {
  background-color: rgba(209, 163, 164, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.85);
  padding: 2.5rem 3rem;
  border-radius: 12px;
  box-shadow:
    0 10px 30px rgba(0, 0, 0, 0.2),
    0 0 25px rgba(209, 163, 164, 0.2);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  text-align: center;
  width: 100%;
  max-width: 380px;
  animation:
    fadeInSlideUp 0.8s ease-out 0.4s forwards,
    gentle-float 6s ease-in-out infinite 1.2s;
}
.logo,
.title,
.input-group,
.login-btn {
  opacity: 0;
  animation: fadeInSlideUp 0.7s ease-out forwards;
}
.logo { animation-delay: 0.5s; }
.title { animation-delay: 0.6s; }
.input-group:nth-of-type(1) { animation-delay: 0.7s; }
.input-group:nth-of-type(2) { animation-delay: 0.8s; }
.login-btn { animation-delay: 0.9s; }
.logo {
  color: var(--color-accent-primary);
  margin-bottom: 0.5rem;
}
.title {
  margin-top: 0;
  margin-bottom: 2rem;
  font-size: 2rem;
  color: var(--color-text-main);
}
.input-group {
  position: relative;
  margin-bottom: 1.5rem;
}
.icon {
  position: absolute;
  left: 15px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-light);
}
.input-group input {
  width: 100%;
  padding: 12px 12px 12px 45px;
  border: 1px solid #ddd;
  border-radius: 12px;
  font-size: 1rem;
  background-color: var(--color-bg-main);
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease;
}
.input-group input:focus {
  outline: none;
  border-color: var(--color-accent-primary);
  box-shadow: 0 0 0 3px rgba(209, 163, 164, 0.3);
}
.login-btn {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background-color: var(--color-accent-primary);
  color: #fff;
  font-size: 1.1rem;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.2s ease,
    background-color 0.3s ease;
  position: relative;
  overflow: hidden;
}
.login-btn:hover {
  transform: translateY(-2px);
  background-color: #c58e8f;
}
.login-btn:disabled {
  background-color: #c58e8f;
  cursor: not-allowed;
  opacity: 0.7;
}
@media (max-width: 768px) {
  .login-page {
    padding: 0.5rem;
    min-height: 100dvh;
  }
  .layout-container {
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: center;
    height: auto;
    min-height: calc(100dvh - 1rem);
    gap: 2rem;
    padding: 1rem 0;
    overflow-y: visible;
    max-width: 100%;
  }
  .quote-section {
    text-align: center;
    padding-right: 0;
    order: 1;
    width: 100%;
    max-width: 100%;
    animation:
      fadeInSlideUp 1s ease-out 0.1s forwards,
      text-float 7s ease-in-out infinite 1s;
  }
  .quote-text {
    font-size: 1.4rem;
    line-height: 1.4;
    padding: 0 0.5rem;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  .quote-author {
    font-size: 1.1rem;
    padding-right: 0;
    text-align: center;
    margin-top: 1rem;
  }
  .login-section {
    width: 100%;
    max-width: 400px;
    justify-content: center;
    order: 2;
    padding: 0 0.5rem;
    box-sizing: border-box;
  }
  .login-box {
    padding: 2rem 1.5rem;
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
  }
  .logo,
  .title,
  .input-group,
  .login-btn {
    animation-delay: 0.2s;
  }
  .title {
    font-size: 1.6rem;
    margin-bottom: 1.5rem;
  }
  .input-group input {
    font-size: 16px;
    padding: 14px 14px 14px 45px;
  }
  .login-btn {
    padding: 14px;
    font-size: 1rem;
  }
}
@media (max-width: 480px) {
  .quote-text { font-size: 1.2rem; }
  .quote-author { font-size: 1rem; }
  .login-box { padding: 1.5rem 1rem; }
  .title { font-size: 1.4rem; }
}
</style>
