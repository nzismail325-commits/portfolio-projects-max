<template>
  <div class="user-info-page">
    <el-row :gutter="24">
      <!-- 左侧：个人概览卡片 -->
      <el-col :xs="24" :sm="24" :md="8" :lg="7" :xl="6">
        <div class="profile-card">
          <!-- 顶部 Banner -->
          <div class="card-banner">
            <div class="banner-pattern"></div>
            <div class="banner-overlay"></div>
          </div>
          
          <!-- 头像区域（使用负margin实现悬浮效果） -->
          <div class="avatar-section">
            <div class="avatar-wrapper">
              <el-avatar :size="100" :src="getAvatarUrl()" class="user-avatar">
                {{ (formInfo.nickname || formInfo.realName)?.charAt(0) || 'U' }}
              </el-avatar>
              <div class="avatar-border"></div>
              <div class="online-dot"></div>
            </div>
          </div>

          <!-- 用户基本信息 -->
          <div class="user-meta">
            <h2 class="user-name">{{ formInfo.nickname || formInfo.realName }}</h2>
            <el-tag 
              :type="isStudent ? 'success' : 'danger'" 
              effect="dark" 
              round 
              class="role-tag"
            >
              <span class="role-tag-content">
                <el-icon><Medal /></el-icon>
                <span>{{ isStudent ? '在校学生' : '系统管理员' }}</span>
              </span>
            </el-tag>
          </div>

          <!-- 信息列表 -->
          <div class="info-list">
            <div class="info-item" v-if="isStudent">
              <div class="info-icon">
                <el-icon><User /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">学号</span>
                <span class="info-value">{{ formInfo.studentId }}</span>
              </div>
            </div>
            <div class="info-item" v-if="!isStudent">
              <div class="info-icon">
                <el-icon><User /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">账号</span>
                <span class="info-value">{{ formInfo.studentId }}</span>
              </div>
            </div>

            <div class="info-item">
              <div class="info-icon">
                <el-icon><Calendar /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">最近登录</span>
                <span class="info-value">{{ formInfo.lastLoginTime }}</span>
              </div>
            </div>
          </div>

          <!-- 绿色提示标语 -->
          <div class="slogan-box">
            <div class="slogan-icon">
              <el-icon><Sunrise /></el-icon>
            </div>
            <p class="slogan-text">低碳生活，从我做起！</p>
          </div>

          <!-- 个性签名 -->
          <div class="signature-box">
            <el-icon class="quote-icon"><ChatLineSquare /></el-icon>
            <p class="signature-text">{{ formInfo.signature || '这个人很懒，什么都没写~' }}</p>
          </div>
        </div>
      </el-col>

      <!-- 右侧：功能设置面板 -->
      <el-col :xs="24" :sm="24" :md="16" :lg="17" :xl="18">
        <el-card class="settings-card" shadow="never">
          <el-tabs v-model="activeTab" class="settings-tabs">
            <!-- Tab 1: 编辑资料 -->
            <el-tab-pane name="profile">
              <template #label>
                <span class="tab-label">
                  <el-icon><EditPen /></el-icon>
                  <span>编辑资料</span>
                </span>
              </template>

              <div class="tab-content">
                <div class="section-header">
                  <h3 class="section-title">个人资料</h3>
                  <p class="section-desc">更新您的头像、昵称和个性签名</p>
                </div>

                <el-form label-position="top" class="profile-form">
                  <!-- 头像上传 -->
                  <el-form-item label="头像">
                    <div class="avatar-upload-area">
                      <div class="preview-avatar">
                        <el-avatar :size="80" :src="getAvatarUrl()">
                          {{ (formInfo.nickname || formInfo.realName)?.charAt(0) || 'U' }}
                        </el-avatar>
                        <div v-if="uploadingAvatar" class="uploading-overlay">
                          <el-icon class="is-loading"><Loading /></el-icon>
                        </div>
                      </div>
                      <div class="upload-actions">
                        <el-upload
                          action="#"
                          :auto-upload="false"
                          :show-file-list="false"
                          :on-change="handleAvatarChange"
                          :disabled="uploadingAvatar"
                          accept="image/*"
                        >
                          <el-button type="primary" plain :loading="uploadingAvatar">
                            <el-icon v-if="!uploadingAvatar"><Upload /></el-icon>
                            {{ uploadingAvatar ? '上传中...' : '上传新头像' }}
                          </el-button>
                        </el-upload>
                        <p class="upload-tip">支持 JPG、PNG 格式，文件小于 2MB</p>
                      </div>
                    </div>
                  </el-form-item>

                  <!-- 昵称 -->
                  <el-form-item label="昵称">
                    <el-input 
                      v-model="formInfo.nickname" 
                      :disabled="!isStudent"
                      :placeholder="isStudent ? '请输入昵称（用于显示）' : '管理员昵称'" 
                      maxlength="20"
                      show-word-limit
                      class="form-input"
                    >
                      <template #prefix>
                        <el-icon><User /></el-icon>
                      </template>
                    </el-input>
                    <div class="form-hint" v-if="!isStudent">
                      <el-icon><Warning /></el-icon>
                      管理员昵称由系统设定，无法修改
                    </div>
                    <div class="form-hint" v-else>
                      <el-icon><InfoFilled /></el-icon>
                      昵称将显示在排行榜等公开页面
                    </div>
                  </el-form-item>

                  <!-- 个性签名 -->
                  <el-form-item label="个性签名">
                    <el-input 
                      v-model="formInfo.signature" 
                      type="textarea"
                      :rows="3"
                      placeholder="写点什么介绍一下自己吧..."
                      maxlength="100"
                      show-word-limit
                      class="form-input"
                    />
                  </el-form-item>

                  <!-- 保存按钮 -->
                  <el-form-item>
                    <el-button 
                      type="primary" 
                      size="large"
                      @click="handleUpdateProfile"
                      :loading="saving"
                      class="save-btn"
                    >
                      <el-icon v-if="!saving"><Check /></el-icon>
                      保存修改
                    </el-button>
                  </el-form-item>
                </el-form>
              </div>
            </el-tab-pane>

            <!-- Tab 2: 安全设置 -->
            <el-tab-pane name="security">
              <template #label>
                <span class="tab-label">
                  <el-icon><Lock /></el-icon>
                  <span>安全设置</span>
                </span>
              </template>

              <div class="tab-content">
                <!-- 登录密码 -->
                <div class="security-section">
                  <div class="section-header">
                    <div class="section-icon primary-icon">
                      <el-icon><Key /></el-icon>
                    </div>
                    <div>
                      <h3 class="section-title">登录密码</h3>
                      <p class="section-desc">定期修改密码可以保护账号安全</p>
                    </div>
                  </div>

                  <el-form 
                    ref="loginPwdFormRef" 
                    :model="formPwd" 
                    :rules="loginPwdRules" 
                    label-position="top"
                    class="security-form"
                  >
                    <el-row :gutter="20">
                      <el-col :xs="24" :sm="24" :md="8">
                        <el-form-item label="原密码" prop="old">
                          <el-input 
                            v-model="formPwd.old" 
                            type="password" 
                            show-password 
                            placeholder="请输入原密码"
                            class="form-input"
                          />
                        </el-form-item>
                      </el-col>
                      <el-col :xs="24" :sm="12" :md="8">
                        <el-form-item label="新密码" prop="new">
                          <el-input 
                            v-model="formPwd.new" 
                            type="password" 
                            show-password 
                            placeholder="至少6位字符"
                            class="form-input"
                          />
                        </el-form-item>
                      </el-col>
                      <el-col :xs="24" :sm="12" :md="8">
                        <el-form-item label="确认新密码" prop="confirm">
                          <el-input 
                            v-model="formPwd.confirm" 
                            type="password" 
                            show-password 
                            placeholder="再次输入新密码"
                            class="form-input"
                          />
                        </el-form-item>
                      </el-col>
                    </el-row>
                    <el-form-item>
                      <el-button 
                        type="primary" 
                        @click="handleChangeLoginPwd" 
                        :loading="changingLoginPwd"
                        class="action-btn"
                      >
                        <el-icon v-if="!changingLoginPwd"><Refresh /></el-icon>
                        修改登录密码
                      </el-button>
                    </el-form-item>
                  </el-form>
                </div>

                <!-- 支付密码（仅学生可见） -->
                <div class="security-section payment-section" v-if="isStudent">
                  <div class="section-header">
                    <div class="section-icon success-icon">
                      <el-icon><Wallet /></el-icon>
                    </div>
                    <div>
                      <h3 class="section-title">资产安全</h3>
                      <p class="section-desc">支付密码用于积分兑换等敏感操作（6位纯数字）</p>
                    </div>
                  </div>

                  <el-form 
                    ref="payFormRef" 
                    :model="formPay" 
                    :rules="payRules" 
                    label-position="top"
                    class="security-form"
                  >
                    <el-row :gutter="20">
                      <el-col :xs="24" :sm="24" :md="8">
                        <el-form-item label="原支付密码" prop="old">
                          <el-input 
                            v-model="formPay.old" 
                            type="password" 
                            show-password 
                            :placeholder="hasPaymentPassword ? '请输入原支付密码' : '首次设置，无需输入'"
                            maxlength="6"
                            class="form-input"
                            :disabled="!hasPaymentPassword"
                          />
                        </el-form-item>
                      </el-col>
                      <el-col :xs="24" :sm="12" :md="8">
                        <el-form-item label="新支付密码" prop="new">
                          <el-input 
                            v-model="formPay.new" 
                            type="password" 
                            show-password 
                            placeholder="6位数字密码"
                            maxlength="6"
                            class="form-input"
                          />
                        </el-form-item>
                      </el-col>
                      <el-col :xs="24" :sm="12" :md="8">
                        <el-form-item label="确认支付密码" prop="confirm">
                          <el-input 
                            v-model="formPay.confirm" 
                            type="password" 
                            show-password 
                            placeholder="再次输入确认"
                            maxlength="6"
                            class="form-input"
                          />
                        </el-form-item>
                      </el-col>
                    </el-row>
                    <el-form-item>
                      <div class="payment-actions">
                        <el-button 
                          type="success" 
                          @click="handleSetPayPwd" 
                          :loading="settingPayPwd"
                          class="action-btn"
                        >
                          <el-icon v-if="!settingPayPwd"><CircleCheck /></el-icon>
                          {{ hasPaymentPassword ? '修改支付密码' : '设置支付密码' }}
                        </el-button>
                        <el-button 
                          v-if="hasPaymentPassword"
                          type="danger" 
                          @click="handleRemovePayPwd" 
                          :loading="removingPayPwd"
                          class="action-btn remove-pwd-btn"
                        >
                          <el-icon v-if="!removingPayPwd"><Lock /></el-icon>
                          关闭安全密码
                        </el-button>
                      </div>
                    </el-form-item>
                  </el-form>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { getUserInfo, updateProfile, changePassword, setPaymentPassword, removePaymentPassword, uploadAvatar } from '@/api/user'
