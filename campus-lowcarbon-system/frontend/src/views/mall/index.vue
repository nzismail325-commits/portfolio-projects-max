<template>
  <div class="mall-page">
    <!-- 顶部资产卡片 -->
    <div class="assets-card">
      <div class="assets-bg">
        <div class="bg-circle circle-1"></div>
        <div class="bg-circle circle-2"></div>
        <div class="bg-circle circle-3"></div>
      </div>
      <div class="assets-content">
        <div class="assets-left">
          <span class="assets-label">我的碳积分</span>
          <div class="assets-value">
            <span class="value-number">{{ userAssets.points.toLocaleString() }}</span>
            <span class="value-unit">积分</span>
          </div>
          <span class="assets-tip">升级称号 · 解锁成就 · 彰显荣耀</span>
        </div>
        <div class="assets-right">
          <div class="stats-overview">
            <div class="stat-block">
              <div class="stat-icon-bg">🏅</div>
              <div class="stat-data">
                <span class="stat-value">{{ userAssets.unlockedTitlesCount }}</span>
                <span class="stat-label">个荣誉称号</span>
              </div>
            </div>
            <div class="stat-block">
              <div class="stat-icon-bg">👑</div>
              <div class="stat-data">
                <span class="stat-value">{{ maxTitleLevelDisplay }}</span>
                <span class="stat-label">当前最高等级</span>
              </div>
            </div>
            <div class="stat-block">
              <div class="stat-icon-bg">🎖️</div>
              <div class="stat-data">
                <span class="stat-value">{{ userAssets.ownedBadgesCount }}</span>
                <span class="stat-label">枚环保勋章</span>
              </div>
            </div>
            <div class="stat-block">
              <div class="stat-icon-bg">✅</div>
              <div class="stat-data">
                <span class="stat-value">{{ userAssets.totalCheckins }}</span>
                <span class="stat-label">次低碳行动</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="assets-decoration">
        <span class="deco-icon">🏆</span>
      </div>
    </div>

    <!-- 商城内容 -->
    <div class="mall-content">
      <!-- 动态区域标题 -->
      <div class="section-header">
        <h3>{{ currentSection.title }}</h3>
        <p>{{ currentSection.desc }}</p>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-container">
        <el-skeleton :rows="10" animated />
      </div>
      
      <!-- 荣誉称号列表 -->
      <div class="product-grid" v-if="isTitlesSection && !loading">
        <div 
          v-for="item in titles" 
          :key="item.id" 
          class="title-card"
          :class="[getLevelClass(item.level), { 'is-equipped': item.isEquipped }]"
        >
          <div class="level-aura" v-if="item.level >= 3"></div>
          
          <!-- 佩戴中角标 -->
          <div class="equipped-ribbon" v-if="item.isEquipped">
            <span>佩戴中</span>
          </div>
          
          <div class="title-header">
            <span class="title-icon">{{ item.icon }}</span>
            <div class="title-info">
              <h4 class="title-name">{{ item.name }}</h4>
              <el-tag 
                :type="getLevelTagType(item.level)" 
                :effect="item.level >= 4 ? 'dark' : 'light'"
                size="small"
                class="level-tag"
              >
                {{ getLevelText(item.level) }}
              </el-tag>
            </div>
          </div>

          <div class="level-progress">
            <div class="progress-bar">
              <div 
                class="progress-fill" 
                :style="{ width: (item.level / 5) * 100 + '%' }"
                :class="getLevelClass(item.level)"
              ></div>
            </div>
            <div class="progress-dots">
              <span 
                v-for="lv in 5" 
                :key="lv" 
                class="dot"
                :class="{ active: item.level >= lv }"
              ></span>
            </div>
          </div>

          <div class="upgrade-info" v-if="item.level < 5">
            <span class="next-level">下一级: {{ getLevelName(item.level + 1) }}</span>
            <span class="upgrade-cost">
              <el-icon><Coin /></el-icon>
              {{ getTitleUpgradeCost(item) }}
            </span>
          </div>
          <div class="upgrade-info max-level" v-else>
            <span class="legend-text">🌟 传说级称号 🌟</span>
          </div>

          <!-- 底部操作区（双按钮策略） -->
          <div class="title-footer">
            <!-- 左侧状态文字 -->
            <span class="status-text" :class="getTitleStatusTextClass(item)">
              {{ getTitleStatusText(item) }}
            </span>

            <!-- 右侧操作按钮组 -->
            <div class="action-area">
              <!-- ========== Scenario A: 未解锁 (Level === 0) ========== -->
              <template v-if="item.level === 0">
                <!-- 积分不足 -->
                <el-button
                  v-if="userAssets.points < getTitleUpgradeCost(item)"
                  type="info"
                  size="small"
                  disabled
                  round
                  class="title-btn"
                >
                  积分不足
                </el-button>
                <!-- 可解锁 -->
                <el-button
                  v-else
                  type="primary"
                  size="small"
                  round
                  class="title-btn unlock-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleUpgradeTitle(item)"
                >
                  🔓 解锁
                </el-button>
              </template>

              <!-- ========== Scenario B: 已拥有但未满级 (0 < Level < 5) ========== -->
              <template v-else-if="item.level < 5">
                <!-- Button 1: 佩戴/卸下 (始终显示) -->
                <el-button
                  v-if="item.isEquipped"
                  type="danger"
                  size="small"
                  plain
                  round
                  class="title-btn wear-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleToggleEquipTitle(item)"
                >
                  ⬇️ 卸下
                </el-button>
                <el-button
                  v-else
                  type="success"
                  size="small"
                  plain
                  round
                  class="title-btn wear-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleToggleEquipTitle(item)"
                >
                  👕 佩戴
                </el-button>

                <!-- Button 2: 升级 -->
                <el-button
                  v-if="userAssets.points < getTitleUpgradeCost(item)"
                  type="warning"
                  size="small"
                  plain
                  disabled
                  round
                  class="title-btn"
                >
                  ⬆️ 升级
                </el-button>
                <el-button
                  v-else
                  type="warning"
                  size="small"
                  round
                  class="title-btn upgrade-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleUpgradeTitle(item)"
                >
                  ⬆️ 升级
                </el-button>
              </template>

              <!-- ========== Scenario C: 已满级 (Level === 5) ========== -->
              <template v-else>
                <!-- 佩戴/卸下 大按钮 -->
                <el-button
                  v-if="item.isEquipped"
                  type="danger"
                  size="small"
                  plain
                  round
                  class="title-btn unequip-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleToggleEquipTitle(item)"
                >
                  ⬇️ 卸下
                </el-button>
                <el-button
                  v-else
                  type="success"
                  size="small"
                  round
                  class="title-btn equip-btn"
                  :loading="loadingTitles[item.id]"
                  @click="handleToggleEquipTitle(item)"
                >
                  👕 佩戴
                </el-button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 环保勋章列表 -->
      <div v-if="isBadgesSection && !loading">
        <div class="badge-category" v-for="category in badgeCategories" :key="category.key">
          <div class="category-header">
            <span class="category-icon">{{ category.icon }}</span>
            <span class="category-name">{{ category.name }}</span>
            <span class="category-count">
              {{ getCategoryOwnedCount(category.key) }} / {{ getCategoryTotalCount(category.key) }} 已拥有
            </span>
            <span class="category-equipped" v-if="getEquippedBadgeByType(category.key)">
              <el-tag type="success" size="small" effect="dark">
                正在佩戴: {{ getEquippedBadgeByType(category.key).name }}
              </el-tag>
            </span>
          </div>
          
          <div class="badge-grid">
            <div 
              v-for="badge in getBadgesByType(category.key)" 
              :key="badge.id" 
              class="badge-card"
              :class="getBadgeCardClass(badge)"
            >
              <!-- 佩戴中角标 -->
              <div class="equipped-ribbon" v-if="badge.isEquipped">
                <span>佩戴中</span>
              </div>

              <div class="badge-icon-wrapper">
                <span class="badge-icon" :class="{ grayscale: !canUnlockBadge(badge) && !badge.isOwned }">
                  {{ badge.icon }}
                </span>
                <div class="owned-stamp" v-if="badge.isOwned">
                  <el-icon><Select /></el-icon>
                </div>
              </div>
              
              <div class="badge-info">
                <h4 class="badge-name">{{ badge.name }}</h4>
                <p class="badge-desc">{{ badge.description }}</p>
              </div>

              <!-- 进度区域 - 仅未拥有时显示 -->
              <div class="badge-progress" v-if="!badge.isOwned">
                <el-progress 
                  :percentage="getBadgeProgress(badge)"
                  :status="canUnlockBadge(badge) ? 'success' : ''"
                  :stroke-width="8"
                  :show-text="false"
                />
                <div class="progress-text">
                  <span class="current">{{ getCurrentProgress(badge) }}</span>
                  <span class="separator">/</span>
                  <span class="target">{{ badge.target }}</span>
                </div>
              </div>

              <!-- 已拥有时显示获得日期 -->
              <div class="badge-owned-info" v-else>
                <el-tag type="success" effect="light" size="small">
                  <el-icon><Select /></el-icon>
                  <span>已获得</span>
                </el-tag>
              </div>

              <!-- 底部操作区 -->
              <div class="badge-footer">
                <!-- 左侧状态文字 -->
                <span class="status-text" :class="getStatusTextClass(badge)">
                  {{ getStatusText(badge) }}
                </span>

                <!-- 右侧操作按钮 -->
                <div class="action-area">
                  <!-- 状态1: 未解锁 - 进度不足 -->
                  <el-button
                    v-if="!canUnlockBadge(badge) && !badge.isOwned"
                    type="info"
                    size="small"
                    disabled
                    class="badge-btn"
                  >
                    不可用
                  </el-button>

                  <!-- 状态2: 待解锁 - 可解锁 -->
                  <el-button
                    v-else-if="canUnlockBadge(badge) && !badge.isOwned"
                    type="primary"
                    size="small"
                    class="badge-btn unlock-btn"
                    :loading="loadingBadges[badge.id]"
                    @click="handleUnlockBadge(badge)"
                  >
                    <span class="btn-icon">🔓</span>
                    <span>解锁勋章</span>
                  </el-button>

                  <!-- 状态3: 已拥有 - 未佩戴 -->
                  <el-button
                    v-else-if="badge.isOwned && !badge.isEquipped"
                    type="default"
                    size="small"
                    plain
                    class="badge-btn equip-btn"
                    :loading="loadingBadges[badge.id]"
                    @click="handleEquipBadge(badge)"
                  >
                    <span class="btn-icon">👕</span>
                    <span>佩戴</span>
                  </el-button>

                  <!-- 状态4: 已佩戴 -->
                  <el-button
                    v-else
                    type="danger"
                    size="small"
                    plain
                    class="badge-btn unequip-btn"
                    :loading="loadingBadges[badge.id]"
                    @click="handleUnequipBadge(badge)"
                  >
                    <span class="btn-icon">⬇️</span>
                    <span>卸下</span>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Coin, Select, Lock, Top, Trophy } from '@element-plus/icons-vue'
