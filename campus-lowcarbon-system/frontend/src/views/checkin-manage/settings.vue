<template>
  <div class="settings-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">
          <span class="scene-icon">{{ sceneConfig.icon }}</span>
          {{ sceneConfig.title }} - 配置管理
        </h1>
        <p class="page-desc">{{ sceneConfig.description }}</p>
      </div>
    </div>

    <!-- 配置表单卡片 -->
    <el-card shadow="hover" class="settings-card">
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="180px"
        class="settings-form"
      >
        <!-- 最低步数/里程配置（步行和骑行） -->
        <el-form-item
          v-if="currentScene === 'walk' || currentScene === 'ride'"
          :label="sceneConfig.minValueLabel"
          prop="minValue"
        >
          <el-input-number
            v-model="formData.minValue"
            :min="0"
            :max="999999"
            :precision="currentScene === 'walk' ? 0 : 2"
            :step="currentScene === 'walk' ? 100 : 0.1"
            controls-position="right"
            style="width: 220px"
          />
          <span class="form-unit">{{ sceneConfig.unit }}</span>
          <el-text type="info" class="form-tip">
            {{ sceneConfig.minValueTip }}
          </el-text>
        </el-form-item>

        <!-- AI判断关键词配置 -->
        <el-form-item
          label="AI判断关键词"
          prop="keywords"
        >
          <div class="keywords-container">
            <el-tag
              v-for="(keyword, index) in formData.keywords"
              :key="index"
              closable
              @close="removeKeyword(index)"
              class="keyword-tag"
              type="success"
              effect="light"
            >
              {{ keyword }}
            </el-tag>
            <el-input
              v-if="inputVisible"
              ref="inputRef"
              v-model="inputValue"
              size="small"
              style="width: 150px"
              placeholder="输入关键词"
              @keyup.enter="handleKeywordConfirm"
              @blur="handleKeywordConfirm"
            />
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              @click="showInput"
            >
              <el-icon><Plus /></el-icon>
              添加关键词
            </el-button>
          </div>
          <el-text type="info" class="form-tip">
            用于强化AI判断，OCR识别到这些关键词时会提高通过率
          </el-text>
        </el-form-item>

        <!-- 排除关键词配置 -->
        <el-form-item
          label="排除关键词"
          prop="excludeKeywords"
        >
          <div class="keywords-container">
            <el-tag
              v-for="(keyword, index) in formData.excludeKeywords"
              :key="index"
              type="danger"
              closable
              @close="removeExcludeKeyword(index)"
              class="keyword-tag"
              effect="light"
            >
              {{ keyword }}
            </el-tag>
            <el-input
              v-if="excludeInputVisible"
              ref="excludeInputRef"
              v-model="excludeInputValue"
              size="small"
              style="width: 150px"
              placeholder="输入关键词"
              @keyup.enter="handleExcludeKeywordConfirm"
              @blur="handleExcludeKeywordConfirm"
            />
            <el-button
              v-else
              size="small"
              type="danger"
              plain
              @click="showExcludeInput"
            >
              <el-icon><Plus /></el-icon>
              添加排除关键词
            </el-button>
          </div>
          <el-text type="info" class="form-tip">
            识别到这些关键词时会降低通过率或直接拒绝
          </el-text>
        </el-form-item>

        <!-- 积分奖励配置 -->
        <el-form-item
          label="基础奖励积分"
          prop="rewardPoints"
        >
          <el-input-number
            v-model="formData.rewardPoints"
            :min="0"
            :max="100"
            :step="1"
            controls-position="right"
            style="width: 220px"
          />
          <span class="form-unit">积分</span>
          <el-text type="info" class="form-tip">
            用户完成打卡后可获得的基础积分奖励
          </el-text>
        </el-form-item>

        <!-- 每日打卡次数限制 -->
        <el-form-item
          label="每日打卡次数限制"
          prop="dailyLimit"
        >
          <el-input-number
            v-model="formData.dailyLimit"
            :min="0"
            :max="10"
            :step="1"
            controls-position="right"
            style="width: 220px"
          />
          <span class="form-unit">次</span>
          <el-text type="info" class="form-tip">
            每个用户每天最多可打卡的次数（0表示不限制）
          </el-text>
        </el-form-item>

        <!-- 动态积分奖励配置（仅步行和骑行） -->
        <template v-if="currentScene === 'walk' || currentScene === 'ride'">
          <el-form-item
            :label="currentScene === 'walk' ? '每多走多少步增加积分' : '每多骑多少km增加积分'"
            prop="bonusStep"
          >
            <el-input-number
              v-model="formData.bonusStep"
              :min="0"
              :max="999999"
              :precision="currentScene === 'walk' ? 0 : 2"
              :step="currentScene === 'walk' ? 100 : 0.1"
              controls-position="right"
              style="width: 220px"
            />
            <span class="form-unit">{{ currentScene === 'walk' ? '步' : 'km' }}</span>
            <el-text type="info" class="form-tip">
              每达到此数值，将在基础积分上增加一定百分比
            </el-text>
          </el-form-item>

          <el-form-item
            label="积分增加百分比"
            prop="bonusPercentage"
          >
            <el-input-number
              v-model="formData.bonusPercentage"
              :min="0"
              :max="100"
              :precision="2"
              :step="1"
              controls-position="right"
              style="width: 220px"
            />
            <span class="form-unit">%</span>
            <el-text type="info" class="form-tip">
              每达到bonus_step时，基础积分增加的百分比（如10表示增加10%）
            </el-text>
          </el-form-item>
        </template>

        <!-- 提交按钮 -->
        <el-form-item>
          <el-button type="primary" size="large" @click="handleSubmit" :loading="isSubmitting">
            <el-icon v-if="!isSubmitting"><Check /></el-icon>
            保存配置
          </el-button>
          <el-button size="large" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Check } from '@element-plus/icons-vue'
