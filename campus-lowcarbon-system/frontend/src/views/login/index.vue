<template>
  <div class="login-container">
    <!-- 左侧：品牌展示区 -->
    <div class="left-section">
      <div class="brand-content">
        <div class="logo">
          <el-icon :size="80" color="#ffffff">
            <Trophy />
          </el-icon>
        </div>
        <h1 class="system-name">智能低碳行为管理系统</h1>
        <p class="slogan">让绿色生活成为习惯，让低碳行为创造价值</p>
        <div class="feature-list">
          <div class="feature-item">
            <el-icon><Check /></el-icon>
            <span>多模态验证体系</span>
          </div>
          <div class="feature-item">
            <el-icon><Check /></el-icon>
            <span>智能积分奖励</span>
          </div>
          <div class="feature-item">
            <el-icon><Check /></el-icon>
            <span>AI 低碳顾问</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：表单区 -->
    <div class="right-section">
      <div class="form-wrapper">
        <div class="form-header">
          <h2>{{ isLogin ? '欢迎回来' : '创建账号' }}</h2>
          <p>{{ isLogin ? '登录您的账号以继续' : '注册加入低碳行动' }}</p>
        </div>

        <!-- 登录表单 -->
        <el-form
          v-if="isLogin"
          ref="loginFormRef"
          :model="loginForm"
          :rules="loginRules"
          class="login-form"
          @submit.prevent="handleLogin"
        >
          <el-form-item prop="studentId">
            <el-input
              v-model="loginForm.studentId"
              placeholder="请输入学号"
              size="large"
              prefix-icon="User"
              clearable
            />
          </el-form-item>
          
          <el-form-item prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              prefix-icon="Lock"
              show-password
              clearable
            />
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              class="submit-btn"
              native-type="submit"
            >
              登录
            </el-button>
          </el-form-item>
        </el-form>

        <!-- 注册表单 -->
        <el-form
          v-else
          ref="registerFormRef"
          :model="registerForm"
          :rules="registerRules"
          class="login-form"
          @submit.prevent="handleRegister"
        >
          <el-form-item prop="studentId">
            <el-input
              v-model="registerForm.studentId"
              placeholder="请输入学号"
              size="large"
              prefix-icon="User"
              clearable
            />
            <div class="form-tip">
              <el-icon><Warning /></el-icon>
              <span>学号必须与系统预存的学号一致</span>
            </div>
          </el-form-item>

          <el-form-item prop="username">
            <el-input
              v-model="registerForm.username"
              placeholder="请输入真实姓名"
              size="large"
              prefix-icon="Avatar"
              clearable
            />
            <div class="form-tip">
              <el-icon><Warning /></el-icon>
              <span>姓名必须与学号对应的真实姓名一致，系统将进行双重验证</span>
            </div>
          </el-form-item>
          
          <el-form-item prop="password">
            <el-input
              v-model="registerForm.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              prefix-icon="Lock"
              show-password
              clearable
            />
          </el-form-item>

          <el-form-item prop="confirmPassword">
            <el-input
              v-model="registerForm.confirmPassword"
              type="password"
              placeholder="请再次输入密码"
              size="large"
              prefix-icon="Lock"
              show-password
              clearable
            />
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              class="submit-btn"
              native-type="submit"
              @click="handleRegister"
            >
              注册
            </el-button>
          </el-form-item>
        </el-form>

        <!-- 切换登录/注册 -->
        <div class="switch-mode">
          <span>{{ isLogin ? '还没有账号？' : '已有账号？' }}</span>
          <el-button type="text" @click="toggleMode">
            {{ isLogin ? '立即注册' : '去登录' }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Trophy, Check, User, Lock, Avatar, Warning } from '@element-plus/icons-vue'
import { login, register } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

// 控制登录/注册模式
const isLogin = ref(true)
const loading = ref(false)

// 登录表单
const loginFormRef = ref(null)
const loginForm = reactive({
  studentId: '',
  password: ''
})

