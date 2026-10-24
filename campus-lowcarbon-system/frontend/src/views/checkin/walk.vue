<template>
  <div class="checkin-container">
    <div class="workspace">
      <!-- 场景标题区 -->
      <div class="workspace-header">
        <div class="header-left">
          <span class="header-emoji">{{ sceneConfig.icon }}</span>
          <div class="header-text">
            <h2>{{ sceneConfig.title }}</h2>
            <el-tag :type="sceneConfig.tagType" size="small">{{ sceneConfig.tag }}</el-tag>
          </div>
        </div>
        <div class="header-right">
          <span class="reward-label">完成可得</span>
          <span class="reward-value">+{{ sceneConfig.rewardPoints }}</span>
          <span class="reward-unit">积分</span>
        </div>
      </div>

      <!-- 打卡要求 -->
      <el-alert
        :title="requirementText"
        type="info"
        show-icon
        :closable="false"
        class="requirement-alert"
      />

      <!-- 测试模式开关（仅开发测试使用） -->
      <div class="test-mode-section">
        <el-switch
          v-model="testMode"
          active-text="测试模式"
          inactive-text="正常模式"
          :disabled="locationStatus !== 'idle'"
        />
        <span class="test-mode-hint" v-if="testMode">
          <el-icon><InfoFilled /></el-icon>
          测试模式下将使用模拟距离（1.5公里）
        </span>
      </div>

      <!-- 定位打卡控制区 -->
      <div class="location-control-section">
        <el-button
          v-if="locationStatus === 'idle'"
          type="primary"
          size="large"
          class="location-btn"
          :loading="isLocationLoading"
          @click="handleStartCheckin"
        >
          <el-icon><Location /></el-icon>
          开始打卡
        </el-button>
        <el-button
          v-else-if="locationStatus === 'in_progress'"
          type="warning"
          size="large"
          class="location-btn"
          :loading="isLocationLoading"
          @click="handleEndCheckin"
        >
          <el-icon><LocationFilled /></el-icon>
          结束打卡
        </el-button>
      </div>

      <!-- 智能上传区 -->
      <div class="upload-section">
        <el-upload
          ref="uploadRef"
          class="upload-dragger"
          drag
          action="#"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="handleFileChange"
          :disabled="!canUpload"
          accept="image/*"
        >
          <div class="upload-content" :class="{ 'disabled': !canUpload }">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">
              <p class="main-text">点击或拖拽上传凭证图片</p>
              <p class="sub-text">支持 JPG、PNG 格式，单文件不超过 5MB</p>
              <p class="hint-text" v-if="!canUpload">请先完成定位打卡</p>
            </div>
          </div>
        </el-upload>

        <!-- 图片预览 -->
        <div class="preview-area" v-if="previewUrl">
          <img :src="previewUrl" alt="预览图" class="preview-image" />
          <el-button type="danger" size="small" circle class="remove-btn" @click="removeImage">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>

        <!-- 提交按钮 -->
        <el-button
          v-if="previewUrl"
          type="primary"
          size="large"
          class="submit-btn"
          :loading="isVerifying"
          :disabled="!canUpload"
          @click="submitCheckin"
        >
          <el-icon v-if="!isVerifying"><Promotion /></el-icon>
          {{ isVerifying ? '核验中...' : '提交打卡' }}
        </el-button>
      </div>

      <!-- AI 核验遮罩 -->
      <div class="verify-overlay" v-if="isVerifying">
        <div class="verify-content">
          <div class="verify-animation">
            <div class="pulse-ring"></div>
            <div class="pulse-ring delay-1"></div>
            <div class="pulse-ring delay-2"></div>
            <el-icon :size="48" color="#26a69a"><Monitor /></el-icon>
          </div>
          <h3 class="verify-title">AI 正在核验中...</h3>
          <p class="verify-detail">{{ verifyDetail }}</p>
          <div class="verify-progress">
            <el-progress :percentage="verifyProgress" :show-text="false" color="#26a69a" />
          </div>
        </div>
      </div>

      <!-- 成功弹窗 -->
      <el-dialog
        v-model="showSuccess"
        :show-close="false"
        width="400px"
        center
        class="success-dialog"
      >
        <div class="success-content">
          <div class="success-icon">🎉</div>
          <h2 class="success-title">核验通过！</h2>
          <p class="success-desc">您的低碳行为已记录</p>
          <div class="success-reward" v-if="rewardPoints">
            <span class="reward-text">获得积分</span>
            <span class="reward-num">+{{ rewardPoints }}</span>
          </div>
          <el-button type="primary" size="large" @click="handleSuccessClose">
            继续打卡
          </el-button>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UploadFilled,
  Close,
  Promotion,
  Monitor,
  Location,
  LocationFilled,
  InfoFilled
} from '@element-plus/icons-vue'
import { verifyImage } from '@/api/verify'
import { saveCheckinRecord, startCheckinLocation, endCheckinLocation, checkDailyLimit } from '@/api/checkin'
import { useCheckinStore } from '@/stores/checkin'
import { useGameStore } from '@/stores/game'
import { getUserAssets, getUserStats, getAllTitles, getAllBadges } from '@/api/mall'
import { generateCheckinRequirementText } from '@/utils/checkinHelper'

