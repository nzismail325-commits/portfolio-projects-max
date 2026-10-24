<template>
  <div class="rank-container">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-skeleton :rows="10" animated />
    </div>
    
    <!-- 页面内容 -->
    <template v-else>
      <!-- 页面标题区 -->
      <div class="rank-header">
        <div class="header-bg"></div>
        <div class="header-content">
          <h1 class="page-title">{{ pageConfig.title }}</h1>
          <p class="page-subtitle">{{ pageConfig.subtitle }}</p>
          <div class="header-actions">
            <!-- 管理员切换按钮 - 仅管理员可见 -->
            <el-button 
              v-if="userStore.role === 'admin'" 
              type="warning" 
              class="toggle-real-info-btn"
              @click="toggleShowRealInfo"
            >
              {{ showRealInfo ? '隐藏学生真实信息' : '显示学生真实信息' }}
            </el-button>
            <!-- 设置展示按钮 - 仅学生且勋章/称号榜可见 -->
            <el-button 
              v-if="canSetDisplay" 
              type="primary" 
              class="set-display-btn"
              @click="openDisplayDialog"
            >
              ✨ 设置我的展示
            </el-button>
          </div>
        </div>
      </div>

      <!-- 前三名领奖台 -->
    <div class="podium-section">
      <div class="podium-wrapper">
        <!-- 亚军 (左侧) -->
        <div class="podium-item silver" v-if="topThree[1]">
          <div class="rank-badge silver-badge">2</div>
          <!-- 称号榜：头顶大称号标签 -->
          <div 
            v-if="currentType === 'titles' && topThree[1].featuredItem" 
            class="podium-title-badge"
            :class="getTitleLevelClass(topThree[1].featuredItem.level)"
          >
            <span class="title-badge-name">{{ topThree[1].featuredItem.name }}</span>
            <span class="title-badge-level">Lv.{{ topThree[1].featuredItem.level }}</span>
          </div>
          <!-- 勋章榜：头顶勋章标签 -->
          <div 
            v-if="currentType === 'badges' && topThree[1].featuredItem" 
            class="podium-badge-tag"
            :class="getBadgeRarityClass(topThree[1].featuredItem, 2)"
          >
            <span class="badge-tag-icon">{{ topThree[1].featuredItem.icon }}</span>
            <span class="badge-tag-name">{{ topThree[1].featuredItem.name }}</span>
          </div>
          <div class="avatar-wrapper silver-glow">
            <el-avatar :size="80" :src="topThree[1].avatar">
              {{ getDisplayName(topThree[1]).charAt(0) }}
            </el-avatar>
          </div>
          <div class="crown-icon">🥈</div>
          <h3 class="player-name">{{ getDisplayName(topThree[1]) }}</h3>
          <p class="player-id" v-if="shouldShowStudentId(topThree[1])">{{ topThree[1].studentId }}</p>
          <div class="score-display silver-score">
            <span class="score-value">{{ formatValue(topThree[1]) }}</span>
            <span class="score-unit">{{ pageConfig.unit }}</span>
          </div>
          <div class="pedestal silver-pedestal">
            <div class="pedestal-number">2</div>
          </div>
        </div>

        <!-- 冠军 (中间，最大) -->
        <div class="podium-item gold" v-if="topThree[0]">
          <div class="champion-crown">👑</div>
          <div class="rank-badge gold-badge">1</div>
          <!-- 称号榜：头顶大称号标签（冠军特大号） -->
          <div 
            v-if="currentType === 'titles' && topThree[0].featuredItem" 
            class="podium-title-badge champion-title-badge"
            :class="getTitleLevelClass(topThree[0].featuredItem.level)"
          >
            <span class="title-badge-name">{{ topThree[0].featuredItem.name }}</span>
            <span class="title-badge-level">Lv.{{ topThree[0].featuredItem.level }}</span>
          </div>
          <!-- 勋章榜：头顶勋章标签（冠军特大号） -->
          <div 
            v-if="currentType === 'badges' && topThree[0].featuredItem" 
            class="podium-badge-tag champion-badge-tag"
            :class="getBadgeRarityClass(topThree[0].featuredItem, 1)"
          >
            <span class="badge-tag-icon">{{ topThree[0].featuredItem.icon }}</span>
            <span class="badge-tag-name">{{ topThree[0].featuredItem.name }}</span>
          </div>
          <div class="avatar-wrapper gold-glow">
            <el-avatar :size="100" :src="topThree[0].avatar">
              {{ getDisplayName(topThree[0]).charAt(0) }}
            </el-avatar>
            <div class="sparkle-effect"></div>
          </div>
          <div class="crown-icon gold-crown">🥇</div>
          <h3 class="player-name champion-name">{{ getDisplayName(topThree[0]) }}</h3>
          <p class="player-id" v-if="shouldShowStudentId(topThree[0])">{{ topThree[0].studentId }}</p>
          <div class="score-display gold-score">
            <span class="score-value">{{ formatValue(topThree[0]) }}</span>
            <span class="score-unit">{{ pageConfig.unit }}</span>
          </div>
          <div class="pedestal gold-pedestal">
            <div class="pedestal-number">1</div>
          </div>
        </div>

        <!-- 季军 (右侧) -->
        <div class="podium-item bronze" v-if="topThree[2]">
          <div class="rank-badge bronze-badge">3</div>
          <!-- 称号榜：头顶大称号标签 -->
          <div 
            v-if="currentType === 'titles' && topThree[2].featuredItem" 
            class="podium-title-badge"
            :class="getTitleLevelClass(topThree[2].featuredItem.level)"
          >
            <span class="title-badge-name">{{ topThree[2].featuredItem.name }}</span>
            <span class="title-badge-level">Lv.{{ topThree[2].featuredItem.level }}</span>
          </div>
          <!-- 勋章榜：头顶勋章标签 -->
          <div 
            v-if="currentType === 'badges' && topThree[2].featuredItem" 
            class="podium-badge-tag"
            :class="getBadgeRarityClass(topThree[2].featuredItem, 3)"
          >
            <span class="badge-tag-icon">{{ topThree[2].featuredItem.icon }}</span>
            <span class="badge-tag-name">{{ topThree[2].featuredItem.name }}</span>
          </div>
          <div class="avatar-wrapper bronze-glow">
            <el-avatar :size="80" :src="topThree[2].avatar">
              {{ getDisplayName(topThree[2]).charAt(0) }}
            </el-avatar>
          </div>
          <div class="crown-icon">🥉</div>
          <h3 class="player-name">{{ getDisplayName(topThree[2]) }}</h3>
          <p class="player-id" v-if="shouldShowStudentId(topThree[2])">{{ topThree[2].studentId }}</p>
          <div class="score-display bronze-score">
            <span class="score-value">{{ formatValue(topThree[2]) }}</span>
            <span class="score-unit">{{ pageConfig.unit }}</span>
          </div>
          <div class="pedestal bronze-pedestal">
            <div class="pedestal-number">3</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 4-100 名列表 -->
    <div class="list-section">
      <div class="list-header">
        <span class="list-title">🏆 排行榜</span>
        <span class="list-info" v-if="restRanking.length > 0">第 4 - {{ 3 + restRanking.length }} 名</span>
        <span class="list-info" v-else>暂无更多排名</span>
      </div>
      <div class="rank-list">
        <div 
          v-for="(item, index) in restRanking" 
          :key="item.studentId"
          class="rank-item"
          :class="{ 'even-row': index % 2 === 0, 'is-current-user': item.isCurrentUser }"
        >
          <div class="rank-number">{{ index + 4 }}</div>
          <div class="user-info">
            <el-avatar :size="44" :src="item.avatar">
              {{ getDisplayName(item).charAt(0) }}
            </el-avatar>
            <div class="user-detail">
              <div class="user-name-row">
                <span class="user-name">{{ getDisplayName(item) }}</span>
                <!-- 勋章榜：名字旁边的勋章标签 -->
                <div 
                  v-if="currentType === 'badges' && item.featuredItem" 
                  class="list-badge-tag"
                  :class="getBadgeRarityClass(item.featuredItem, index + 4)"
                >
                  <span class="list-btag-icon">{{ item.featuredItem.icon }}</span>
                  <span class="list-btag-name">{{ item.featuredItem.name }}</span>
                </div>
                <!-- 称号榜：名字旁边的称号标签 -->
                <div 
                  v-if="currentType === 'titles' && item.featuredItem" 
                  class="list-title-badge"
                  :class="getTitleLevelClass(item.featuredItem.level)"
                >
                  <span class="list-badge-name">{{ item.featuredItem.name }}</span>
                  <span class="list-badge-level">Lv.{{ item.featuredItem.level }}</span>
                </div>
              </div>
              <span class="user-id" v-if="shouldShowStudentId(item)">{{ item.studentId }}</span>
            </div>
          </div>
          <div class="score-info">
            <span class="score-num">{{ formatValue(item) }}</span>
            <span class="score-label">{{ pageConfig.unit }}</span>
          </div>
          <div class="trend-indicator" :class="item.trend">
            <el-icon v-if="item.trend === 'up'"><Top /></el-icon>
            <el-icon v-else-if="item.trend === 'down'"><Bottom /></el-icon>
            <el-icon v-else><Minus /></el-icon>
          </div>
        </div>
      </div>
    </div>

      <!-- 底部装饰 -->
      <div class="footer-decoration">
        <div class="decoration-line"></div>
        <span class="decoration-text">📊 数据每日更新</span>
        <div class="decoration-line"></div>
      </div>
    </template>

    <!-- 设置展示 Dialog -->
    <el-dialog 
      v-model="displayDialogVisible" 
      :title="displayDialogTitle"
      width="520px"
      class="display-dialog"
    >
      <!-- 勋章选择 Grid -->
      <div v-if="currentType === 'badges'" class="badge-grid">
        <div v-if="gameStore.earnedBadges.length === 0" class="empty-tip">
          <el-empty description="暂无已获得的勋章，快去打卡获取吧！" />
        </div>
        <div 
          v-for="badge in gameStore.earnedBadges" 
          :key="badge.id"
          class="badge-item"
          :class="{ 'is-selected': selectedBadgeId === badge.id }"
          @click="selectBadge(badge)"
        >
          <div class="badge-icon">{{ badge.icon }}</div>
          <div class="badge-name">{{ badge.name }}</div>
          <div class="badge-check" v-if="selectedBadgeId === badge.id">
            <el-icon><Check /></el-icon>
          </div>
        </div>
      </div>

      <!-- 称号选择 List -->
      <div v-if="currentType === 'titles'" class="title-list">
        <div v-if="ownedTitles.length === 0" class="empty-tip">
          <el-empty description="暂无已解锁的称号，快去商城购买吧！" />
        </div>
        <div 
          v-for="title in ownedTitles" 
          :key="title.id"
          class="title-item"
          :class="{ 'is-selected': selectedTitleId === title.id }"
          @click="selectTitle(title)"
        >
          <div class="title-icon">{{ title.icon }}</div>
          <div class="title-info">
            <div class="title-name">{{ title.name }}</div>
            <el-tag :type="getTitleTagType(title.level)" size="small">
              Lv.{{ title.level }} {{ gameStore.getLevelName(title.level) }}
            </el-tag>
          </div>
          <div class="title-check" v-if="selectedTitleId === title.id">
            <el-icon><Check /></el-icon>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="displayDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmDisplay" :disabled="!hasSelection">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Top, Bottom, Minus, Check } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useGameStore } from '@/stores/game'