import { 
  Lock, Wallet, User, Medal, Key, Check, Refresh, CircleCheck,
  EditPen, Calendar, ChatLineSquare, Upload, Warning, Sunrise,
  InfoFilled, Loading
} from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()
const isStudent = computed(() => userStore.role === 'student')

// UI State
const activeTab = ref('profile')
const saving = ref(false)
const changingLoginPwd = ref(false)
const settingPayPwd = ref(false)
const removingPayPwd = ref(false)

// Forms Refs
const loginPwdFormRef = ref()
const payFormRef = ref()

// 基础资料（带更多字段）
const formInfo = reactive({
  avatar: '', 
  nickname: '',
  realName: '', // 真实姓名
  signature: '',
  lastLoginTime: '',
  studentId: ''
})

// 头像上传相关
const avatarFile = ref(null)
const avatarPreviewUrl = ref('')
const uploadingAvatar = ref(false)

// 是否已设置支付密码（用于判断是否需要原密码）
const hasPaymentPassword = ref(false)

// 登录密码表单
const formPwd = reactive({ old: '', new: '', confirm: '' })
const validatePwdConfirm = (rule, value, callback) => {
  if (value !== formPwd.new) callback(new Error('两次输入密码不一致'))
  else callback()
}
const loginPwdRules = {
  old: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new: [{ required: true, message: '请输入新密码', trigger: 'blur' }, { min: 6, message: '至少6位', trigger: 'blur' }],
  confirm: [{ required: true, message: '请确认密码', trigger: 'blur' }, { validator: validatePwdConfirm, trigger: 'blur' }]
}