import { 
  getUserAssets, 
  getUserStats, 
  getAllTitles, 
  getAllBadges, 
  upgradeTitle, 
  toggleEquipTitle, 
  unlockBadge, 
  toggleEquipBadge 
} from '@/api/mall'
import { getUserInfo } from '@/api/user'
import { useGameStore } from '@/stores/game'
import { ElMessageBox } from 'element-plus'

const route = useRoute()
const gameStore = useGameStore()

// 监听全局刷新事件（当打卡成功或审核通过时触发）
const handleRefreshEvent = () => {
  fetchMallData()
}

// 组件挂载时监听刷新事件
onMounted(() => {
  window.addEventListener('refreshMallData', handleRefreshEvent)
})

// 组件卸载时移除监听
onUnmounted(() => {
  window.removeEventListener('refreshMallData', handleRefreshEvent)
})

// 加载状态
const loading = ref(false)
const loadingTitles = reactive({})
const loadingBadges = reactive({})

// 数据状态
const userAssets = ref({
  points: 0,
  unlockedTitlesCount: 0,
  maxTitleLevel: 0,
  ownedBadgesCount: 0,
  totalCheckins: 0
})

const userStats = ref({
  walkCheckins: 0,
  plateCheckins: 0,
  rideCheckins: 0,
  transitCheckins: 0,
  totalCheckins: 0
})