import { getPointsRank, getBadgesRank, getTitlesRank, getCheckinsRank, setDisplay } from '@/api/rank'

const route = useRoute()
const userStore = useUserStore()
const gameStore = useGameStore()

// 页面配置映射
const pageConfigs = {
  points: {
    title: '🌍 校园碳积分总榜',
    subtitle: '积跬步以至千里，聚碳分以护地球',
    field: 'points',
    unit: '积分'
  },
  badges: {
    title: '🏅 勋章收集达人榜',
    subtitle: '每一枚勋章都是低碳路上的里程碑',
    field: 'badgesCount',
    unit: '枚勋章'
  },
  titles: {
    title: '🎖️ 荣誉称号荣耀榜',
    subtitle: '称号加身，荣耀无限',
    field: 'titleScore',
    unit: '荣誉分'
  },
  checkins: {
    title: '📅 低碳勤奋打卡榜',
    subtitle: '坚持打卡，习惯成自然',
    field: 'checkins',
    unit: '次打卡'
  }
}

// 当前榜单类型
const currentType = computed(() => {
  const path = route.path
  if (path.includes('points')) return 'points'
  if (path.includes('badges')) return 'badges'
  if (path.includes('titles')) return 'titles'
  if (path.includes('checkins')) return 'checkins'
  return 'points'
})