import { useCheckinStore } from '@/stores/checkin'
import { updateSceneConfig, getSceneConfig, refreshAIConfig } from '@/api/sceneConfig'

const route = useRoute()
const checkinStore = useCheckinStore()

// 当前场景
const currentScene = computed(() => {
  return route.meta.scene || 'walk'
})

// 场景配置元数据（UI显示用，不从后端获取）
const sceneConfigMeta = {
  walk: {
    description: '配置步数识别的最低要求和AI判断规则',
    minValueLabel: '最低步数要求',
    minValueTip: '用户上传的步数截图需达到此数值才能通过验证'
  },
  ride: {
    description: '配置骑行里程识别的最低要求和AI判断规则',
    minValueLabel: '最低里程要求',
    minValueTip: '用户上传的骑行截图需达到此里程才能通过验证'
  },
  plate: {
    description: '配置AI判断规则和关键词',
    minValueLabel: '',
    minValueTip: ''
  },
  transit: {
    description: '配置票据识别和AI判断规则',
    minValueLabel: '',
    minValueTip: ''
  }
}

// 场景配置（从store获取，包含后端数据）
const sceneConfig = computed(() => {
  const storeConfig = checkinStore.getSceneConfig(currentScene.value)
  const meta = sceneConfigMeta[currentScene.value] || {}
  return {
    icon: storeConfig.icon || '',
    title: storeConfig.title || '',
    tag: storeConfig.tag || '',
    tagType: storeConfig.tagType || 'primary',
    unit: storeConfig.unit || '',
    ...meta
  }
})

// 表单引用
const formRef = ref(null)
const inputRef = ref(null)
const excludeInputRef = ref(null)

// 表单数据（从后端加载，初始值为空）
const formData = reactive({
  minValue: 0,
  keywords: [],
  excludeKeywords: [],
  rewardPoints: 0,
  dailyLimit: 3,
  bonusStep: null,
  bonusPercentage: 10.00
})

// 关键词输入
const inputVisible = ref(false)
const inputValue = ref('')
const excludeInputVisible = ref(false)
const excludeInputValue = ref('')

// 提交状态
const isSubmitting = ref(false)

// 表单验证规则
const formRules = {
  minValue: [
    { required: true, message: '请输入最低要求', trigger: 'blur' }
  ],
  rewardPoints: [
    { required: true, message: '请输入奖励积分', trigger: 'blur' }
  ],
  dailyLimit: [
    { required: true, message: '请输入每日打卡次数限制', trigger: 'blur' }
  ]
}