const titles = ref([])
const badges = ref([])

// 用户是否设置了支付密码
const hasPaymentPassword = ref(false)

// 等级名称映射
const levelNames = ['未解锁', '初级', '进阶', '精通', '大师', '传说']

// ==================== 路由动态判断 ====================
// 判断当前是称号页还是勋章页
const isTitlesSection = computed(() => route.path.includes('titles'))
const isBadgesSection = computed(() => route.path.includes('badges'))

// 当前区域信息（动态标题）
const currentSection = computed(() => {
  if (isTitlesSection.value) {
    return {
      title: '荣誉称号大厅',
      desc: '消耗积分解锁并升级专属称号，最高可达 Lv.5 传说级'
    }
  }
  return {
    title: '环保勋章兑换处',
    desc: '完成指定任务解锁勋章，同系列勋章只能佩戴一个'
  }
})

// ==================== 称号系统 ====================
const getLevelClass = (level) => {
  const classes = ['level-0', 'level-1', 'level-2', 'level-3', 'level-4', 'level-5']
  return classes[level] || 'level-0'
}

const getLevelTagType = (level) => {
  if (level === 0) return 'info'
  if (level <= 2) return ''
  if (level <= 4) return 'warning'
  return 'danger'
}

const getLevelText = (level) => {
  if (level === 0) return '未解锁'
  return `Lv.${level} ${levelNames[level]}`
}