const loginRules = {
  studentId: [
    { required: true, message: '请输入学号', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

// 注册表单
const registerFormRef = ref(null)
const registerForm = reactive({
  studentId: '',
  username: '',
  password: '',
  confirmPassword: ''
})

const validateConfirmPassword = (rule, value, callback) => {
  if (value === '') {
    callback(new Error('请再次输入密码'))
  } else if (value !== registerForm.password) {
    callback(new Error('两次输入密码不一致'))
  } else {
    callback()
  }
}

const registerRules = {
  studentId: [
    { required: true, message: '请输入学号', trigger: 'blur' }
  ],
  username: [
    { required: true, message: '请输入姓名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

// 切换登录/注册模式
const toggleMode = () => {
  isLogin.value = !isLogin.value
  // 清空表单
  if (isLogin.value) {
    loginFormRef.value?.resetFields()
  } else {
    registerFormRef.value?.resetFields()
  }
}

// 处理登录：统一用 async/await，避免重复触发与导航未等待
const handleLogin = async () => {
  if (!loginFormRef.value) return
  try {
    loading.value = true
    // 校验表单（Promise 版，失败会 throw）
    await loginFormRef.value.validate()

    // 执行登录，Pinia 内已写入 token/role/localStorage
    const result = await userStore.login({ ...loginForm })
    const roleName = result.role === 'admin' ? '管理员' : '学生'
    ElMessage.success(`登录成功！欢迎您，${roleName}`)

    // 使用 replace 避免回退到登录页，等待导航完成
    await router.replace('/dashboard')
  } catch (error) {
    // 检查是否是封禁错误
    const errorMessage = error?.response?.data?.message || error?.message || ''
    const isBanError = errorMessage && (
      errorMessage.includes('账号已被封禁') || 
      errorMessage.includes('被封禁') ||
      errorMessage.includes('封禁原因')
    )
    if (isBanError) {
      // 只使用MessageBox显示封禁信息，不显示其他提示
      const banReasonMatch = errorMessage.match(/封禁原因[：:]([^。]+)/)
      const banReason = banReasonMatch ? banReasonMatch[1].trim() : ''
      
      let message = '账号已被封禁'
      if (banReason) {
        message = `账号已被封禁\n\n封禁原因：\n${banReason}\n\n请联系管理员处理。`
      } else {
        message = '账号已被封禁，请联系管理员'
      }
      
      ElMessageBox.alert(message, '账号封禁提示', {
        type: 'error',
        confirmButtonText: '我知道了',
        dangerouslyUseHTMLString: false,
        customClass: 'ban-message-box',
        showClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: true,
        center: true
      }).catch(() => {
        // 用户关闭对话框
      })
      return // 封禁错误已处理，不再处理其他错误
    }
    
    // 其他错误：表单校验错误不会触发网络请求，所以不会在拦截器中显示
    if (error && error.message && !error.isBusinessError && !error.response) {
      // 仅处理表单校验错误（非网络错误）
      ElMessage.error(error.message)
    }
  } finally {
    loading.value = false
  }
}

// 处理注册
const handleRegister = async () => {
  if (!registerFormRef.value) return
  try {
      loading.value = true
    // 校验表单
    await registerFormRef.value.validate()
    
    // 调用注册接口
    const { confirmPassword, ...registerData } = registerForm
    await register(registerData)
    
        ElMessage.success('注册成功！请登录')
        
        // 切换到登录模式
        isLogin.value = true
        
        // 将注册的学号自动填入登录表单
        loginForm.studentId = registerForm.studentId
  } catch (error) {
    // 错误消息已在 request.js 拦截器中统一处理，这里不需要重复显示
    // 表单校验错误不会触发网络请求，所以不会在拦截器中显示
    if (error && error.message && !error.isBusinessError && !error.response) {
      // 仅处理表单校验错误（非网络错误）
      ElMessage.error(error.message)
    }
  } finally {
          loading.value = false
    }
}
</script>

<style scoped>
.login-container {
  display: flex;
  width: 100%;
  height: 100vh;
}

/* 左侧品牌区 */
.left-section {
  flex: 1;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px;
  position: relative;
  overflow: hidden;
}

.left-section::before {
  content: '';
  position: absolute;
  width: 500px;
  height: 500px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 50%;
  top: -200px;
  left: -200px;
}

.left-section::after {
  content: '';
  position: absolute;
  width: 400px;
  height: 400px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 50%;
  bottom: -150px;
  right: -150px;
}

.brand-content {
  position: relative;
  z-index: 1;
  color: #ffffff;
  text-align: center;
}

.logo {
  margin-bottom: 30px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}

.system-name {
  font-size: 42px;
  font-weight: bold;
  margin-bottom: 20px;
  letter-spacing: 2px;
}

.slogan {
  font-size: 18px;
  opacity: 0.9;
  margin-bottom: 50px;
  line-height: 1.6;
}

.feature-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
  opacity: 0.95;
}

.feature-item .el-icon {
  font-size: 20px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  padding: 8px;
}

/* 右侧表单区 */
.right-section {
  flex: 1;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px;
}

.form-wrapper {
  width: 100%;
  max-width: 420px;
}

.form-header {
  text-align: center;
  margin-bottom: 40px;
}

.form-header h2 {
  font-size: 32px;
  color: #303133;
  margin-bottom: 10px;
}

.form-header p {
  font-size: 14px;
  color: #909399;
}

.login-form {
  margin-top: 30px;
}

.submit-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: bold;
  margin-top: 10px;
}

.switch-mode {
  text-align: center;
  margin-top: 20px;
  font-size: 14px;
  color: #606266;
}

.switch-mode .el-button {
  font-weight: bold;
  padding: 0 4px;
}

/* 表单项样式优化 */
.login-form :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px #dcdfe6 inset;
  transition: all 0.3s;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #26a69a inset !important;
}

:deep(.el-button--primary) {
  background-color: #26a69a;
  border-color: #26a69a;
}

:deep(.el-button--primary:hover) {
  background-color: #00897b;
  border-color: #00897b;
}

/* 表单提示样式 */
.form-tip {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

.form-tip .el-icon {
  font-size: 14px;
  color: #e6a23c;
}

</style>

<!-- 封禁提示对话框全局样式 - 简化版 -->
<style>
.ban-message-box {
  max-width: 520px;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(220, 38, 38, 0.2);
}

.ban-message-box .el-message-box__header {
  padding: 20px 24px;
  background: #fee2e2;
  border-bottom: 1px solid #fecaca;
  border-radius: 16px 16px 0 0;
}

.ban-message-box .el-message-box__title {
  font-size: 18px;
  font-weight: 600;
  color: #dc2626;
}

.ban-message-box .el-message-box__headerbtn {
  top: 18px;
  right: 18px;
}

.ban-message-box .el-message-box__headerbtn .el-message-box__close {
  color: #dc2626;
}

.ban-message-box .el-message-box__content {
  padding: 24px;
  background: #ffffff;
}

.ban-message-box .el-message-box__message {
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.8;
  max-height: 400px;
  overflow-y: auto;
  padding: 16px;
  margin: 0;
  background: #fef2f2;
  border-radius: 12px;
  border: 1px solid #fee2e2;
  color: #374151;
  font-size: 14px;
}

.ban-message-box .el-message-box__message::-webkit-scrollbar {
  width: 6px;
}

.ban-message-box .el-message-box__message::-webkit-scrollbar-track {
  background: #f3f4f6;
  border-radius: 3px;
}

.ban-message-box .el-message-box__message::-webkit-scrollbar-thumb {
  background: #fca5a5;
  border-radius: 3px;
}

.ban-message-box .el-message-box__message::-webkit-scrollbar-thumb:hover {
  background: #ef4444;
}

.ban-message-box .el-message-box__btns {
  padding: 16px 24px 24px;
  border-top: 1px solid #fee2e2;
}

.ban-message-box .el-message-box__btns .el-button--primary {
  background: #dc2626;
  border: none;
  border-radius: 8px;
  padding: 10px 24px;
  font-weight: 500;
}

.ban-message-box .el-message-box__btns .el-button--primary:hover {
  background: #b91c1c;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
  }
  
  .left-section {
    padding: 40px 20px;
  }
  
  .system-name {
    font-size: 28px;
  }
  
  .slogan {
    font-size: 14px;
  }
  
  .right-section {
    padding: 40px 20px;
  }
  
  .ban-message-box {
    max-width: 90%;
  }
}
</style>