// 初始化数据（从后端获取）
const initData = async () => {
  try {
    // 从后端API获取当前场景的配置
    const response = await getSceneConfig(currentScene.value)
    const config = response.data
    
    if (config) {
      // 更新表单数据
      formData.minValue = config.minValue ? Number(config.minValue) : 0
      formData.keywords = [...(config.keywords || [])]
      formData.excludeKeywords = [...(config.excludeKeywords || [])]
      formData.rewardPoints = config.rewardPoints || 10
      formData.dailyLimit = config.dailyLimit !== undefined ? config.dailyLimit : 3
      formData.bonusStep = config.bonusStep ? Number(config.bonusStep) : null
      formData.bonusPercentage = config.bonusPercentage ? Number(config.bonusPercentage) : 10.00
      
      // 同步更新store
      checkinStore.updateSceneConfig(currentScene.value, {
        icon: config.icon,
        title: config.title,
        tag: config.tag,
        tagType: config.tagType,
        rewardPoints: config.rewardPoints,
        requirementText: config.requirementText,
        minValue: config.minValue ? Number(config.minValue) : null,
        unit: config.unit,
        keywords: config.keywords || [],
        excludeKeywords: config.excludeKeywords || []
      })
    } else {
      // 如果后端没有数据，从store读取默认值
      const storeConfig = checkinStore.getSceneConfig(currentScene.value)
      formData.minValue = storeConfig.minValue || 0
      formData.keywords = [...(storeConfig.keywords || [])]
      formData.excludeKeywords = [...(storeConfig.excludeKeywords || [])]
      formData.rewardPoints = storeConfig.rewardPoints || 10
      formData.dailyLimit = storeConfig.dailyLimit !== undefined ? storeConfig.dailyLimit : 3
      formData.bonusStep = storeConfig.bonusStep ? Number(storeConfig.bonusStep) : null
      formData.bonusPercentage = storeConfig.bonusPercentage ? Number(storeConfig.bonusPercentage) : 10.00
    }
  } catch (error) {
    console.error('加载配置失败:', error)
    // 如果加载失败，从store读取
    const config = checkinStore.getSceneConfig(currentScene.value)
    formData.minValue = config.minValue || 0
    formData.keywords = [...(config.keywords || [])]
    formData.excludeKeywords = [...(config.excludeKeywords || [])]
    formData.rewardPoints = config.rewardPoints || 10
  }
}

// 显示关键词输入框
const showInput = () => {
  inputVisible.value = true
  nextTick(() => {
    inputRef.value?.focus()
  })
}

// 确认添加关键词
const handleKeywordConfirm = () => {
  if (inputValue.value && !formData.keywords.includes(inputValue.value)) {
    formData.keywords.push(inputValue.value)
  }
  inputVisible.value = false
  inputValue.value = ''
}

// 移除关键词
const removeKeyword = (index) => {
  formData.keywords.splice(index, 1)
}

// 显示排除关键词输入框
const showExcludeInput = () => {
  excludeInputVisible.value = true
  nextTick(() => {
    excludeInputRef.value?.focus()
  })
}

// 确认添加排除关键词
const handleExcludeKeywordConfirm = () => {
  if (excludeInputValue.value && !formData.excludeKeywords.includes(excludeInputValue.value)) {
    formData.excludeKeywords.push(excludeInputValue.value)
  }
  excludeInputVisible.value = false
  excludeInputValue.value = ''
}

// 移除排除关键词
const removeExcludeKeyword = (index) => {
  formData.excludeKeywords.splice(index, 1)
}

// 生成提示文字
const generateRequirementText = () => {
  const scene = currentScene.value
  if (scene === 'walk') {
    return `请上传微信运动或手环APP的今日步数截图，步数需超过 ${formData.minValue} 步。`
  } else if (scene === 'ride') {
    return `请上传共享单车行程结束截图，骑行距离需大于 ${formData.minValue}km。`
  } else if (scene === 'plate') {
    return '请上传空盘照片，系统将通过AI识别进行验证。'
  } else if (scene === 'transit') {
    return '请上传乘车扣费记录或电子车票，日期需为今日。'
  }
  return ''
}