// 当前页面配置
const pageConfig = computed(() => pageConfigs[currentType.value])

// 是否可以设置展示（学生 + 勋章/称号榜）
const canSetDisplay = computed(() => {
  return userStore.role === 'student' && 
         (currentType.value === 'badges' || currentType.value === 'titles')
})

// 管理员切换显示真实信息的状态
const showRealInfo = ref(false)

// 加载状态
const loading = ref(false)

// 原始数据
const rawData = ref([])

// 获取排行榜数据
const fetchRankData = async () => {
  loading.value = true
  try {
    let response
    switch (currentType.value) {
      case 'points':
        response = await getPointsRank()
        break
      case 'badges':
        response = await getBadgesRank()
        break
      case 'titles':
        response = await getTitlesRank()
        break
      case 'checkins':
        response = await getCheckinsRank()
        break
      default:
        response = await getPointsRank()
    }
    
    if (response.code === 200 && response.data) {
      // 转换数据格式，确保所有字段都有值
      rawData.value = response.data.map(item => ({
        userId: item.userId,
        name: item.name || '',
        nickname: item.nickname || item.name || '',
        realName: item.realName || item.name || '',
        studentId: item.studentId || '',
        avatar: item.avatar || '',
        points: item.points || 0,
        badgesCount: item.badgesCount || 0,
        checkins: item.checkins || 0,
        titleScore: item.titleScore || 0,
        featuredItem: item.featuredItem || null,
        trend: item.trend || 'stable',
        isCurrentUser: item.isCurrentUser || false
      }))
    } else {
      // 业务错误已在 request.js 拦截器中统一处理
      rawData.value = []
    }
  } catch (error) {
    console.error('获取排行榜数据失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
    rawData.value = []
  } finally {
    loading.value = false
  }
}

// 排序后的数据
const sortedData = computed(() => {
  const field = pageConfig.value.field
  return [...rawData.value].sort((a, b) => b[field] - a[field])
})

// 前三名
const topThree = computed(() => sortedData.value.slice(0, 3))

// 4-100 名
const restRanking = computed(() => sortedData.value.slice(3, 100))

// 格式化显示值
const formatValue = (item) => {
  const field = pageConfig.value.field
  const value = item[field]
  return value.toLocaleString()
}

// 切换显示真实信息（仅管理员）
const toggleShowRealInfo = () => {
  showRealInfo.value = !showRealInfo.value
}

// 获取显示名称（根据切换状态）
const getDisplayName = (item) => {
  if (userStore.role === 'admin' && showRealInfo.value) {
    return item.realName || item.name
  }
  return item.nickname || item.name
}

// 是否应该显示学号
const shouldShowStudentId = (item) => {
  return userStore.role === 'admin' && showRealInfo.value && item.studentId
}

// 根据称号等级获取 Tag 类型（用于 Dialog）
const getTitleTagType = (level) => {
  if (level >= 5) return 'danger'
  if (level >= 4) return 'warning'
  if (level >= 3) return 'success'
  if (level >= 2) return 'primary'
  return 'info'
}

// 根据称号等级获取样式 class
const getTitleLevelClass = (level) => {
  if (level >= 5) return 'level-legendary'
  if (level >= 4) return 'level-epic'
  if (level >= 3) return 'level-rare'
  if (level >= 2) return 'level-uncommon'
  return 'level-common'
}

// 根据勋章信息和排名获取稀有度样式 class
const getBadgeRarityClass = (badgeItem, rank) => {
  // 高级勋章名单（前三名专用勋章）
  const premiumBadgeNames = ['净坛使者', '低碳达人', '环保大师']
  const isPremium = premiumBadgeNames.includes(badgeItem.name)
  
  if (isPremium && rank === 1) return 'badge-legendary'    // 冠军传说级 - 金色
  if (isPremium && rank === 2) return 'badge-epic'         // 亚军史诗级 - 紫色
  if (isPremium && rank === 3) return 'badge-rare'         // 季军稀有级 - 翠绿
  if (rank <= 5) return 'badge-uncommon'                   // 4-5名优秀级 - 蓝色
  return 'badge-common'                                    // 其他普通级 - 青灰
}

// ==================== 设置展示 Dialog ====================
const displayDialogVisible = ref(false)
const selectedBadgeId = ref(null)
const selectedTitleId = ref(null)

// Dialog 标题
const displayDialogTitle = computed(() => {
  return currentType.value === 'badges' 
    ? '🏅 选择要展示的勋章' 
    : '🎖️ 选择要展示的称号'
})

// 已拥有的称号
const ownedTitles = computed(() => {
  return gameStore.titles.filter(t => t.isOwned && t.level > 0)
})

// 是否有选中
const hasSelection = computed(() => {
  if (currentType.value === 'badges') {
    return selectedBadgeId.value !== null
  }
  return selectedTitleId.value !== null
})

// 打开 Dialog
const openDisplayDialog = () => {
  selectedBadgeId.value = null
  selectedTitleId.value = null
  displayDialogVisible.value = true
}

// 选择勋章
const selectBadge = (badge) => {
  selectedBadgeId.value = badge.id
}

// 选择称号
const selectTitle = (title) => {
  selectedTitleId.value = title.id
}

// 确认设置展示
const confirmDisplay = async () => {
  try {
    const type = currentType.value === 'badges' ? 'badge' : 'title'
    const itemId = currentType.value === 'badges' ? selectedBadgeId.value : selectedTitleId.value
    
    if (!itemId) {
      ElMessage.warning('请选择要展示的' + (currentType.value === 'badges' ? '勋章' : '称号'))
      return
    }
    
    const response = await setDisplay({ type, itemId })
    
    if (response.code === 200) {
      displayDialogVisible.value = false
      ElMessage.success('展示设置成功！同学们都看到了你的风采 ✨')
      // 重新获取排行榜数据
      await fetchRankData()
    }
    // 业务错误已在 request.js 拦截器中统一处理
  } catch (error) {
    console.error('设置展示失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  }
}

// 监听路由变化时重新获取数据
watch(() => route.path, () => {
  fetchRankData()
}, { immediate: true })

// 组件挂载时获取数据
onMounted(() => {
  fetchRankData()
})
</script>

<style scoped>
.rank-container {
  min-height: 100vh;
  background: linear-gradient(180deg, #e8f5e9 0%, #f1f8f6 50%, #ffffff 100%);
  padding-bottom: 40px;
}

/* 加载状态 */
.loading-container {
  padding: 40px 24px;
  max-width: 800px;
  margin: 0 auto;
}

/* 页面标题区 */
.rank-header {
  position: relative;
  padding: 48px 24px 32px;
  text-align: center;
  overflow: hidden;
}

.header-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #00897b 0%, #26a69a 50%, #4db6ac 100%);
  clip-path: ellipse(80% 100% at 50% 0%);
}

.header-content {
  position: relative;
  z-index: 1;
}

.page-title {
  font-size: 32px;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 8px 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  letter-spacing: 2px;
}

.page-subtitle {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
  margin: 0 0 16px 0;
  font-weight: 400;
}

/* 头部操作按钮区域 */
.header-actions {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* 切换真实信息按钮 */
.toggle-real-info-btn {
  background: rgba(255, 193, 7, 0.2);
  border: 1px solid rgba(255, 193, 7, 0.4);
  color: #fff;
  font-weight: 500;
  transition: all 0.3s;
}

.toggle-real-info-btn:hover {
  background: rgba(255, 193, 7, 0.3);
  border-color: rgba(255, 193, 7, 0.6);
  transform: translateY(-2px);
}

/* 设置展示按钮 */
.set-display-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: #fff;
  font-weight: 500;
  transition: all 0.3s;
}

.set-display-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  border-color: rgba(255, 255, 255, 0.6);
  transform: translateY(-2px);
}

/* 领奖台区域 */
.podium-section {
  padding: 20px 24px 40px;
  margin-top: -20px;
}

.podium-wrapper {
  display: flex;
  justify-content: center;
  align-items: flex-end;
  gap: 16px;
  max-width: 800px;
  margin: 0 auto;
}

.podium-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  padding: 20px 16px;
  background: #ffffff;
  border-radius: 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  transition: transform 0.3s ease;
  min-width: 200px;
  flex: 0 0 auto;
}

.podium-item:hover {
  transform: translateY(-8px);
}

.podium-item.gold {
  order: 2;
  padding: 32px 24px;
  z-index: 10;
  min-width: 220px;
}

.podium-item.silver {
  order: 1;
}

.podium-item.bronze {
  order: 3;
}

/* 冠军皇冠 */
.champion-crown {
  position: absolute;
  top: -20px;
  font-size: 40px;
  animation: bounce 2s ease-in-out infinite;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

/* 排名徽章 */
.rank-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}

.gold-badge {
  background: linear-gradient(135deg, #ffd700 0%, #ffb300 100%);
  box-shadow: 0 2px 8px rgba(255, 193, 7, 0.5);
}

.silver-badge {
  background: linear-gradient(135deg, #c0c0c0 0%, #9e9e9e 100%);
  box-shadow: 0 2px 8px rgba(158, 158, 158, 0.5);
}

.bronze-badge {
  background: linear-gradient(135deg, #cd7f32 0%, #b8860b 100%);
  box-shadow: 0 2px 8px rgba(205, 127, 50, 0.5);
}

/* ==================== 称号榜 - 领奖台大称号标签 ==================== */
.podium-title-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 20px;
  margin-bottom: 12px;
  animation: titleGlow 2s ease-in-out infinite;
  position: relative;
  overflow: hidden;
}

.podium-title-badge::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    45deg,
    transparent 30%,
    rgba(255, 255, 255, 0.3) 50%,
    transparent 70%
  );
  animation: titleShine 3s ease-in-out infinite;
}

@keyframes titleShine {
  0% { transform: translateX(-100%) rotate(45deg); }
  100% { transform: translateX(100%) rotate(45deg); }
}

@keyframes titleGlow {
  0%, 100% { 
    filter: brightness(1);
    transform: scale(1);
  }
  50% { 
    filter: brightness(1.1);
    transform: scale(1.02);
  }
}

.champion-title-badge {
  padding: 10px 20px;
  font-size: 15px;
}

.title-badge-name {
  font-size: 14px;
  font-weight: 700;
  position: relative;
  z-index: 1;
}

.champion-title-badge .title-badge-name {
  font-size: 16px;
}

.title-badge-level {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.3);
  position: relative;
  z-index: 1;
}