// 最高称号等级显示文本
const maxTitleLevelDisplay = computed(() => {
  const max = userAssets.value.maxTitleLevel
  if (max === 0) return 'Lv.0'
  return `Lv.${max}`
})

// 获取称号升级费用
const getTitleUpgradeCost = (title) => {
  return title.nextUpgradeCost || 0
}

// 判断勋章是否可解锁
const canUnlockBadge = (badge) => {
  return badge.currentProgress >= badge.target && !badge.isOwned
}

// 获取勋章进度百分比
const getBadgeProgress = (badge) => {
  return badge.progressPercentage || 0
}

// 获取指定类型当前佩戴的勋章
const getEquippedBadgeByType = (type) => {
  return badges.value.find(b => b.type === type && b.isEquipped) || null
}

// 按类型获取勋章列表
const getBadgesByType = (type) => {
  return badges.value.filter(b => b.type === type)
}

// 获取等级名称
const getLevelName = (level) => {
  return levelNames[level] || '未知'
}

// 获取用户统计数据（兼容旧代码）
const getUserStatValue = (statKey) => {
  const keyMap = {
    'walkCheckins': 'walkCheckins',
    'plateCheckins': 'plateCheckins',
    'rideCheckins': 'rideCheckins',
    'transitCheckins': 'transitCheckins',
    'totalCheckins': 'totalCheckins'
  }
  return userStats.value[keyMap[statKey]] || 0
}