const checkinStore = useCheckinStore()
const gameStore = useGameStore()

// 从store获取场景配置
const sceneConfig = computed(() => checkinStore.getSceneConfig('walk'))

// 动态生成打卡要求提示
const requirementText = computed(() => {
  return generateCheckinRequirementText(sceneConfig.value, 'walk')
})

// 上传相关
const uploadRef = ref(null)
const previewUrl = ref('')
const uploadedFile = ref(null)

// 定位相关
const locationStatus = ref('idle') // 'idle' | 'in_progress' | 'completed'
const locationId = ref(null) // 定位记录ID
const isLocationLoading = ref(false)
const canUpload = computed(() => locationStatus.value === 'completed') // 只有定位完成且距离满足要求才能上传

// 测试模式相关
const testMode = ref(false) // 测试模式开关
const startPosition = ref(null) // 保存起始位置，用于测试模式计算模拟结束位置

// 核验状态
const isVerifying = ref(false)
const verifyProgress = ref(0)
const verifyDetail = ref('正在上传图片...')
const showSuccess = ref(false)
const actualRewardPoints = ref(null) // 实际获得的积分（动态计算后的值）
const rewardPoints = computed(() => actualRewardPoints.value !== null ? actualRewardPoints.value : sceneConfig.value.rewardPoints)

// 页面加载时确保配置已加载
onMounted(async () => {
  // 强制加载最新配置，确保管理员修改后能及时更新
  try {
    await checkinStore.loadSceneConfig('walk')
  } catch (error) {
    console.error('加载场景配置失败:', error)
  }
})

// 处理文件选择
const handleFileChange = (file) => {
  if (!file.raw) return
  
  // 检查文件类型
  const isImage = file.raw.type.startsWith('image/')
  if (!isImage) {
    ElMessage.error('请上传图片文件')
    return
  }
  
  // 检查文件大小 (5MB)
  const isLt5M = file.raw.size / 1024 / 1024 < 5
  if (!isLt5M) {
    ElMessage.error('图片大小不能超过 5MB')
    return
  }
  
  uploadedFile.value = file.raw
  previewUrl.value = URL.createObjectURL(file.raw)
}

// 移除图片
const removeImage = () => {
  previewUrl.value = ''
  uploadedFile.value = null
}

// 获取当前位置
const getCurrentPosition = () => {
  return new Promise((resolve, reject) => {
    if (!window.BMap) {
      reject(new Error('百度地图API未加载'))
      return
    }
    
    const geolocation = new BMap.Geolocation()
    geolocation.getCurrentPosition((r) => {
      if (geolocation.getStatus() === window.BMAP_STATUS_SUCCESS) {
        resolve({
          latitude: r.point.lat,
          longitude: r.point.lng
        })
      } else {
        reject(new Error('获取位置失败，请检查定位权限'))
      }
    })
  })
}

