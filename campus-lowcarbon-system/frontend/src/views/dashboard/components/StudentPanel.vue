<template>
  <div class="student-panel">
    <!-- A. Hero Section 轮播图 -->
    <div class="hero-section">
      <el-carousel height="300px" :interval="5000" arrow="hover" indicator-position="outside">
        <el-carousel-item v-for="slide in heroSlides" :key="slide.id">
          <div class="hero-slide" :style="{ background: slide.background }">
            <div class="hero-content">
              <h1 class="hero-title">{{ slide.title }}</h1>
              <p class="hero-subtitle">{{ slide.subtitle }}</p>
              <el-button v-if="slide.showBtn" type="primary" size="large" round class="hero-btn">
                立即开始
                <el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </div>
            <div class="hero-decoration">
              <span class="deco-icon">{{ slide.icon }}</span>
            </div>
          </div>
        </el-carousel-item>
      </el-carousel>
    </div>

    <div class="ai-section">
      <el-card class="ai-card" shadow="hover">
        <div class="ai-card-inner">
          <div class="ai-orbit">
            <div class="ai-core">AI</div>
            <span class="orbit-dot dot-1">图</span>
            <span class="orbit-dot dot-2">审</span>
            <span class="orbit-dot dot-3">分</span>
          </div>
          <div class="ai-content">
            <el-tag type="success" effect="dark" round>AI 赋能低碳打卡</el-tag>
            <h2>从“上传凭证”到“可信积分”的智能闭环</h2>
            <p>{{ aiEmpowermentText }}</p>
            <div class="ai-feature-grid">
              <div class="ai-feature" v-for="feature in aiFeatures" :key="feature.title">
                <span class="feature-icon">{{ feature.icon }}</span>
                <div>
                  <strong>{{ feature.title }}</strong>
                  <span>{{ feature.desc }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="guide-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <el-icon :size="24" color="#26a69a"><Guide /></el-icon>
            <span class="header-title">如何开始您的低碳之旅？</span>
          </div>
        </template>
        <div class="guide-flow">
          <div class="flow-item" v-for="(step, index) in guideSteps" :key="step.title">
            <div class="flow-icon" :style="{ background: step.gradient }">
              <component :is="step.icon" />
            </div>
            <div class="flow-copy">
              <span class="flow-index">0{{ index + 1 }}</span>
              <strong>{{ step.title }}</strong>
              <p>{{ step.desc }}</p>
            </div>
          </div>
        </div>
        <div class="guide-bottom">
          <span>平均 10 秒完成智能核验</span>
          <span>支持四类校园低碳场景</span>
        </div>
      </el-card>
    </div>

    <div class="scene-showcase">
      <div class="scene-card" v-for="scene in sceneShowcase" :key="scene.sceneType" @click="handleEntry(scene)">
        <img :src="scene.image" :alt="scene.label" class="scene-image" />
        <div class="scene-mask"></div>
        <div class="scene-info">
          <span class="scene-icon">{{ scene.icon }}</span>
          <h3>{{ scene.label }}</h3>
          <p>{{ scene.desc }}</p>
        </div>
      </div>
    </div>

    <!-- C. Low-Carbon Knowledge 低碳科普 + 今日记录 -->
    <div class="knowledge-section">
      <!-- 左卡片：低碳贴士 -->
      <el-card class="tips-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <el-icon :size="24" color="#ff9800"><Sunrise /></el-icon>
            <span class="header-title">今日低碳贴士</span>
          </div>
        </template>
        <div class="tips-content">
          <div class="tips-main">
            <div class="tips-icon">🤖</div>
            <div class="tips-text">
              <p class="tips-highlight">AI 今日建议</p>
              <p class="tips-detail" v-if="tipsData.dailyTip && tipsData.aiAvailable">
                {{ tipsData.dailyTip }}
              </p>
              <p class="tips-detail tips-error" v-else-if="tipsData.dailyTip && !tipsData.aiAvailable">
                {{ tipsData.dailyTip }}
              </p>
              <p class="tips-detail tips-loading" v-else>
                正在加载AI贴士...
              </p>
            </div>
          </div>
          <div class="tips-footer">
            <div class="tips-stats">
              <div class="stat-item">
                <span class="stat-value">{{ tipsData.savedElectricity.toFixed(1) }}</span>
                <span class="stat-label">累计节电(度)</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <span class="stat-value">{{ tipsData.carbonReduction.toFixed(1) }}</span>
                <span class="stat-label">减碳量(kg)</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <span class="stat-value">{{ tipsData.points }}</span>
                <span class="stat-label">我的积分</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 右卡片：今日记录 -->
      <el-card class="record-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <el-icon :size="24" color="#26a69a"><Calendar /></el-icon>
            <span class="header-title">今日记录</span>
            <el-tag type="success" size="small" effect="plain">{{ todayRecords.length }} 条</el-tag>
          </div>
        </template>
        <div class="record-list" v-if="todayRecords.length > 0">
          <div class="record-item" v-for="record in todayRecords" :key="record.id">
            <span class="record-icon">{{ record.icon }}</span>
            <div class="record-info">
              <span class="record-name">{{ record.name }}</span>
              <span class="record-time">{{ record.time }}</span>
            </div>
            <div class="record-status">
              <el-tag :type="record.status === 'success' ? 'success' : 'warning'" size="small">
                {{ record.status === 'success' ? '已通过' : '审核中' }}
              </el-tag>
              <span class="record-points" :class="record.status">+{{ record.points }}</span>
            </div>
          </div>
        </div>
        <el-empty v-else description="今日暂无打卡记录" :image-size="80">
          <template #image>
            <div class="empty-icon">📋</div>
          </template>
        </el-empty>
      </el-card>
    </div>

  </div>
</template>

<script setup>
import { reactive, onMounted, ref, markRaw } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  ArrowRight,
  Guide,
  Pointer,
  Camera,
  Trophy,
  Sunrise,
  Calendar
} from '@element-plus/icons-vue'
import { getDashboardData, getDailyTip } from '@/api/dashboard'
import { useRouter } from 'vue-router'