// 支付密码表单
const formPay = reactive({ old: '', new: '', confirm: '' })
const validatePayNum = (rule, value, callback) => {
  if (!/^\d{6}$/.test(value)) callback(new Error('支付密码必须是6位数字'))
  else callback()
}
const validatePayConfirm = (rule, value, callback) => {
  if (value !== formPay.new) callback(new Error('两次输入不一致'))
  else callback()
}
const validatePayOld = (rule, value, callback) => {
  // 如果已设置过支付密码，则原密码必填
  if (hasPaymentPassword.value && (!value || value === '')) {
    callback(new Error('请输入原支付密码'))
  } else {
    callback()
  }
}
const payRules = {
  old: [{ validator: validatePayOld, trigger: 'blur' }],
  new: [{ required: true, message: '请设置新支付密码', trigger: 'blur' }, { validator: validatePayNum, trigger: 'blur' }],
  confirm: [{ required: true, message: '请确认支付密码', trigger: 'blur' }, { validator: validatePayConfirm, trigger: 'blur' }]
}

// 获取头像完整URL的辅助函数（添加时间戳防止缓存）
const getAvatarUrl = () => {
  let avatarUrl = ''
  
  // 优先使用预览URL（刚上传的头像）
  if (avatarPreviewUrl.value && avatarPreviewUrl.value.trim() !== '') {
    avatarUrl = avatarPreviewUrl.value
  } else if (formInfo.avatar && formInfo.avatar.trim() !== '') {
    // 如果没有预览URL，使用formInfo中的avatar
    // 如果是完整URL，直接使用
    if (formInfo.avatar.startsWith('http')) {
      avatarUrl = formInfo.avatar
    } else if (formInfo.avatar.startsWith('/api')) {
      // 如果是相对路径，转换为完整URL
      avatarUrl = `http://localhost:8080${formInfo.avatar}`
    } else {
      // 如果路径不完整，尝试补全
      avatarUrl = `http://localhost:8080/api${formInfo.avatar}`
    }
  }
  
  // 如果没有头像，返回空字符串，显示默认头像
  if (!avatarUrl) {
    return ''
  }
  
  // 添加时间戳参数防止浏览器缓存（每次上传后都会更新）
  // 如果URL已经包含查询参数，使用&；否则使用?
  const separator = avatarUrl.includes('?') ? '&' : '?'
  return `${avatarUrl}${separator}_t=${Date.now()}`
}