// 开始打卡
const handleStartCheckin = async () => {
  try {
    isLocationLoading.value = true
    
    // 先检查每日打卡次数限制
    try {
      await checkDailyLimit('walk')
    } catch (error) {
      // 如果次数已用完，显示错误信息并返回
      // 注意：错误消息已经在后端返回，这里只需要提取并显示
      let errorMessage = '今日打卡次数已达上限，请明天再试'
      if (error.response && error.response.data) {
        // 优先使用后端返回的message
        if (error.response.data.message) {
          errorMessage = error.response.data.message
        } else if (error.response.data.data && error.response.data.data.message) {
          errorMessage = error.response.data.data.message
        }
      } else if (error.message) {
        errorMessage = error.message
      }
      ElMessage.error(errorMessage)
      return
    }
    
    // 获取当前位置
    const position = await getCurrentPosition()
    
    // 保存起始位置（用于测试模式）
    startPosition.value = {
      latitude: position.latitude,
      longitude: position.longitude
    }
    
    // 调用后端API记录起始位置
    const response = await startCheckinLocation('walk', position.latitude, position.longitude)
    
    if (response.code === 200) {
      locationId.value = response.data.id
      locationStatus.value = 'in_progress'
    } else {
      ElMessage.error(response.message || '开始打卡失败')
    }
  } catch (error) {
    console.error('开始打卡失败:', error)
    ElMessage.error(error.message || '获取位置失败，请检查定位权限')
  } finally {
    isLocationLoading.value = false
  }
}

// 计算模拟结束位置（基于起始位置向北移动1.5公里）
const calculateMockEndPosition = (startLat, startLng) => {
  // 1度纬度 ≈ 111000米
  // 向北移动1.5公里 ≈ 1.5 / 111 ≈ 0.0135度
  const distanceKm = 1.5 // 模拟距离1.5公里
  const latDelta = distanceKm / 111.0
  
  return {
    latitude: startLat + latDelta,
    longitude: startLng // 经度不变
  }
}

// 结束打卡
const handleEndCheckin = async () => {
  try {
    isLocationLoading.value = true
    
    let endPosition
    
    if (testMode.value && startPosition.value) {
      // 测试模式：使用模拟的结束位置（基于起始位置计算）
      endPosition = calculateMockEndPosition(
        startPosition.value.latitude,
        startPosition.value.longitude
      )
      console.log('测试模式：使用模拟结束位置', endPosition)
    } else {
      // 正常模式：获取当前位置
      endPosition = await getCurrentPosition()
    }
    
    // 调用后端API记录结束位置并计算距离
    const response = await endCheckinLocation(
      locationId.value, 
      endPosition.latitude, 
      endPosition.longitude
    )
    
    if (response.code === 200) {
      const { distance, status } = response.data
      
      if (distance < 1000) {
        // 距离小于1公里，增加可疑次数并提示
        ElMessage.warning('距离太近，请不要作弊，真正出行')
        // 重置状态
        locationStatus.value = 'idle'
        locationId.value = null
        startPosition.value = null
        // 消耗一次打卡次数（后端已处理）
      } else {
        // 距离满足要求，允许上传
        locationStatus.value = 'completed'
        const distanceText = testMode.value ? '模拟距离' : '距离'
        ElMessage.success(`已记录行程，${distanceText} ${(distance / 1000).toFixed(2)} 公里，可以上传图片了`)
      }
    } else {
      ElMessage.error(response.message || '结束打卡失败')
      locationStatus.value = 'idle'
      locationId.value = null
      startPosition.value = null
    }
  } catch (error) {
    console.error('结束打卡失败:', error)
    ElMessage.error(error.message || '获取位置失败，请检查定位权限')
    locationStatus.value = 'idle'
    locationId.value = null
    startPosition.value = null
  } finally {
    isLocationLoading.value = false
  }
}