const router = useRouter()
const loading = ref(false)

// 轮播图数据
const heroSlides = reactive([
  {
    id: 1,
    title: '智能低碳，AI 守护地球',
    subtitle: '基于计算机视觉的自动核验系统',
    background: 'linear-gradient(135deg, #e0f7fa 0%, #80deea 50%, #26a69a 100%)',
    icon: '🌍',
    showBtn: true
  },
  {
    id: 2,
    title: '四大场景，全面覆盖',
    subtitle: '健步走 · 骑行 · 光盘 · 公交',
    background: 'linear-gradient(135deg, #c8e6c9 0%, #81c784 50%, #4caf50 100%)',
    icon: '🎯',
    showBtn: false
  },
  {
    id: 3,
    title: '积分兑换，好礼相送',
    subtitle: '让每一次环保行为都有价值',
    background: 'linear-gradient(135deg, #fff3e0 0%, #ffcc80 50%, #ff9800 100%)',
    icon: '🎁',
    showBtn: false
  }
])

// 今日打卡记录
const todayRecords = reactive([])

// 低碳贴士数据
const tipsData = reactive({
  savedElectricity: 0,
  carbonReduction: 0,
  points: 0,
  dailyTip: '', // AI生成的每日贴士，初始为空
  aiAvailable: true // AI服务是否可用
})

const aiEmpowermentText = '系统通过图像识别、重复图片检测、行为数值提取和异常置信度评估，把低碳行为从人工填报升级为可核验、可追踪、可量化的数据资产。'

const aiFeatures = reactive([
  { icon: '🖼️', title: '图像识别', desc: '识别光盘、骑行、公交等凭证内容' },
  { icon: '🧬', title: '哈希去重', desc: '拦截重复上传和历史图片复用' },
  { icon: '📍', title: '位置校验', desc: '结合轨迹距离提升出行可信度' },
  { icon: '📊', title: '智能评分', desc: '根据场景规则自动计算积分' }
])

const sceneShowcase = reactive([
  { id: 1, icon: '🏃', label: '低碳健步走', sceneType: 'walk', desc: '上传运动截图，AI 提取步数并结合定位距离校验', image: '/api/uploads/checkin/walk/低碳健步走.png' },
  { id: 2, icon: '🚲', label: '绿色骑行', sceneType: 'ride', desc: '记录骑行里程，鼓励短途通勤少开车', image: '/api/uploads/checkin/ride/骑行打卡图片.png' },
  { id: 3, icon: '🍽️', label: '光盘行动', sceneType: 'plate', desc: '识别餐盘凭证，倡导减少食物浪费', image: '/api/uploads/checkin/plate/光盘行动.png' },
  { id: 4, icon: '🚌', label: '公共交通', sceneType: 'transit', desc: '上传公交地铁凭证，量化绿色出行贡献', image: '/api/uploads/checkin/transit/公共交通.png' }
])