.champion-title-badge .title-badge-level {
  font-size: 12px;
  padding: 3px 8px;
}

/* 称号等级样式 - 传说 (Lv.5) */
.level-legendary {
  background: linear-gradient(135deg, #ffd700 0%, #ff8c00 50%, #ffd700 100%);
  box-shadow: 0 4px 20px rgba(255, 193, 7, 0.5), 0 0 30px rgba(255, 140, 0, 0.3);
  color: #5d4037;
}

.level-legendary .title-badge-level {
  background: rgba(93, 64, 55, 0.2);
}

/* 称号等级样式 - 史诗 (Lv.4) */
.level-epic {
  background: linear-gradient(135deg, #ff9800 0%, #f57c00 50%, #ff9800 100%);
  box-shadow: 0 4px 16px rgba(255, 152, 0, 0.4), 0 0 20px rgba(245, 124, 0, 0.3);
  color: #fff;
}

.level-epic .title-badge-level {
  background: rgba(255, 255, 255, 0.2);
}

/* 称号等级样式 - 稀有 (Lv.3) */
.level-rare {
  background: linear-gradient(135deg, #26a69a 0%, #00897b 50%, #26a69a 100%);
  box-shadow: 0 4px 14px rgba(38, 166, 154, 0.4), 0 0 16px rgba(0, 137, 123, 0.3);
  color: #fff;
}

.level-rare .title-badge-level {
  background: rgba(255, 255, 255, 0.2);
}

/* 称号等级样式 - 优秀 (Lv.2) */
.level-uncommon {
  background: linear-gradient(135deg, #42a5f5 0%, #1e88e5 50%, #42a5f5 100%);
  box-shadow: 0 4px 12px rgba(66, 165, 245, 0.4);
  color: #fff;
}

.level-uncommon .title-badge-level {
  background: rgba(255, 255, 255, 0.2);
}

/* 称号等级样式 - 普通 (Lv.1) */
.level-common {
  background: linear-gradient(135deg, #78909c 0%, #546e7a 50%, #78909c 100%);
  box-shadow: 0 4px 10px rgba(120, 144, 156, 0.4);
  color: #fff;
}

.level-common .title-badge-level {
  background: rgba(255, 255, 255, 0.2);
}

/* 头像光环 */
.avatar-wrapper {
  position: relative;
  border-radius: 50%;
  padding: 4px;
  margin-bottom: 8px;
}

.gold-glow {
  background: linear-gradient(135deg, #ffd700, #ffb300, #ffd700);
  box-shadow: 0 0 30px rgba(255, 193, 7, 0.6);
  animation: goldGlow 2s ease-in-out infinite;
}

@keyframes goldGlow {
  0%, 100% { 
    box-shadow: 0 0 30px rgba(255, 193, 7, 0.6), 0 0 60px rgba(255, 193, 7, 0.3);
  }
  50% { 
    box-shadow: 0 0 40px rgba(255, 193, 7, 0.8), 0 0 80px rgba(255, 193, 7, 0.4);
  }
}

.silver-glow {
  background: linear-gradient(135deg, #e0e0e0, #bdbdbd, #e0e0e0);
  box-shadow: 0 0 20px rgba(189, 189, 189, 0.5);
}

.bronze-glow {
  background: linear-gradient(135deg, #d4a574, #cd7f32, #d4a574);
  box-shadow: 0 0 20px rgba(205, 127, 50, 0.5);
}

/* ==================== 勋章榜 - 领奖台勋章胶囊标签 ==================== */
.podium-badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 20px;
  margin-bottom: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.4), 0 0 20px rgba(118, 75, 162, 0.25);
  animation: badgeTagGlow 2.5s ease-in-out infinite;
  position: relative;
  overflow: hidden;
  transition: all 0.25s ease;
  white-space: nowrap;
}

.podium-badge-tag:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5), 0 0 25px rgba(118, 75, 162, 0.35);
}

.podium-badge-tag::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    45deg,
    transparent 30%,
    rgba(255, 255, 255, 0.25) 50%,
    transparent 70%
  );
  animation: badgeShine 3.5s ease-in-out infinite;
}

@keyframes badgeShine {
  0% { transform: translateX(-100%) rotate(45deg); }
  100% { transform: translateX(100%) rotate(45deg); }
}

@keyframes badgeTagGlow {
  0%, 100% {
    box-shadow: 0 4px 16px rgba(102, 126, 234, 0.4), 0 0 20px rgba(118, 75, 162, 0.25);
  }
  50% {
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.55), 0 0 28px rgba(118, 75, 162, 0.35);
  }
}

.champion-badge-tag {
  padding: 10px 20px;
}

.podium-badge-tag .badge-tag-icon {
  font-size: 16px;
  position: relative;
  z-index: 1;
}

.champion-badge-tag .badge-tag-icon {
  font-size: 20px;
}

.podium-badge-tag .badge-tag-name {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
  position: relative;
  z-index: 1;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.champion-badge-tag .badge-tag-name {
  font-size: 16px;
}

/* ==================== 勋章稀有度等级样式 ==================== */

/* 传说级勋章 (冠军专用) - 金色系，与称号传说级呼应 */
.podium-badge-tag.badge-legendary,
.list-badge-tag.badge-legendary {
  background: linear-gradient(135deg, #f6d365 0%, #fda085 50%, #f6d365 100%);
  box-shadow: 0 4px 20px rgba(253, 160, 133, 0.5), 0 0 30px rgba(246, 211, 101, 0.4);
}

.podium-badge-tag.badge-legendary .badge-tag-name,
.list-badge-tag.badge-legendary .list-btag-name {
  color: #5d4037;
  text-shadow: 0 1px 2px rgba(255, 255, 255, 0.4);
}

/* 史诗级勋章 (亚军专用) - 紫色系，与称号史诗级呼应但更深邃 */
.podium-badge-tag.badge-epic,
.list-badge-tag.badge-epic {
  background: linear-gradient(135deg, #a855f7 0%, #7c3aed 50%, #a855f7 100%);
  box-shadow: 0 4px 18px rgba(168, 85, 247, 0.5), 0 0 25px rgba(124, 58, 237, 0.35);
}

.podium-badge-tag.badge-epic .badge-tag-name,
.list-badge-tag.badge-epic .list-btag-name {
  color: #ffffff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
}

/* 稀有级勋章 (季军专用) - 翠绿色系，与称号稀有级呼应 */
.podium-badge-tag.badge-rare,
.list-badge-tag.badge-rare {
  background: linear-gradient(135deg, #10b981 0%, #059669 50%, #10b981 100%);
  box-shadow: 0 4px 16px rgba(16, 185, 129, 0.45), 0 0 20px rgba(5, 150, 105, 0.3);
}

.podium-badge-tag.badge-rare .badge-tag-name,
.list-badge-tag.badge-rare .list-btag-name {
  color: #ffffff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

/* 优秀级勋章 (4-5名) - 天蓝色系，与称号优秀级呼应 */
.podium-badge-tag.badge-uncommon,
.list-badge-tag.badge-uncommon {
  background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 50%, #38bdf8 100%);
  box-shadow: 0 4px 14px rgba(56, 189, 248, 0.4), 0 0 16px rgba(14, 165, 233, 0.25);
}

.podium-badge-tag.badge-uncommon .badge-tag-name,
.list-badge-tag.badge-uncommon .list-btag-name {
  color: #ffffff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

/* 普通级勋章 (其他排名) - 青灰色系，低调但清晰 */
.podium-badge-tag.badge-common,
.list-badge-tag.badge-common {
  background: linear-gradient(135deg, #64748b 0%, #475569 50%, #64748b 100%);
  box-shadow: 0 4px 12px rgba(100, 116, 139, 0.35), 0 0 12px rgba(71, 85, 105, 0.2);
}

.podium-badge-tag.badge-common .badge-tag-name,
.list-badge-tag.badge-common .list-btag-name {
  color: #ffffff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

/* 金光闪闪效果 */
.sparkle-effect {
  position: absolute;
  top: -10px;
  left: -10px;
  right: -10px;
  bottom: -10px;
  border-radius: 50%;
  pointer-events: none;
}

.sparkle-effect::before,
.sparkle-effect::after {
  content: '✨';
  position: absolute;
  font-size: 16px;
  animation: sparkle 1.5s ease-in-out infinite;
}

.sparkle-effect::before {
  top: 0;
  left: 5px;
  animation-delay: 0s;
}

.sparkle-effect::after {
  bottom: 5px;
  right: 0;
  animation-delay: 0.75s;
}

@keyframes sparkle {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  50% { opacity: 1; transform: scale(1.2); }
}

/* 皇冠图标 */
.crown-icon {
  font-size: 24px;
  margin-bottom: 4px;
}

.gold-crown {
  font-size: 32px;
}

/* 玩家信息 */
.player-name {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin: 4px 0 0 0;
}

.champion-name {
  font-size: 20px;
  color: #d4a017;
}

.player-id {
  font-size: 12px;
  color: #999;
  margin: 0 0 8px 0;
}

/* 分数显示 */
.score-display {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 8px 16px;
  border-radius: 20px;
  margin-bottom: 8px;
}

.gold-score {
  background: linear-gradient(135deg, #fff8e1 0%, #ffecb3 100%);
}

.silver-score {
  background: linear-gradient(135deg, #fafafa 0%, #eeeeee 100%);
}

.bronze-score {
  background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
}

.score-value {
  font-size: 24px;
  font-weight: 700;
  color: #333;
}

.podium-item.gold .score-value {
  font-size: 28px;
  color: #d4a017;
}

.score-unit {
  font-size: 12px;
  color: #666;
}

/* 领奖台底座 */
.pedestal {
  position: absolute;
  bottom: -20px;
  width: 100%;
  height: 40px;
  border-radius: 0 0 20px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gold-pedestal {
  background: linear-gradient(135deg, #ffd700 0%, #ffb300 100%);
  height: 60px;
  bottom: -30px;
}

.silver-pedestal {
  background: linear-gradient(135deg, #c0c0c0 0%, #9e9e9e 100%);
}

.bronze-pedestal {
  background: linear-gradient(135deg, #cd7f32 0%, #b8860b 100%);
}

.pedestal-number {
  font-size: 20px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.8);
}

/* 列表区域 */
.list-section {
  max-width: 800px;
  margin: 40px auto 0;
  padding: 0 24px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 0 8px;
}

.list-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.list-info {
  font-size: 13px;
  color: #999;
}

.rank-list {
  background: #ffffff;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

.rank-item {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  gap: 16px;
  transition: background 0.2s;
}

.rank-item:hover {
  background: #f5faf9;
}

.rank-item.even-row {
  background: #f8fbfa;
}

.rank-item.even-row:hover {
  background: #f0f7f5;
}

.rank-item.is-current-user {
  background: linear-gradient(90deg, rgba(38, 166, 154, 0.1), transparent);
  border-left: 3px solid #26a69a;
}

/* 排名数字 */
.rank-number {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}

/* 用户信息 */
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.avatar-with-badge {
  position: relative;
  flex-shrink: 0;
}

.list-featured-badge {
  position: absolute;
  bottom: -2px;
  right: -2px;
  font-size: 16px;
  background: #ffffff;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

.user-detail {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.user-name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ==================== 称号榜 - 列表中等称号标签 ==================== */
.list-title-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 12px;
  height: 24px;
  box-sizing: border-box;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}

.list-title-badge::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    45deg,
    transparent 30%,
    rgba(255, 255, 255, 0.2) 50%,
    transparent 70%
  );
  animation: titleShine 4s ease-in-out infinite;
}

.list-badge-name {
  font-size: 12px;
  font-weight: 600;
  position: relative;
  z-index: 1;
}

.list-badge-level {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.25);
  position: relative;
  z-index: 1;
}

/* ==================== 勋章榜 - 列表中勋章标签 ==================== */
.list-badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 12px;
  height: 24px;
  box-sizing: border-box;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
  transition: all 0.25s ease;
}

.list-badge-tag::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    45deg,
    transparent 30%,
    rgba(255, 255, 255, 0.2) 50%,
    transparent 70%
  );
  animation: badgeShine 4s ease-in-out infinite;
}

.list-badge-tag:hover {
  transform: translateY(-1px);
  filter: brightness(1.08);
}

.list-btag-icon {
  font-size: 12px;
  position: relative;
  z-index: 1;
}

.list-btag-name {
  font-size: 12px;
  font-weight: 600;
  position: relative;
  z-index: 1;
}

.user-id {
  font-size: 12px;
  color: #999;
}

/* 分数信息 */
.score-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  min-width: 80px;
}

.score-num {
  font-size: 18px;
  font-weight: 700;
  color: #26a69a;
}

.score-label {
  font-size: 11px;
  color: #999;
}

/* 趋势指示器 */
.trend-indicator {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.trend-indicator.up {
  background: #e8f5e9;
  color: #4caf50;
}

.trend-indicator.down {
  background: #ffebee;
  color: #f44336;
}

.trend-indicator.stable {
  background: #f5f5f5;
  color: #9e9e9e;
}

/* 底部装饰 */
.footer-decoration {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 40px;
  padding: 0 24px;
}

.decoration-line {
  flex: 1;
  max-width: 120px;
  height: 1px;
  background: linear-gradient(90deg, transparent, #26a69a, transparent);
}

.decoration-text {
  font-size: 13px;
  color: #999;
}

/* ==================== Dialog 样式 ==================== */
.display-dialog :deep(.el-dialog__header) {
  border-bottom: 1px solid #f0f0f0;
  padding-bottom: 16px;
}

.display-dialog :deep(.el-dialog__title) {
  font-size: 18px;
  font-weight: 600;
}

/* 勋章 Grid */
.badge-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 8px 0;
}

.badge-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 8px;
  border-radius: 12px;
  border: 2px solid #f0f0f0;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.badge-item:hover {
  border-color: #26a69a;
  background: #f0f9f8;
}

.badge-item.is-selected {
  border-color: #26a69a;
  background: linear-gradient(135deg, #e0f2f1, #b2dfdb);
}

.badge-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.badge-name {
  font-size: 12px;
  color: #666;
  text-align: center;
}

.badge-check {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #26a69a;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

/* 称号 List */
.title-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 0;
  max-height: 400px;
  overflow-y: auto;
}

.title-item {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-radius: 12px;
  border: 2px solid #f0f0f0;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.title-item:hover {
  border-color: #26a69a;
  background: #f0f9f8;
}

.title-item.is-selected {
  border-color: #26a69a;
  background: linear-gradient(135deg, #e0f2f1, #b2dfdb);
}

.title-icon {
  font-size: 28px;
  margin-right: 12px;
}

.title-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.title-check {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #26a69a;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-tip {
  padding: 40px 0;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .podium-wrapper {
    gap: 8px;
    padding: 0 8px;
  }
  
  .podium-item {
    padding: 16px 12px;
    min-width: 160px;
  }
  
  .podium-item.gold {
    padding: 24px 16px;
    min-width: 180px;
  }
  
  .avatar-wrapper.gold-glow .el-avatar {
    width: 80px !important;
    height: 80px !important;
  }
  
  .page-title {
    font-size: 24px;
  }
  
  .rank-item {
    padding: 12px 16px;
    gap: 12px;
  }
  
  .badge-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  
  .podium-title-badge {
    padding: 6px 12px;
  }
  
  .title-badge-name {
    font-size: 12px;
  }
  
  .user-name-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}
</style>