// 提交打卡
const submitCheckin = async () => {
  if (!uploadedFile.value) return
  
  isVerifying.value = true
  verifyProgress.value = 0
  verifyDetail.value = '正在上传图片...'
  
  let aiVerifyResult = null
  let aiError = null
  
  // 第一步：调用AI服务验证
  try {
    const response = await verifyImage(
      uploadedFile.value,
      'walk',
      (progress) => {
        verifyProgress.value = Math.min(progress * 0.9, 90)
        if (progress < 50) {
          verifyDetail.value = '正在上传图片...'
        } else {
          verifyDetail.value = '正在进行 OCR 文字提取...'
        }
      }
    )
    
    verifyProgress.value = 90
    
    const steps = response.data?.steps || []
    if (steps.length > 0) {
      const lastStep = steps[steps.length - 1]
      if (lastStep.step === 'Hash Check') {
        verifyDetail.value = '正在进行指纹验证...'
      } else if (lastStep.step === 'OCR Check') {
        verifyDetail.value = '正在进行 OCR 文字提取...'
      } else if (lastStep.step === 'VLLM Check') {
        verifyDetail.value = 'AI 视觉模型正在分析...'
      }
    }
    
    await new Promise(resolve => setTimeout(resolve, 500))
    verifyProgress.value = 95
    
    aiVerifyResult = response.data
    
  } catch (error) {
    // AI服务断链或错误
    aiError = error
    console.error('AI验证失败:', error)
    
    // 如果AI服务断链，标记为SUSPICIOUS状态
    if (error.code === 'AI_SERVICE_DOWN' || error.code === 'AI_SERVICE_TIMEOUT' || error.code === 'AI_SERVICE_ERROR') {
      verifyProgress.value = 95
      verifyDetail.value = 'AI服务不可用，转入人工审核...'
      aiVerifyResult = {
        status: 'SUSPICIOUS',
        reason: error.message || 'AI服务断链，已转入人工审核',
        verifySteps: JSON.stringify([{
          step: 'AI Service',
          status: 'ERROR',
          reason: error.message || 'AI服务不可用'
        }])
      }
    } else {
      // 其他错误，直接返回
      isVerifying.value = false
      ElMessage.error(error.message || '验证失败，请稍后重试')
      return
    }
  }
  
  // 第二步：保存打卡记录到后端
  try {
    verifyDetail.value = '正在保存打卡记录...'
    verifyProgress.value = 98
    
    // 将verifySteps转换为JSON字符串（如果已经是字符串则直接使用）
    let verifyStepsJson = null
    if (aiVerifyResult.verifySteps) {
      verifyStepsJson = typeof aiVerifyResult.verifySteps === 'string' 
        ? aiVerifyResult.verifySteps 
        : JSON.stringify(aiVerifyResult.verifySteps)
    } else if (aiVerifyResult.steps) {
      verifyStepsJson = JSON.stringify(aiVerifyResult.steps)
    }
    
    // 调用后端保存打卡记录
    const saveResponse = await saveCheckinRecord(
      uploadedFile.value,
      'walk',
      aiVerifyResult.status,
      aiVerifyResult.reason || null,
      verifyStepsJson,
      null, // imageHash（可选，AI服务已计算）
      aiVerifyResult.reward || aiVerifyResult.rewardPoints || null,
      locationId.value // 关联定位记录ID
    )
    
    // 打卡提交后重置定位状态
    if (saveResponse.code === 200) {
      locationStatus.value = 'idle'
      locationId.value = null
    }
    
    verifyProgress.value = 100
    
    // 从后端返回的数据中获取实际积分（动态计算后的值）
    if (saveResponse.data && saveResponse.data.rewardPoints !== undefined) {
      actualRewardPoints.value = saveResponse.data.rewardPoints
    } else {
      // 如果没有返回，使用默认值
      actualRewardPoints.value = aiVerifyResult.reward || aiVerifyResult.rewardPoints || sceneConfig.value.rewardPoints
    }
    
    // 根据验证结果显示不同的提示
    if (aiVerifyResult.status === 'APPROVED') {
      verifyDetail.value = '验证通过！'
      
      // 刷新gameStore数据（用于更新小红点提示）
      refreshGameStoreData()
      
      // 触发全局刷新事件，通知mall页面刷新数据
      window.dispatchEvent(new Event('refreshMallData'))
      
      setTimeout(() => {
        isVerifying.value = false
        showSuccess.value = true
      }, 300)
    } else if (aiVerifyResult.status === 'REJECTED') {
      isVerifying.value = false
      ElMessage.error(aiVerifyResult.reason || '验证未通过')
    } else if (aiVerifyResult.status === 'SUSPICIOUS') {
      isVerifying.value = false
      ElMessage.warning(aiVerifyResult.reason || '图片需要人工审核，请稍后查看结果')
    } else {
      isVerifying.value = false
      ElMessage.warning('验证状态异常，请稍后重试')
    }
    
  } catch (error) {
    isVerifying.value = false
    console.error('保存打卡记录失败:', error)
    ElMessage.error('保存打卡记录失败，请稍后重试')
  }
}