const guideSteps = reactive([
  { title: '选择场景', desc: '从四张场景图进入对应打卡，系统加载规则与次数限制', icon: markRaw(Pointer), gradient: 'linear-gradient(135deg, #26a69a, #00897b)' },
  { title: '上传凭证', desc: '提交图片或截图，AI 自动识别内容并检测重复图片', icon: markRaw(Camera), gradient: 'linear-gradient(135deg, #42a5f5, #1976d2)' },
  { title: '积分到账', desc: '通过核验后自动计算积分，更新个人统计与排行榜数据', icon: markRaw(Trophy), gradient: 'linear-gradient(135deg, #ffb74d, #fb8c00)' }
])

// 加载首页数据
const loadDashboardData = async () => {
  loading.value = true
  try {
    // 并行加载首页数据和AI贴士
    const [dashboardRes, tipRes] = await Promise.all([
      getDashboardData(),
      getDailyTip()
    ])
    
    // 处理首页数据
    if (dashboardRes.code === 200) {
      const data = dashboardRes.data
      
      // 更新今日打卡记录
      todayRecords.length = 0
      if (data.todayRecords && data.todayRecords.length > 0) {
        todayRecords.push(...data.todayRecords)
      }
      
      // 更新低碳贴士统计数据
      if (data.tipsData) {
        tipsData.savedElectricity = data.tipsData.savedElectricity || 0
        tipsData.carbonReduction = data.tipsData.carbonReduction || 0
        tipsData.points = data.tipsData.points || 0
      }
    }
    
    // 处理AI贴士数据
    if (tipRes.data) {
      if (tipRes.data.code === 200 && tipRes.data.data) {
        tipsData.dailyTip = tipRes.data.data.tip || ''
        tipsData.aiAvailable = tipRes.data.data.source !== 'error'
      } else {
        // AI服务返回错误
        tipsData.dailyTip = tipRes.data.data?.tip || '人工智能断线中，等待管理员维护……'
        tipsData.aiAvailable = false
      }
    } else {
      // 请求失败
      tipsData.dailyTip = '人工智能断线中，等待管理员维护……'
      tipsData.aiAvailable = false
    }
  } catch (error) {
    console.error('加载首页数据失败:', error)
    // 如果出错，设置默认错误提示
    if (!tipsData.dailyTip) {
      tipsData.dailyTip = '人工智能断线中，等待管理员维护……'
      tipsData.aiAvailable = false
    }
  } finally {
    loading.value = false
  }
}

// 快捷入口点击
const handleEntry = (entry) => {
  // 根据场景类型跳转到对应的打卡页面
  const routeMap = {
    'walk': '/checkin/walk',
    'ride': '/checkin/ride',
    'plate': '/checkin/plate',
    'transit': '/checkin/transit'
  }
  
  const route = routeMap[entry.sceneType]
  if (route) {
    router.push(route)
  } else {
    ElMessage({
      message: `即将进入「${entry.label}」打卡页面`,
      type: 'info',
      duration: 2000
    })
  }
}

// 组件挂载时加载数据
onMounted(() => {
  loadDashboardData()
})
</script>

<style scoped>
.student-panel {
  padding: 24px;
  background: linear-gradient(180deg, #f0f9f8 0%, #f5f7fa 100%);
  min-height: calc(100vh - 60px);
}

/* Hero Section 轮播图 */
.hero-section {
  margin-bottom: 24px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(38, 166, 154, 0.15);
}

.hero-slide {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 60px;
  position: relative;
  overflow: hidden;
}

.hero-content {
  z-index: 2;
  max-width: 60%;
}

.hero-title {
  font-size: 42px;
  font-weight: 700;
  color: #1a3a34;
  margin: 0 0 16px;
  letter-spacing: 2px;
  text-shadow: 0 2px 4px rgba(255, 255, 255, 0.5);
}

.hero-subtitle {
  font-size: 18px;
  color: #37474f;
  margin: 0 0 28px;
  letter-spacing: 1px;
  opacity: 0.9;
}

.hero-btn {
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  border: none;
  padding: 14px 32px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 1px;
  box-shadow: 0 4px 16px rgba(38, 166, 154, 0.4);
}

.hero-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(38, 166, 154, 0.5);
}

.hero-decoration {
  position: absolute;
  right: 80px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 1;
}

.deco-icon {
  font-size: 120px;
  opacity: 0.6;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.1));
}