// 获取用户信息
const fetchUserInfo = async () => {
  try {
    const response = await getUserInfo()
    if (response.code === 200) {
      const data = response.data
      formInfo.nickname = data.nickname || ''
      formInfo.realName = data.username || '' // 真实姓名
      formInfo.studentId = data.studentId || ''
      formInfo.avatar = data.avatar || ''
      formInfo.signature = data.signature || ''
      formInfo.lastLoginTime = data.lastLoginTime || '从未登录'
      
      // 设置头像预览URL（清空预览URL，让getAvatarUrl函数处理URL生成和缓存问题）
      // 这样每次获取用户信息时，都会使用最新的avatar URL
      avatarPreviewUrl.value = ''
      
      // 检查是否已设置支付密码
      hasPaymentPassword.value = data.hasPaymentPassword || false
    }
  } catch (error) {
    console.error('获取用户信息失败:', error)
  }
}

// Actions
const handleAvatarChange = async (file) => {
  if (!file.raw) return
  
  // 验证文件类型
  const isImage = file.raw.type.startsWith('image/')
  if (!isImage) {
    ElMessage.warning('只能上传图片文件')
    return
  }
  
  // 验证文件大小（2MB）
  if (file.raw.size > 2 * 1024 * 1024) {
    ElMessage.warning('图片大小不能超过2MB')
    return
  }
  
  avatarFile.value = file.raw
  avatarPreviewUrl.value = URL.createObjectURL(file.raw)
  
  // 立即上传头像
  uploadingAvatar.value = true
  try {
    const response = await uploadAvatar(file.raw)
    if (response.code === 200) {
      const avatarUrl = response.data
      formInfo.avatar = avatarUrl
      
      // 更新预览URL（添加时间戳防止缓存）
      let fullUrl = ''
      if (avatarUrl.startsWith('http')) {
        fullUrl = avatarUrl
      } else {
        // 如果URL已经包含/api，直接使用；否则添加
        fullUrl = avatarUrl.startsWith('/api') 
          ? `http://localhost:8080${avatarUrl}`
          : `http://localhost:8080/api${avatarUrl}`
      }
      // 添加时间戳，确保每次上传后URL都不同，强制浏览器刷新
      avatarPreviewUrl.value = `${fullUrl}?_t=${Date.now()}`
      
      // 上传成功后立即更新数据库
      try {
        const updateData = {
          avatar: avatarUrl,
          signature: formInfo.signature || ''
        }
        // 只有学生才传昵称字段
        if (isStudent.value) {
          updateData.nickname = formInfo.nickname ? formInfo.nickname.trim() : ''
        }
        await updateProfile(updateData)
        
        // 更新成功后，重新获取用户信息以确保数据同步
        await fetchUserInfo()
        
        ElMessage.success('头像上传并保存成功')
      } catch (updateError) {
        // 如果更新失败，只提示上传成功，不提示保存失败（避免重复错误提示）
        console.error('更新头像URL到数据库失败:', updateError)
        ElMessage.success('头像上传成功')
      }
    }
  } catch (error) {
    console.error('上传头像失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
    // 恢复原来的头像
    if (formInfo.avatar) {
      if (formInfo.avatar.startsWith('http')) {
        avatarPreviewUrl.value = formInfo.avatar
      } else {
        const avatarUrl = formInfo.avatar.startsWith('/api') 
          ? `http://localhost:8080${formInfo.avatar}`
          : `http://localhost:8080/api${formInfo.avatar}`
        avatarPreviewUrl.value = avatarUrl
      }
    } else {
      avatarPreviewUrl.value = ''
    }
    avatarFile.value = null
  } finally {
    uploadingAvatar.value = false
  }
}

const handleUpdateProfile = async () => {
  // 学生必须填写昵称
  if (isStudent.value && (!formInfo.nickname || formInfo.nickname.trim() === '')) {
    ElMessage.warning('请输入昵称')
    return
  }
  
  saving.value = true
  try {
    // 保存当前头像URL和预览URL，避免被重新获取覆盖
    const currentAvatarUrl = formInfo.avatar
    const currentPreviewUrl = avatarPreviewUrl.value
    
    // 构建更新数据：管理员不传昵称字段
    const updateData = {
      avatar: formInfo.avatar || '',
      signature: formInfo.signature || ''
    }
    
    // 只有学生才传昵称字段
    if (isStudent.value) {
      updateData.nickname = formInfo.nickname ? formInfo.nickname.trim() : ''
    }
    
    const response = await updateProfile(updateData)
    
    if (response.code === 200) {
      ElMessage.success('个人资料已更新')
      // 保存成功后，不重新获取用户信息，直接使用当前表单数据
      // 这样可以避免覆盖刚刚上传的新头像
      // 如果需要同步其他字段（如lastLoginTime），可以只更新那些字段
      
      // 确保头像预览URL保持最新
      if (currentAvatarUrl) {
        formInfo.avatar = currentAvatarUrl
        if (currentPreviewUrl) {
          avatarPreviewUrl.value = currentPreviewUrl
        } else {
          // 如果没有预览URL，根据avatar URL生成
          if (currentAvatarUrl.startsWith('http')) {
            avatarPreviewUrl.value = currentAvatarUrl
          } else {
            const avatarUrl = currentAvatarUrl.startsWith('/api') 
              ? `http://localhost:8080${currentAvatarUrl}`
              : `http://localhost:8080/api${currentAvatarUrl}`
            avatarPreviewUrl.value = avatarUrl
          }
        }
      }
    }
  } catch (error) {
    console.error('更新个人信息失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    saving.value = false
  }
}

const handleChangeLoginPwd = async () => {
  try {
    await loginPwdFormRef.value.validate()
    
    changingLoginPwd.value = true
    const response = await changePassword({
      oldPassword: formPwd.old,
      newPassword: formPwd.new,
      confirmPassword: formPwd.confirm
    })
    
    if (response.code === 200) {
      ElMessage.success('登录密码修改成功，请重新登录')
      loginPwdFormRef.value.resetFields()
      
      // 提示重新登录
      await ElMessageBox.confirm('密码已修改，请重新登录', '提示', {
        confirmButtonText: '确定',
        showCancelButton: false,
        type: 'success'
      })
      
      // 退出登录
      userStore.logout()
      router.push('/login')
    }
  } catch (error) {
    console.error('修改密码失败:', error)
  } finally {
    changingLoginPwd.value = false
  }
}

const handleSetPayPwd = async () => {
  try {
    await payFormRef.value.validate()
    
    settingPayPwd.value = true
    const response = await setPaymentPassword({
      oldPassword: formPay.old || undefined, // 首次设置时可以为空
      newPassword: formPay.new,
      confirmPassword: formPay.confirm
    })
    
    if (response.code === 200) {
      ElMessage.success('支付密码设置成功，您的积分更安全了')
      payFormRef.value.resetFields()
      hasPaymentPassword.value = true
    }
  } catch (error) {
    console.error('设置支付密码失败:', error)
  } finally {
    settingPayPwd.value = false
  }
}

const handleRemovePayPwd = async () => {
  try {
    await ElMessageBox.confirm(
      '关闭安全密码后，支付时将不再需要输入密码。确定要关闭吗？',
      '关闭安全密码',
      {
        confirmButtonText: '确定关闭',
        cancelButtonText: '取消',
        type: 'warning',
        showClose: false
      }
    )
    
    // 输入支付密码验证
    const { value } = await ElMessageBox.prompt('请输入支付密码以确认', '安全验证', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputType: 'password',
      inputPlaceholder: '请输入6位数字支付密码',
      inputPattern: /^\d{6}$/,
      inputErrorMessage: '支付密码必须是6位数字',
      showClose: false
    })
    
    removingPayPwd.value = true
    const response = await removePaymentPassword({
      paymentPassword: value
    })
    
    if (response.code === 200) {
      ElMessage.success('安全密码已关闭')
      hasPaymentPassword.value = false
      payFormRef.value.resetFields()
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('关闭安全密码失败:', error)
      // 错误消息已在 request.js 拦截器中统一处理
    }
  } finally {
    removingPayPwd.value = false
  }
}

// 组件挂载时获取用户信息
onMounted(() => {
  fetchUserInfo()
})
</script>

<style scoped>
/* ========== 页面容器 ========== */
.user-info-page {
  padding: 20px;
  min-height: 100%;
  background: linear-gradient(160deg, #f0f4f8 0%, #e2e8f0 100%);
}

/* ========== 左侧个人卡片 ========== */
.profile-card {
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 20px;
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.06),
    0 10px 20px -2px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  margin-bottom: 24px;
}

/* Banner 区域 */
.card-banner {
  position: relative;
  height: 120px;
  background: linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%);
  overflow: hidden;
}

