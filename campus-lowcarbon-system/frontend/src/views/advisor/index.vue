<template>
  <div class="advisor-container">
    <!-- 聊天头部 -->
    <div class="chat-header">
      <div class="header-icon">
        <el-icon :size="28"><Service /></el-icon>
      </div>
      <div class="header-info">
        <h3>低碳智能顾问</h3>
        <span class="status">
          <span class="status-dot"></span>
          在线
        </span>
      </div>
    </div>

    <!-- 消息区域 -->
    <div class="message-area" ref="messageAreaRef">
      <!-- 欢迎消息 -->
      <div class="welcome-section" v-if="messages.length === 0">
        <div class="welcome-icon">🌱</div>
        <h2>你好，我是低碳小助手</h2>
        <p>有什么关于低碳生活的问题，尽管问我吧！</p>
      </div>

      <!-- 消息列表 -->
      <div 
        v-for="(msg, index) in messages" 
        :key="index"
        :class="['message-item', msg.role === 'user' ? 'user-message' : 'ai-message']"
      >
        <!-- AI 消息：[头像] [气泡] 左对齐 -->
        <template v-if="msg.role === 'ai'">
          <div class="avatar ai-avatar">
            <span>🤖</span>
          </div>
          <div class="bubble-wrapper">
            <div class="bubble ai-bubble">
              <span class="bubble-text">{{ msg.content }}</span>
            </div>
            <span class="message-time ai-time">{{ msg.time }}</span>
          </div>
        </template>
        
        <!-- 用户消息：[气泡] [头像] 右对齐 -->
        <template v-else>
          <div class="bubble-wrapper user-wrapper">
            <div class="bubble user-bubble">
              <span class="bubble-text">{{ msg.content }}</span>
            </div>
            <span class="message-time user-time">{{ msg.time }}</span>
          </div>
          <div class="avatar user-avatar">
            <el-avatar :size="40" :src="userAvatar" v-if="userAvatar" />
            <el-avatar :size="40" v-else>
              {{ userStore.userInfo.name?.charAt(0) || 'U' }}
            </el-avatar>
          </div>
        </template>
      </div>

      <!-- AI 正在思考 -->
      <div class="message-item ai-message" v-if="isTyping">
        <div class="avatar ai-avatar">
          <span>🤖</span>
        </div>
        <div class="bubble ai-bubble typing-bubble">
          <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <span class="typing-text">AI 正在思考...</span>
        </div>
      </div>
    </div>

    <!-- 快捷提问区域 -->
    <div class="quick-chips" v-if="quickChips.length > 0 || quickChipsLoading">
      <span class="chips-label">猜你想问：</span>
      <div class="chips-list" v-if="quickChipsLoading">
        <el-skeleton :rows="1" animated style="width: 300px;" />
      </div>
      <div class="chips-list" v-else>
        <el-tag
          v-for="(chip, index) in quickChips"
          :key="index"
          class="chip-item"
          effect="plain"
          round
          @click="handleQuickChip(chip)"
        >
          {{ chip }}
        </el-tag>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper">
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入你的问题，按 Enter 发送..."
          resize="none"
          @keydown.enter.exact.prevent="handleSend"
          :disabled="isTyping"
        />
        <el-button
          class="send-btn"
          :disabled="!inputText.trim() || isTyping"
          @click="handleSend"
        >
          <el-icon :size="20"><Promotion /></el-icon>
        </el-button>
      </div>
      <p class="input-tip">💡 提示：我可以回答积分规则、垃圾分类、环保知识等问题</p>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, computed, onMounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { Service, Promotion } from '@element-plus/icons-vue'
import { sendQuestion, getQuickQuestions } from '@/api/advisor'

// 用户 Store
const userStore = useUserStore()

// 用户头像
const userAvatar = computed(() => userStore.userInfo.avatar || '')

// 消息列表（临时会话，页面刷新/离开后清空，不做持久化）
const messages = ref([])

// 输入框内容
const inputText = ref('')

// AI 是否正在输入
const isTyping = ref(false)

// 消息区域引用
const messageAreaRef = ref(null)

// 快捷提问选项（从后端动态加载）
const quickChips = ref([])
const quickChipsLoading = ref(true)

// 页面加载时获取快捷提问
onMounted(async () => {
  try {
    quickChips.value = await getQuickQuestions(5)
  } catch (error) {
    console.error('获取快捷提问失败:', error)
  } finally {
    quickChipsLoading.value = false
  }
})

// 格式化时间戳 (HH:mm)
const formatTime = (date) => {
  const hours = date.getHours().toString().padStart(2, '0')
  const minutes = date.getMinutes().toString().padStart(2, '0')
  return `${hours}:${minutes}`
}

// 滚动到底部
const scrollToBottom = () => {
  nextTick(() => {
    if (messageAreaRef.value) {
      messageAreaRef.value.scrollTop = messageAreaRef.value.scrollHeight
    }
  })
}