/* 轮播指示器样式 */
:deep(.el-carousel__indicators--outside) {
  margin-top: 12px;
}

:deep(.el-carousel__indicator--horizontal .el-carousel__button) {
  width: 24px;
  height: 4px;
  border-radius: 2px;
  background: #c0c4cc;
}

:deep(.el-carousel__indicator--horizontal.is-active .el-carousel__button) {
  background: #26a69a;
}

.ai-section {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.65fr);
  gap: 24px;
  margin-bottom: 24px;
}

.ai-card,
.guide-card {
  border-radius: 16px;
  border: none;
}

.ai-card :deep(.el-card__body) {
  padding: 0;
}

.ai-card-inner {
  min-height: 100%;
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 24px;
  align-items: center;
  padding: 24px 28px;
  background: radial-gradient(circle at 18% 30%, rgba(38, 166, 154, 0.24), transparent 28%), linear-gradient(135deg, #ffffff 0%, #effdf9 52%, #e6f7ff 100%);
}

.ai-orbit {
  width: 170px;
  height: 170px;
  position: relative;
  border-radius: 50%;
  border: 1px dashed rgba(38, 166, 154, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.62);
  box-shadow: inset 0 0 32px rgba(38, 166, 154, 0.14);
}

.ai-core {
  width: 88px;
  height: 88px;
  border-radius: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 30px;
  font-weight: 800;
  letter-spacing: 2px;
  background: linear-gradient(135deg, #00bfa5, #1976d2);
  box-shadow: 0 18px 40px rgba(25, 118, 210, 0.24);
}

.orbit-dot {
  position: absolute;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-weight: 700;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.14);
}

.dot-1 {
  top: 14px;
  right: 22px;
  background: #26a69a;
}

.dot-2 {
  left: 6px;
  bottom: 44px;
  background: #ff9800;
}

.dot-3 {
  right: 16px;
  bottom: 14px;
  background: #7e57c2;
}

.ai-content h2 {
  margin: 12px 0 8px;
  font-size: 24px;
  color: #1a3a34;
  letter-spacing: 1px;
}

.ai-content p {
  margin: 0 0 14px;
  color: #52616b;
  font-size: 15px;
  line-height: 1.8;
}

.ai-feature-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.ai-feature {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  padding: 10px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(38, 166, 154, 0.12);
}

.feature-icon {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e0f7fa;
  font-size: 20px;
}

.ai-feature strong,
.ai-feature span:last-child {
  display: block;
}

.ai-feature strong {
  color: #263238;
  font-size: 13px;
  margin-bottom: 4px;
}

.ai-feature span:last-child {
  color: #78909c;
  font-size: 11px;
}

/* Guide Card 操作指引 */
.guide-card {
  margin-bottom: 24px;
}

.guide-card :deep(.el-card__body) {
  padding: 24px 28px 26px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  letter-spacing: 1px;
}

.guide-flow {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.flow-item {
  position: relative;
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 16px;
  border-radius: 16px;
  background: linear-gradient(135deg, #f8fffd 0%, #f4f7fb 100%);
  border: 1px solid #edf2f7;
  transition: all 0.25s ease;
}

.flow-item:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 37px;
  bottom: -15px;
  width: 2px;
  height: 14px;
  background: linear-gradient(180deg, #26a69a, rgba(38, 166, 154, 0.08));
}

.flow-item:hover {
  transform: translateX(4px);
  border-color: rgba(38, 166, 154, 0.26);
  box-shadow: 0 10px 22px rgba(38, 166, 154, 0.1);
}

.flow-icon {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 20px;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.12);
}

.flow-copy {
  flex: 1;
  min-width: 0;
}

.flow-index {
  display: inline-block;
  margin-bottom: 4px;
  color: #26a69a;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 1px;
}

.flow-copy strong {
  display: block;
  color: #263238;
  font-size: 16px;
  margin-bottom: 5px;
}

.flow-copy p {
  margin: 0;
  color: #78909c;
  font-size: 13px;
  line-height: 1.6;
}

.guide-bottom {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed #dce8e6;
}

.guide-bottom span {
  padding: 7px 10px;
  border-radius: 999px;
  color: #00897b;
  font-size: 12px;
  background: rgba(38, 166, 154, 0.1);
}

.scene-showcase {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 24px;
}

.scene-card {
  height: 178px;
  position: relative;
  border-radius: 18px;
  overflow: hidden;
  cursor: pointer;
  box-shadow: 0 10px 26px rgba(38, 166, 154, 0.14);
  transition: all 0.28s ease;
}

.scene-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 16px 34px rgba(38, 166, 154, 0.22);
}

.scene-card:hover .scene-image {
  transform: scale(1.08);
}

.scene-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.35s ease;
}