// 升级称号
const handleUpgradeTitle = async (item) => {
  const cost = getTitleUpgradeCost(item)
  if (userAssets.value.points < cost) {
    ElMessage.warning('积分不足，无法升级')
    return
  }
  
  // 如果设置了支付密码，需要输入支付密码
  let paymentPassword = null
  if (hasPaymentPassword.value) {
    try {
      const { value } = await ElMessageBox.prompt('请输入支付密码', '安全验证', {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        inputType: 'password',
        inputPlaceholder: '请输入6位数字支付密码',
        inputPattern: /^\d{6}$/,
        inputErrorMessage: '支付密码必须是6位数字',
        showClose: false
      })
      paymentPassword = value
    } catch (error) {
      // 用户取消输入
      return
    }
  }
  
  loadingTitles[item.id] = true
  try {
    const response = await upgradeTitle(item.id, paymentPassword)
    if (response.code === 200) {
      const action = item.level === 0 ? '解锁' : '升级'
      // 更新本地数据
      await fetchMallData()
      ElMessage.success({
        message: `🎉 ${action}成功！获得「${response.data.name}」Lv.${response.data.level}`,
        duration: 3000
      })
    }
  } catch (error) {
    console.error('升级称号失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loadingTitles[item.id] = false
  }
}

// 佩戴称号
const handleEquipTitle = (item) => {
  gameStore.equipTitle(item.id)
  ElMessage.success({
    message: `👑 佩戴成功！「${item.name}」已装备`,
    duration: 2000
  })
}

// 卸下称号
const handleUnequipTitle = (item) => {
  gameStore.unequipTitle(item.id)
  ElMessage.info({
    message: `已卸下「${item.name}」称号`,
    duration: 2000
  })
}

// 切换称号佩戴状态 (Toggle)
const handleToggleEquipTitle = async (item) => {
  const wasEquipped = item.isEquipped
  loadingTitles[item.id] = true
  
  try {
    const response = await toggleEquipTitle(item.id)
    if (response.code === 200) {
      // 更新本地数据
      await fetchMallData()
      
      if (wasEquipped) {
        ElMessage.info({
          message: `已卸下「${item.name}」称号`,
          duration: 2000
        })
      } else {
        ElMessage.success({
          message: `👑 佩戴成功！「${item.name}」已装备`,
          duration: 2000
        })
      }
    }
  } catch (error) {
    console.error('切换称号佩戴状态失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loadingTitles[item.id] = false
  }
}

// 获取称号状态文字
const getTitleStatusText = (item) => {
  // Scenario A: 未解锁
  if (item.level === 0) {
    return `需 ${getTitleUpgradeCost(item)} 积分`
  }
  // Scenario B: 已拥有但未满级
  if (item.level < 5) {
    return `下一级: ${getTitleUpgradeCost(item)} 积分`
  }
  // Scenario C: 已满级
  return '✨ 传说等级'
}

// 获取称号状态文字样式类
const getTitleStatusTextClass = (item) => {
  // Scenario A: 未解锁
  if (item.level === 0) return 'status-locked'
  // Scenario B: 已拥有但未满级
  if (item.level < 5) return 'status-upgradable'
  // Scenario C: 已满级
  return 'status-legend'
}

// ==================== 勋章系统 ====================
const badgeCategories = [
  { key: 'plate', name: '光盘系列', icon: '🍽️' },
  { key: 'walk', name: '健步系列', icon: '🏃' },
  { key: 'ride', name: '骑行系列', icon: '🚲' },
  { key: 'general', name: '综合成就', icon: '🏅' }
]

// 获取当前进度数值
const getCurrentProgress = (badge) => {
  return badge.currentProgress || 0
}

// 获取分类已拥有数量
const getCategoryOwnedCount = (categoryKey) => {
  return badges.value.filter(b => b.type === categoryKey && b.isOwned).length
}

// 获取分类总数量
const getCategoryTotalCount = (categoryKey) => {
  return badges.value.filter(b => b.type === categoryKey).length
}

// 获取勋章卡片样式类
const getBadgeCardClass = (badge) => {
  if (badge.isEquipped) return 'equipped'
  if (badge.isOwned) return 'owned'
  if (canUnlockBadge(badge)) return 'unlockable'
  return 'locked'
}

// 获取状态文字
const getStatusText = (badge) => {
  if (badge.isEquipped) return '已佩戴'
  if (badge.isOwned) return '已拥有'
  if (canUnlockBadge(badge)) return '可解锁'
  return '未达成'
}

// 获取状态文字样式类
const getStatusTextClass = (badge) => {
  if (badge.isEquipped) return 'status-equipped'
  if (badge.isOwned) return 'status-owned'
  if (canUnlockBadge(badge)) return 'status-unlockable'
  return 'status-locked'
}

// 解锁勋章
const handleUnlockBadge = async (badge) => {
  loadingBadges[badge.id] = true
  try {
    const response = await unlockBadge(badge.id)
    if (response.code === 200) {
      // 更新本地数据
      await fetchMallData()
      ElMessage.success({
        message: `🎉 解锁成功！获得「${badge.name}」勋章，快去佩戴吧`,
        duration: 3000
      })
    }
  } catch (error) {
    console.error('解锁勋章失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loadingBadges[badge.id] = false
  }
}

// 佩戴勋章
const handleEquipBadge = async (badge) => {
  loadingBadges[badge.id] = true
  try {
    const response = await toggleEquipBadge(badge.id)
    if (response.code === 200) {
      // 更新本地数据
      await fetchMallData()
      ElMessage.success({
        message: `👕 佩戴成功！「${badge.name}」已装备`,
        duration: 2000
      })
    }
  } catch (error) {
    console.error('佩戴勋章失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loadingBadges[badge.id] = false
  }
}

// 卸下勋章
const handleUnequipBadge = async (badge) => {
  loadingBadges[badge.id] = true
  try {
    const response = await toggleEquipBadge(badge.id)
    if (response.code === 200) {
      // 更新本地数据
      await fetchMallData()
      ElMessage.info({
        message: `已卸下「${badge.name}」勋章`,
        duration: 2000
      })
    }
  } catch (error) {
    console.error('卸下勋章失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loadingBadges[badge.id] = false
  }
}

// 计算可升级称号数量
const calculateCanUpgradeTitlesCount = () => {
  let count = 0
  for (const title of titles.value) {
    // 已满级 (Lv.5) 跳过
    if (title.level >= title.maxLevel) continue
    
    // 计算下一级所需积分
    const nextCost = title.nextUpgradeCost || 0
    
    // 积分足够 → 该称号计为 1
    if (userAssets.value.points >= nextCost && nextCost > 0) {
      count++
    }
  }
  return count
}

// 计算可解锁勋章数量
const calculateCanUnlockBadgesCount = () => {
  return badges.value.filter(badge => {
    // 未拥有 && 达成条件
    return !badge.isOwned && badge.currentProgress >= badge.target
  }).length
}

// 获取用户信息（检查是否设置了支付密码）
const fetchUserInfo = async () => {
  try {
    const response = await getUserInfo()
    if (response.code === 200) {
      hasPaymentPassword.value = response.data.hasPaymentPassword || false
    }
  } catch (error) {
    console.error('获取用户信息失败:', error)
  }
}

// 获取商城数据
const fetchMallData = async () => {
  loading.value = true
  try {
    // 并行获取所有数据
    const [assetsRes, statsRes, titlesRes, badgesRes] = await Promise.all([
      getUserAssets(),
      getUserStats(),
      getAllTitles(),
      getAllBadges()
    ])
    
    if (assetsRes.code === 200) {
      userAssets.value = assetsRes.data
    }
    
    if (statsRes.code === 200) {
      userStats.value = statsRes.data
    }
    
    if (titlesRes.code === 200) {
      titles.value = titlesRes.data
    }
    
    if (badgesRes.code === 200) {
      badges.value = badgesRes.data
    }
    
    // 同步更新 gameStore 中的数据，用于侧边栏红点提示计算
    if (assetsRes.code === 200 && titlesRes.code === 200 && badgesRes.code === 200 && statsRes.code === 200) {
      // 更新积分
      gameStore.userPoints = userAssets.value.points
      
      // 更新统计数据
      gameStore.userStats.walkCheckins = userStats.value.walkCheckins || 0
      gameStore.userStats.plateCheckins = userStats.value.plateCheckins || 0
      gameStore.userStats.rideCheckins = userStats.value.rideCheckins || 0
      gameStore.userStats.transitCheckins = userStats.value.transitCheckins || 0
      gameStore.userStats.totalCheckins = userStats.value.totalCheckins || 0
      
      // 更新称号数据（用于计算红点）
      // 清空原有数据并重新填充
      gameStore.titles.length = 0
      titles.value.forEach(title => {
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
      
      // 更新勋章数据（用于计算红点，包含currentProgress）
      // 清空原有数据并重新填充
      gameStore.badges.length = 0
      badges.value.forEach(badge => {
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
    console.error('获取商城数据失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  } finally {
    loading.value = false
  }
}

// 监听路由变化，重新获取数据
watch(() => route.path, () => {
  fetchMallData()
}, { immediate: true })

// 组件挂载时获取数据
onMounted(() => {
  fetchUserInfo()
  fetchMallData()
})
</script>

<style scoped>
.mall-page {
  padding: 24px;
  background: linear-gradient(180deg, #e8f5e9 0%, #f5f7fa 100%);
  min-height: calc(100vh - 60px);
}

/* 加载状态 */
.loading-container {
  padding: 40px 0;
}

/* ==================== 资产卡片 ==================== */
.assets-card {
  position: relative;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 50%, #004d40 100%);
  border-radius: 20px;
  padding: 32px;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(38, 166, 154, 0.3);
}

.assets-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.bg-circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
}

.circle-1 { width: 200px; height: 200px; top: -80px; right: -40px; }
.circle-2 { width: 150px; height: 150px; bottom: -60px; left: 20%; }
.circle-3 { width: 100px; height: 100px; top: 40%; right: 30%; }

.assets-content {
  position: relative;
  z-index: 2;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.assets-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assets-label {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.8);
  letter-spacing: 1px;
}

.assets-value {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.value-number {
  font-size: 48px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 2px;
}

.value-unit {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.9);
}

.assets-tip {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

/* 统计概览区域 */
.stats-overview {
  display: flex;
  align-items: stretch;
  gap: 20px;
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  justify-content: space-around;
  scrollbar-width: none;
  -ms-overflow-style: none;
  padding-bottom: 10px;
  width: 100%;
}

.stats-overview::-webkit-scrollbar {
  display: none;
}

.stat-block {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.12);
  padding: 16px 20px;
  border-radius: 12px;
  backdrop-filter: blur(4px);
  min-width: 140px;
  flex: 0 0 auto;
  white-space: nowrap;
  transition: all 0.3s ease;
}

.stat-block:hover {
  background: rgba(255, 255, 255, 0.18);
  transform: translateY(-2px);
}

.stat-icon-bg {
  font-size: 28px;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
}

.stat-data {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-data .stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.2;
}

.stat-data .stat-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.75);
  white-space: nowrap;
}

.assets-decoration {
  position: absolute;
  right: 40px;
  bottom: -20px;
  z-index: 1;
  opacity: 0.15;
}

.deco-icon {
  font-size: 140px;
}

/* ==================== 商城内容 ==================== */
.mall-content {
  background: #ffffff;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.section-header {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.section-header h3 {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.section-header p {
  font-size: 13px;
  color: #909399;
  margin: 0;
  width: 100%;
}

/* ==================== 称号卡片 ==================== */
.product-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.title-card {
  position: relative;
  background: #ffffff;
  border-radius: 16px;
  padding: 20px;
  border: 2px solid #f0f0f0;
  transition: all 0.3s ease;
  overflow: hidden;
}

.title-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
}

.title-card.level-0 { border-color: #e0e0e0; }
.title-card.level-1 { border-color: #90a4ae; }
.title-card.level-2 { border-color: #4dd0e1; }
.title-card.level-3 { border-color: #66bb6a; }
.title-card.level-4 { border-color: #ffa726; }
.title-card.level-5 { border-color: #ef5350; background: linear-gradient(135deg, #fff8e1 0%, #ffecb3 100%); }

/* 佩戴中的称号特殊样式 */
.title-card.is-equipped {
  border-color: #ffb300 !important;
  background: linear-gradient(135deg, #fff8e1 0%, #fffde7 100%);
  box-shadow: 0 4px 20px rgba(255, 179, 0, 0.25);
}

/* 佩戴中角标 */
.title-card .equipped-ribbon {
  position: absolute;
  top: 12px;
  right: -32px;
  background: linear-gradient(135deg, #ffb300 0%, #ff8f00 100%);
  color: #5d4037;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 40px;
  transform: rotate(45deg);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 10;
}

.level-aura {
  position: absolute;
  inset: -50%;
  background: radial-gradient(circle, rgba(255, 193, 7, 0.1) 0%, transparent 70%);
  animation: pulse-aura 3s ease-in-out infinite;
}

@keyframes pulse-aura {
  0%, 100% { opacity: 0.5; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.1); }
}

.title-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  position: relative;
  z-index: 1;
}

.title-icon {
  font-size: 40px;
}

.title-info {
  flex: 1;
}

.title-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 6px;
}

.level-tag {
  font-weight: 500;
}

.level-progress {
  margin-bottom: 16px;
  position: relative;
  z-index: 1;
}

.progress-bar {
  height: 6px;
  background: #f0f0f0;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease;
}

.progress-fill.level-1 { background: linear-gradient(90deg, #90a4ae, #b0bec5); }
.progress-fill.level-2 { background: linear-gradient(90deg, #4dd0e1, #80deea); }
.progress-fill.level-3 { background: linear-gradient(90deg, #66bb6a, #81c784); }
.progress-fill.level-4 { background: linear-gradient(90deg, #ffa726, #ffb74d); }
.progress-fill.level-5 { background: linear-gradient(90deg, #ef5350, #ff8a65); }

.progress-dots {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e0e0e0;
  transition: all 0.3s;
}

.dot.active {
  background: #26a69a;
  box-shadow: 0 0 8px rgba(38, 166, 154, 0.5);
}

.upgrade-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-size: 13px;
  position: relative;
  z-index: 1;
}

.next-level {
  color: #909399;
}

.upgrade-cost {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #26a69a;
  font-weight: 600;
}

.upgrade-info.max-level {
  justify-content: center;
}

.legend-text {
  color: #ff9800;
  font-weight: 600;
  font-size: 14px;
}

/* 称号底部操作区（与勋章卡片统一风格） */
.title-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid #f5f5f5;
  position: relative;
  z-index: 1;
}

.title-footer .status-text {
  font-size: 13px;
  font-weight: 500;
}

.title-footer .status-text.status-locked {
  color: #c0c4cc;
}

.title-footer .status-text.status-upgradable {
  color: #e6a23c;
}

.title-footer .status-text.status-legend {
  color: #ff9800;
  font-weight: 600;
}

.title-footer .status-text.status-equipped {
  color: #26a69a;
}

.title-footer .action-area {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.title-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-weight: 500;
}

.title-btn.unlock-btn {
  background: linear-gradient(135deg, #409eff 0%, #337ecc 100%);
  border: none;
}

.title-btn.unlock-btn:hover {
  background: linear-gradient(135deg, #337ecc 0%, #2a6ab8 100%);
}

.title-btn.upgrade-btn {
  background: linear-gradient(135deg, #e6a23c 0%, #cf8f2e 100%);
  border: none;
  color: #ffffff;
}

.title-btn.upgrade-btn:hover {
  background: linear-gradient(135deg, #cf8f2e 0%, #b87d28 100%);
}

.title-btn.equip-btn {
  background: linear-gradient(135deg, #67c23a 0%, #529b2e 100%);
  border: none;
}

.title-btn.equip-btn:hover {
  background: linear-gradient(135deg, #529b2e 0%, #448526 100%);
}

.title-btn.unequip-btn {
  border-color: #f56c6c;
  color: #f56c6c;
}

.title-btn.unequip-btn:hover {
  background: #fef0f0;
  border-color: #f56c6c;
}

/* ==================== 勋章系统 ==================== */
.badge-category {
  margin-bottom: 32px;
}

.badge-category:last-child {
  margin-bottom: 0;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px dashed #e0e0e0;
}

.category-icon {
  font-size: 24px;
}

.category-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.category-count {
  font-size: 13px;
  color: #909399;
  background: #f5f5f5;
  padding: 4px 12px;
  border-radius: 12px;
}

.category-equipped {
  margin-left: auto;
}

.badge-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.badge-card {
  position: relative;
  background: #ffffff;
  border-radius: 16px;
  padding: 20px;
  border: 2px solid #f0f0f0;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
}

.badge-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
}

.badge-card.locked {
  background: #fafafa;
  border-color: #e8e8e8;
}

.badge-card.unlockable {
  border-color: #81c784;
  background: linear-gradient(135deg, #f1f8e9 0%, #ffffff 100%);
}

.badge-card.owned {
  border-color: #b0bec5;
}

.badge-card.equipped {
  border-color: #26a69a;
  background: linear-gradient(135deg, #e0f2f1 0%, #ffffff 100%);
  box-shadow: 0 4px 16px rgba(38, 166, 154, 0.2);
}

/* 佩戴中角标 */
.equipped-ribbon {
  position: absolute;
  top: 12px;
  right: -32px;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 40px;
  transform: rotate(45deg);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.badge-icon-wrapper {
  position: relative;
  display: flex;
  justify-content: center;
  margin-bottom: 12px;
}

.badge-icon {
  font-size: 48px;
  display: block;
  transition: all 0.3s;
}

.badge-icon.grayscale {
  filter: grayscale(0.8);
  opacity: 0.5;
}

.owned-stamp {
  position: absolute;
  bottom: -4px;
  right: calc(50% - 36px);
  width: 22px;
  height: 22px;
  background: #4caf50;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 12px;
  box-shadow: 0 2px 6px rgba(76, 175, 80, 0.4);
}

.badge-info {
  text-align: center;
  margin-bottom: 12px;
}

.badge-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 6px;
}

.badge-desc {
  font-size: 12px;
  color: #909399;
  margin: 0;
  line-height: 1.5;
}

.badge-progress {
  margin-bottom: 16px;
}

.progress-text {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  font-size: 13px;
}

.progress-text .current {
  font-weight: 600;
  color: #26a69a;
}

.progress-text .separator {
  color: #c0c4cc;
}

.progress-text .target {
  color: #909399;
}

.badge-owned-info {
  display: flex;
  justify-content: center;
  margin-bottom: 16px;
}

.badge-owned-info .el-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 底部操作区 */
.badge-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid #f5f5f5;
}

.status-text {
  font-size: 13px;
  font-weight: 500;
}

.status-text.status-locked {
  color: #c0c4cc;
}

.status-text.status-unlockable {
  color: #67c23a;
}

.status-text.status-owned {
  color: #909399;
}

.status-text.status-equipped {
  color: #26a69a;
}

.action-area {
  flex-shrink: 0;
}

.badge-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border-radius: 6px;
  font-weight: 500;
}

.badge-btn .btn-icon {
  font-size: 14px;
  line-height: 1;
}

.badge-btn.unlock-btn {
  background: linear-gradient(135deg, #66bb6a 0%, #43a047 100%);
  border: none;
}

.badge-btn.unlock-btn:hover {
  background: linear-gradient(135deg, #43a047 0%, #2e7d32 100%);
}

.badge-btn.equip-btn {
  border-color: #26a69a;
  color: #26a69a;
}

.badge-btn.equip-btn:hover {
  background: #e0f2f1;
  border-color: #00897b;
  color: #00897b;
}

.badge-btn.unequip-btn {
  border-color: #f56c6c;
  color: #f56c6c;
}

.badge-btn.unequip-btn:hover {
  background: #fef0f0;
  border-color: #f56c6c;
}

/* ==================== 响应式 ==================== */
@media (max-width: 1400px) {
  .product-grid, .badge-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1024px) {
  .product-grid, .badge-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .stats-overview {
    justify-content: flex-start;
  }
}

@media (max-width: 768px) {
  .assets-content {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
  
  .value-number {
    font-size: 36px;
  }
  
  .product-grid, .badge-grid {
    grid-template-columns: 1fr;
  }
  
  .category-equipped {
    display: none;
  }
  
  .stats-overview {
    width: 100%;
    justify-content: flex-start;
    gap: 16px;
  }
  
  .stat-block {
    min-width: 120px;
    padding: 12px 16px;
  }
  
  .stat-icon-bg {
    font-size: 24px;
    width: 40px;
    height: 40px;
  }
  
  .stat-data .stat-value {
    font-size: 20px;
  }
  
  .stat-data .stat-label {
    font-size: 10px;
  }
}
</style>