// 发送消息
const handleSend = async () => {
  const text = inputText.value.trim()
  if (!text || isTyping.value) return
  
  const now = new Date()
  
  // 1. 添加用户消息
  messages.value.push({
    role: 'user',
    content: text,
    time: formatTime(now)
  })
  
  // 清空输入框
  inputText.value = ''
  scrollToBottom()
  
  // 2. 开启 AI 思考状态
  isTyping.value = true
  
  try {
    // 3. 调用后端 AI 服务
    const result = await sendQuestion(text)
    
    // 4. 添加 AI 消息
    const aiTime = new Date()
    messages.value.push({
      role: 'ai',
      content: result.answer,
      time: formatTime(aiTime)
    })
  } catch (error) {
    // 异常兜底（理论上不会走到这里，因为 API 层已处理）
    const aiTime = new Date()
    messages.value.push({
      role: 'ai',
      content: '抱歉，我遇到了一些问题，请稍后再试...',
      time: formatTime(aiTime)
    })
  } finally {
    isTyping.value = false
    scrollToBottom()
  }
}

// 快捷提问
const handleQuickChip = (chip) => {
  inputText.value = chip
  handleSend()
}
</script>

<style scoped>
.advisor-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
  background: #f5f7fa;
}

/* 聊天头部 */
.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  color: #ffffff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

.header-icon {
  width: 48px;
  height: 48px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-info h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  opacity: 0.9;
}

.status-dot {
  width: 8px;
  height: 8px;
  background: #4ade80;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 消息区域 */
.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.message-area::-webkit-scrollbar {
  display: none;
}

/* 欢迎区域 */
.welcome-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  text-align: center;
  padding: 40px;
}

.welcome-icon {
  font-size: 64px;
  margin-bottom: 16px;
  animation: bounce 2s ease-in-out infinite;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.welcome-section h2 {
  margin: 0 0 8px;
  font-size: 24px;
  color: #303133;
  font-weight: 600;
}

.welcome-section p {
  margin: 0;
  font-size: 15px;
  color: #909399;
}

/* 消息项基础布局 */
.message-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  animation: fadeInUp 0.3s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* AI 消息：左对齐，顺序 [头像] [气泡] */
.ai-message {
  flex-direction: row;
  justify-content: flex-start;
}

/* 用户消息：右对齐，顺序 [气泡] [头像] */
.user-message {
  flex-direction: row;
  justify-content: flex-end;
}

/* 头像 */
.avatar {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.ai-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}

.user-avatar {
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  box-shadow: 0 4px 12px rgba(38, 166, 154, 0.3);
}

.user-avatar :deep(.el-avatar) {
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  font-size: 16px;
  font-weight: 600;
  color: #ffffff;
}

/* 气泡容器 */
.bubble-wrapper {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 70%;
}

.user-wrapper {
  align-items: flex-end;
}

/* 气泡 */
.bubble {
  padding: 14px 18px;
  border-radius: 18px;
  position: relative;
}

.ai-bubble {
  background: #ffffff;
  color: #303133;
  border-radius: 4px 18px 18px 18px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.user-bubble {
  background: linear-gradient(135deg, #00b894 0%, #00a085 100%);
  color: #ffffff;
  border-radius: 18px 4px 18px 18px;
  box-shadow: 0 2px 12px rgba(0, 184, 148, 0.3);
}

.bubble-text {
  font-size: 15px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 时间戳 */
.message-time {
  font-size: 11px;
  color: #909399;
  padding: 0 4px;
}

.ai-time {
  text-align: left;
}

.user-time {
  text-align: right;
}

/* AI 思考动画 */
.typing-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
}

.typing-indicator {
  display: flex;
  gap: 4px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #909399;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.6;
  }
  30% {
    transform: translateY(-8px);
    opacity: 1;
  }
}

.typing-text {
  font-size: 14px;
  color: #909399;
}

/* 快捷提问区域 */
.quick-chips {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  overflow-x: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.quick-chips::-webkit-scrollbar {
  display: none;
}

.chips-label {
  font-size: 13px;
  color: #909399;
  white-space: nowrap;
}

.chips-list {
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
}

.chip-item {
  cursor: pointer;
  border-color: #26a69a;
  color: #26a69a;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.chip-item:hover {
  background: #26a69a;
  color: #ffffff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(38, 166, 154, 0.3);
}

/* 输入区域 */
.input-area {
  padding: 16px 24px 20px;
  background: #ffffff;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.08);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: #f5f7fa;
  border-radius: 24px;
  padding: 8px 8px 8px 20px;
  border: 2px solid transparent;
  transition: all 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #26a69a;
  background: #ffffff;
  box-shadow: 0 0 0 4px rgba(38, 166, 154, 0.1);
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 8px 0;
  font-size: 15px;
  line-height: 1.5;
  resize: none;
}

.input-wrapper :deep(.el-textarea__inner):focus {
  box-shadow: none;
}

.send-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(135deg, #00b894 0%, #00a085 100%);
  border: none;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 4px 16px rgba(0, 184, 148, 0.4);
}

.send-btn:active:not(:disabled) {
  transform: scale(0.95);
}

.send-btn:disabled {
  background: #c0c4cc;
  cursor: not-allowed;
}

.input-tip {
  margin: 12px 0 0;
  font-size: 12px;
  color: #909399;
  text-align: center;
}

/* 响应式 */
@media (max-width: 768px) {
  .message-area {
    padding: 16px;
  }
  
  .bubble-wrapper {
    max-width: 85%;
  }
  
  .quick-chips {
    padding: 10px 16px;
  }
  
  .input-area {
    padding: 12px 16px 16px;
  }
}
</style>