.scene-mask {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.68));
}

.scene-info {
  position: absolute;
  left: 18px;
  right: 18px;
  bottom: 16px;
  color: #ffffff;
}

.scene-icon {
  width: 38px;
  height: 38px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.22);
  backdrop-filter: blur(6px);
  font-size: 20px;
  margin-bottom: 8px;
}

.scene-info h3 {
  margin: 0 0 6px;
  font-size: 18px;
  letter-spacing: 1px;
}

.scene-info p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  opacity: 0.88;
}

/* Knowledge Section 知识科普 */
.knowledge-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-bottom: 24px;
}

.tips-card,
.record-card {
  border-radius: 16px;
  border: none;
}

.tips-content {
  padding: 8px 0;
}

.tips-main {
  display: flex;
  gap: 20px;
  margin-bottom: 24px;
}

.tips-icon {
  font-size: 48px;
  flex-shrink: 0;
}

.tips-text {
  flex: 1;
}

.tips-highlight {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 12px;
}

.tips-detail {
  font-size: 15px;
  color: #606266;
  line-height: 1.8;
  margin: 0 0 8px;
}

.tips-detail strong {
  color: #26a69a;
  font-weight: 600;
}

.tips-detail.tips-error {
  color: #f56c6c;
  font-weight: 500;
  background: rgba(245, 108, 108, 0.1);
  padding: 12px;
  border-radius: 8px;
  border-left: 3px solid #f56c6c;
}

.tips-detail.tips-loading {
  color: #909399;
  font-style: italic;
}

.tips-footer {
  border-top: 1px solid #f0f0f0;
  padding-top: 20px;
}

.tips-stats {
  display: flex;
  justify-content: space-around;
  align-items: center;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #26a69a;
}

.stat-label {
  font-size: 12px;
  color: #909399;
}

.stat-divider {
  width: 1px;
  height: 40px;
  background: #e0e0e0;
}

/* Record Card 今日记录 */
.record-card .card-header {
  justify-content: flex-start;
}

.record-card .card-header .el-tag {
  margin-left: auto;
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

/* 自定义滚动条样式 */
.record-list::-webkit-scrollbar {
  width: 6px;
}

.record-list::-webkit-scrollbar-track {
  background: #f5f5f5;
  border-radius: 3px;
}

.record-list::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 3px;
  transition: background 0.2s;
}

.record-list::-webkit-scrollbar-thumb:hover {
  background: #909399;
}

.record-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 12px;
  transition: all 0.2s;
}

.record-item:hover {
  background: #f0f9f8;
  transform: translateX(4px);
}

.record-icon {
  font-size: 32px;
}

.record-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.record-name {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
}

.record-time {
  font-size: 12px;
  color: #909399;
}

.record-status {
  display: flex;
  align-items: center;
  gap: 12px;
}

.record-points {
  font-size: 18px;
  font-weight: 700;
}

.record-points.success {
  color: #26a69a;
}

.record-points.pending {
  color: #e6a23c;
}

.empty-icon {
  font-size: 64px;
  opacity: 0.5;
}

/* 响应式 */
@media (max-width: 1200px) {
  .ai-section {
    grid-template-columns: 1fr;
  }

  .ai-feature-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scene-showcase {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .hero-title {
    font-size: 32px;
  }
  
  .deco-icon {
    font-size: 80px;
  }
}

@media (max-width: 992px) {
  .ai-card-inner {
    grid-template-columns: 1fr;
  }

  .ai-orbit {
    margin: 0 auto;
  }

  .knowledge-section {
    grid-template-columns: 1fr;
  }
  
}

@media (max-width: 768px) {
  .scene-showcase,
  .ai-feature-grid {
    grid-template-columns: 1fr;
  }

  .hero-slide {
    padding: 0 24px;
    flex-direction: column;
    text-align: center;
  }
  
  .hero-content {
    max-width: 100%;
  }
  
  .hero-title {
    font-size: 24px;
  }
  
  .hero-subtitle {
    font-size: 14px;
  }
  
  .hero-decoration {
    position: static;
    transform: none;
    margin-top: 20px;
  }
  
  .deco-icon {
    font-size: 60px;
  }
}
</style>