// 提交表单
const handleSubmit = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
    isSubmitting.value = true
    
    // 生成提示文字
    const requirementText = generateRequirementText()
    
    // 准备提交数据
    // 注意：如果icon、title等字段为空字符串，不提交这些字段（让后端保留原有值）
    const submitData = {
      rewardPoints: formData.rewardPoints,
      requirementText: requirementText,
      minValue: formData.minValue || null,
      keywords: formData.keywords,
      excludeKeywords: formData.excludeKeywords,
      dailyLimit: formData.dailyLimit,
      bonusStep: (currentScene.value === 'walk' || currentScene.value === 'ride') && formData.bonusStep ? formData.bonusStep : null,
      bonusPercentage: (currentScene.value === 'walk' || currentScene.value === 'ride') && formData.bonusPercentage ? formData.bonusPercentage : null
    }
    
    // 只有当icon、title等字段有值时才提交（避免覆盖数据库中的原有值）
    if (sceneConfig.value.icon) {
      submitData.icon = sceneConfig.value.icon
    }
    if (sceneConfig.value.title) {
      submitData.title = sceneConfig.value.title
    }
    if (sceneConfig.value.tag) {
      submitData.tag = sceneConfig.value.tag
    }
    if (sceneConfig.value.tagType) {
      submitData.tagType = sceneConfig.value.tagType
    }
    if (sceneConfig.value.unit) {
      submitData.unit = sceneConfig.value.unit
    }
    
    // 调用后端API保存配置
    await updateSceneConfig(currentScene.value, submitData)
    
    // 保存成功后，重新从后端加载配置（确保所有字段都被更新，包括icon、title等）
    await checkinStore.loadSceneConfig(currentScene.value)
    
    // 同步更新表单数据（确保表单显示最新数据）
    const updatedStoreConfig = checkinStore.getSceneConfig(currentScene.value)
    if (updatedStoreConfig) {
      formData.minValue = updatedStoreConfig.minValue || 0
      formData.keywords = [...(updatedStoreConfig.keywords || [])]
      formData.excludeKeywords = [...(updatedStoreConfig.excludeKeywords || [])]
      formData.rewardPoints = updatedStoreConfig.rewardPoints || 10
      formData.dailyLimit = updatedStoreConfig.dailyLimit !== undefined ? updatedStoreConfig.dailyLimit : 3
      formData.bonusStep = updatedStoreConfig.bonusStep ? Number(updatedStoreConfig.bonusStep) : null
      formData.bonusPercentage = updatedStoreConfig.bonusPercentage ? Number(updatedStoreConfig.bonusPercentage) : 10.00
    }
    
    // 刷新AI服务配置缓存（让AI服务使用最新配置）
    try {
      await refreshAIConfig()
    } catch (error) {
      // AI服务刷新失败不影响主流程，只记录警告
      console.warn('刷新AI配置缓存失败:', error)
    }
    
    ElMessage.success('配置保存成功，学生端和AI服务已同步更新')
  } catch (error) {
    // 错误消息已在request拦截器中处理
    console.error('保存失败:', error)
  } finally {
    isSubmitting.value = false
  }
}

// 重置表单（从后端重新加载）
const handleReset = async () => {
  try {
    // 从后端重新加载配置
    await checkinStore.resetToDefault(currentScene.value)
    // 重新加载表单数据
    await initData()
    ElMessage.info('已重置为最新配置')
  } catch (error) {
    console.error('重置失败:', error)
  }
}

// 监听路由变化，重新初始化数据
watch(
  () => route.meta.scene,
  () => {
    initData()
  },
  { immediate: true }
)
</script>

<style scoped>
.settings-page {
  padding: 24px;
  background: #f0f2f5;
  min-height: calc(100vh - 60px);
}

/* 页面标题 */
.page-header {
  margin-bottom: 24px;
  padding: 24px 28px;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(38, 166, 154, 0.25);
}

.header-content {
  color: #ffffff;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 26px;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 8px;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.scene-icon {
  font-size: 32px;
  line-height: 1;
}

.page-desc {
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  margin: 0;
  letter-spacing: 0.5px;
}

/* 配置卡片 */
.settings-card {
  border-radius: 16px;
  border: none;
}

:deep(.settings-card .el-card__body) {
  padding: 32px;
}

/* 表单 */
.settings-form {
  max-width: 900px;
}

:deep(.settings-form .el-form-item) {
  margin-bottom: 32px;
}

:deep(.settings-form .el-form-item__label) {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.form-unit {
  margin-left: 12px;
  color: #606266;
  font-size: 14px;
  font-weight: 500;
}

.form-tip {
  margin-left: 16px;
  font-size: 12px;
  line-height: 1.5;
}

/* 关键词容器 */
.keywords-container {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  min-height: 32px;
  padding: 8px;
  background: #fafbfc;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}

.keyword-tag {
  margin: 0;
  font-size: 13px;
  padding: 6px 12px;
}

/* 响应式 */
@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }
  
  .page-header {
    padding: 20px;
    border-radius: 12px;
  }
  
  .page-title {
    font-size: 20px;
  }
  
  .scene-icon {
    font-size: 24px;
  }
  
  :deep(.settings-form) {
    max-width: 100%;
  }
  
  :deep(.settings-form .el-form-item__label) {
    width: 100% !important;
    text-align: left;
  }
  
  .form-tip {
    margin-left: 0;
    margin-top: 8px;
    display: block;
  }
}
</style>