.banner-pattern {
  position: absolute;
  inset: 0;
  background-image: 
    radial-gradient(circle at 20% 80%, rgba(255,255,255,0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 20%, rgba(255,255,255,0.1) 0%, transparent 40%),
    radial-gradient(circle at 40% 40%, rgba(255,255,255,0.08) 0%, transparent 30%);
}

.banner-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, transparent 50%, rgba(255,255,255,0.1) 100%);
}

/* 头像区域 - 使用 margin-top 负值实现悬浮效果 */
.avatar-section {
  position: relative;
  display: flex;
  justify-content: center;
  margin-top: -50px;
  z-index: 1;
}

.avatar-wrapper {
  position: relative;
  padding: 5px;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
}

.user-avatar {
  font-size: 36px;
  font-weight: 600;
  color: #059669;
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
}

.avatar-border {
  position: absolute;
  inset: -3px;
  border: 3px solid #10b981;
  border-radius: 50%;
  opacity: 0.5;
}

.online-dot {
  position: absolute;
  bottom: 8px;
  right: 8px;
  width: 14px;
  height: 14px;
  background: #22c55e;
  border: 3px solid #fff;
  border-radius: 50%;
}

/* 用户元信息 */
.user-meta {
  text-align: center;
  padding: 16px 20px 12px;
}