// 刷新gameStore数据（用于更新小红点提示）
const refreshGameStoreData = async () => {
  try {
    const [assetsRes, statsRes, titlesRes, badgesRes] = await Promise.all([
      getUserAssets().catch(() => ({ code: 0 })),
      getUserStats().catch(() => ({ code: 0 })),
      getAllTitles().catch(() => ({ code: 0 })),
      getAllBadges().catch(() => ({ code: 0 }))
    ])
    
    // 如果所有请求都成功，更新 gameStore
    if (assetsRes.code === 200 && statsRes.code === 200 && titlesRes.code === 200 && badgesRes.code === 200) {
      // 更新积分
      gameStore.userPoints = assetsRes.data.points || 0
      
      // 更新统计数据
      gameStore.userStats.walkCheckins = statsRes.data.walkCheckins || 0
      gameStore.userStats.plateCheckins = statsRes.data.plateCheckins || 0
      gameStore.userStats.rideCheckins = statsRes.data.rideCheckins || 0
      gameStore.userStats.transitCheckins = statsRes.data.transitCheckins || 0
      gameStore.userStats.totalCheckins = statsRes.data.totalCheckins || 0
      
      // 更新称号数据
      gameStore.titles.length = 0
      titlesRes.data.forEach(title => {
        gameStore.titles.push({
          id: title.id,
          name: title.name,
          icon: title.icon,
          baseCost: title.baseCost,
          level: title.level,
          isOwned: title.isOwned,
          isEquipped: title.isEquipped
        })
      })
      
      // 更新勋章数据（包含currentProgress用于计算可解锁状态）
      gameStore.badges.length = 0
      badgesRes.data.forEach(badge => {
        gameStore.badges.push({
          id: badge.id,
          name: badge.name,
          icon: badge.icon,
          type: badge.type,
          target: badge.target,
          statKey: badge.statKey,
          desc: badge.description,
          isOwned: badge.isOwned,
          isEquipped: badge.isEquipped,
          currentProgress: badge.currentProgress || 0
        })
      })
    }
  } catch (error) {
    // 静默失败，不影响打卡流程
    console.debug('刷新gameStore数据失败（不影响打卡流程）:', error)
  }
}

// 关闭成功弹窗
const handleSuccessClose = async () => {
  showSuccess.value = false
  previewUrl.value = ''
  uploadedFile.value = null
  verifyProgress.value = 0
  verifyDetail.value = '正在上传图片...'
  actualRewardPoints.value = null // 重置实际积分
  locationStatus.value = 'idle' // 重置定位状态
  locationId.value = null
  startPosition.value = null // 重置起始位置
  
  // 刷新gameStore数据，更新小红点提示
  await refreshGameStoreData()
}
</script>

<style src="./styles.css"></style>

<style scoped>
/* Element Plus 深度选择器样式 */
:deep(.el-upload-dragger) {
  border: 2px dashed #d9d9d9;
  border-radius: 16px;
  padding: 60px 40px;
  transition: all 0.3s;
  background: #fafafa;
}

:deep(.el-upload-dragger:hover) {
  border-color: #26a69a;
  background: #f0f9f8;
}

:deep(.el-upload-dragger:hover) .upload-icon {
  color: #26a69a;
}

:deep(.el-upload-dragger.is-disabled) {
  opacity: 0.6;
  cursor: not-allowed;
}

:deep(.el-upload-dragger.is-disabled:hover) {
  border-color: #d9d9d9;
  background: #fafafa;
}

.upload-content.disabled {
  opacity: 0.6;
}

.hint-text {
  color: #909399;
  font-size: 12px;
  margin-top: 8px;
}

.test-mode-section {
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.test-mode-hint {
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.location-control-section {
  margin-bottom: 20px;
  text-align: center;
}

.location-btn {
  min-width: 200px;
  height: 48px;
  font-size: 16px;
}

.success-dialog :deep(.el-dialog__body) {
  padding: 40px 20px;
}
</style>