.user-name {
  margin: 0 0 10px;
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  letter-spacing: -0.5px;
}

.role-tag {
  font-size: 12px;
  padding: 6px 16px;
  border-radius: 20px;
  height: auto;
}

.role-tag-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.role-tag-content .el-icon {
  font-size: 14px;
}

/* 信息列表 */
.info-list {
  padding: 12px 20px 8px;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.info-item:last-child {
  border-bottom: none;
}

.info-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  border-radius: 10px;
  color: #64748b;
  font-size: 16px;
  flex-shrink: 0;
}

.info-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-label {
  font-size: 12px;
  color: #94a3b8;
}

.info-value {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

/* 绿色提示标语 */
.slogan-box {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 20px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
  border-radius: 12px;
  border: 1px solid #a7f3d0;
}

.slogan-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #10b981 0%, #34d399 100%);
  border-radius: 50%;
  color: #fff;
  font-size: 18px;
  flex-shrink: 0;
}

.slogan-text {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #059669;
  letter-spacing: 0.5px;
}

/* 个性签名区域 */
.signature-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  margin: 0 20px 20px;
  padding: 18px 20px;
  background: linear-gradient(160deg, #fafbfc 0%, #f1f5f9 100%);
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  min-height: 80px;
}

.quote-icon {
  color: #94a3b8;
  font-size: 18px;
  margin-bottom: 8px;
}

.signature-text {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.7;
  font-style: italic;
}

/* ========== 右侧设置面板 ========== */
.settings-card {
  border-radius: 20px;
  border: none;
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.06),
    0 10px 20px -2px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.settings-card :deep(.el-card__body) {
  padding: 0;
}

/* Tabs 样式 */
.settings-tabs {
  --el-tabs-header-height: 56px;
}

.settings-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 28px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}

.settings-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.settings-tabs :deep(.el-tabs__item) {
  height: 56px;
  line-height: 56px;
  font-size: 14px;
  color: #64748b;
  padding: 0 20px;
  transition: all 0.25s ease;
}

.settings-tabs :deep(.el-tabs__item:hover) {
  color: #059669;
}

.settings-tabs :deep(.el-tabs__item.is-active) {
  color: #059669;
  font-weight: 600;
}

.settings-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  background: linear-gradient(90deg, #059669 0%, #10b981 100%);
  border-radius: 3px 3px 0 0;
}

.settings-tabs :deep(.el-tabs__content) {
  padding: 0;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tab-content {
  padding: 28px;
}

/* Section 样式 */
.section-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #f1f5f9;
}

.section-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  flex-shrink: 0;
}

.section-icon.primary-icon {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
}

.section-icon.success-icon {
  background: linear-gradient(135deg, #0891b2 0%, #06b6d4 100%);
}

.section-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
}

.section-desc {
  margin: 0;
  font-size: 13px;
  color: #94a3b8;
}

/* 表单样式 */
.profile-form,
.security-form {
  max-width: 100%;
}

.profile-form :deep(.el-form-item),
.security-form :deep(.el-form-item) {
  margin-bottom: 22px;
}

.profile-form :deep(.el-form-item__label),
.security-form :deep(.el-form-item__label) {
  font-weight: 500;
  color: #475569;
  padding-bottom: 8px;
}

.form-input :deep(.el-input__wrapper),
.form-input :deep(.el-textarea__inner) {
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: none;
  border: 1px solid #e2e8f0;
  transition: all 0.25s ease;
}

.form-input :deep(.el-input__wrapper:hover),
.form-input :deep(.el-textarea__inner:hover) {
  border-color: #10b981;
}

.form-input :deep(.el-input__wrapper.is-focus),
.form-input :deep(.el-textarea__inner:focus) {
  border-color: #059669;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1);
}

.form-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  color: #f59e0b;
}

/* 头像上传区域 */
.avatar-upload-area {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px dashed #cbd5e1;
}

.preview-avatar :deep(.el-avatar) {
  font-size: 28px;
  font-weight: 600;
  color: #059669;
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2);
}

.upload-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.upload-tip {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
}

.preview-avatar {
  position: relative;
}

.uploading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 50%;
  z-index: 10;
}

.uploading-overlay .el-icon {
  font-size: 24px;
  color: #059669;
}

/* 按钮样式 */
.save-btn,
.action-btn {
  padding: 12px 28px;
  font-size: 14px;
  font-weight: 500;
  border-radius: 10px;
  transition: all 0.25s ease;
}

.save-btn {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  border: none;
}

.save-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(16, 185, 129, 0.35);
}

.action-btn {
  border: none;
}

.action-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}

/* 支付密码操作按钮组 */
.payment-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* 关闭安全密码按钮样式 */
.remove-pwd-btn {
  background: #f56c6c;
  border-color: #f56c6c;
  color: #fff;
}

.remove-pwd-btn:hover {
  background: #f78989;
  border-color: #f78989;
}

/* 安全设置区块 */
.security-section {
  padding: 24px;
  background: #f8fafc;
  border-radius: 16px;
  margin-bottom: 24px;
}

.security-section:last-child {
  margin-bottom: 0;
}

.payment-section {
  background: linear-gradient(135deg, #f0fdfa 0%, #ccfbf1 100%);
}

/* ========== 响应式适配 ========== */
@media screen and (max-width: 991px) {
  .user-info-page {
    padding: 16px;
  }
  
  .profile-card {
    margin-bottom: 20px;
  }
}

@media screen and (max-width: 767px) {
  .user-info-page {
    padding: 12px;
  }

  .tab-content {
    padding: 20px;
  }

  .avatar-upload-area {
    flex-direction: column;
    text-align: center;
  }

  .security-section {
    padding: 16px;
  }

  .section-header {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
}
</style>
