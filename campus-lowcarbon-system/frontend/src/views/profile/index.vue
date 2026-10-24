<template>
  <div class="profile-page">
    <!-- 顶部用户身份卡片 -->
    <div class="identity-card">
      <div class="card-bg">
        <div class="bg-pattern"></div>
      </div>
      <div class="card-content">
        <div class="avatar-section">
          <div class="avatar-wrapper">
            <el-avatar 
              :size="100" 
              :src="getAvatarUrl()" 
              class="user-avatar"
            >
              {{ (userInfo.nickname || userInfo.name)?.charAt(0) || 'U' }}
            </el-avatar>
            <div class="avatar-ring"></div>
          </div>
        </div>
        
        <div class="info-section">
          <h1 class="user-name">{{ userInfo.nickname || userInfo.name }}</h1>
          
          <!-- 佩戴的称号 (Mini Tags) -->
          <div class="equipped-titles-row">
            <template v-if="equippedTitles.length > 0">
              <div 
                v-for="title in equippedTitles" 
                :key="title.id"
                class="mini-title-tag"
              >
                <span class="tag-icon">{{ title.icon }}</span>
                <span class="tag-name">{{ title.name }}</span>
              </div>
            </template>
            <div class="mini-title-tag empty" v-else>
              <span class="tag-icon">👑</span>
              <span class="tag-name">暂无佩戴</span>
            </div>
          </div>
          
          <!-- 佩戴的勋章 (Capsule Tag Style) -->
          <div class="equipped-badges-row">
            <template v-if="equippedBadges.length > 0">
              <div 
                v-for="badge in equippedBadges" 
                :key="badge.id"
                class="mini-badge-tag"
              >
                <span class="badge-tag-icon">{{ badge.icon }}</span>
                <span class="badge-tag-name">{{ badge.name }}</span>
              </div>
            </template>
            <div class="mini-badge-tag empty" v-else>
              <span class="badge-tag-icon">🎖️</span>
              <span class="badge-tag-name">暂无佩戴</span>
            </div>
          </div>
          
          <!-- 统计数据行 -->
          <div class="stats-row">
            <div class="stat-item">
              <span class="stat-icon">🌍</span>
              <span class="stat-value">{{ userInfo.stats.carbon }}</span>
              <span class="stat-label">累计减碳</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <span class="stat-icon">📅</span>
              <span class="stat-value">{{ gameStore.userStats.totalCheckins }}</span>
              <span class="stat-label">坚持打卡</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <span class="stat-icon">🏆</span>
              <span class="stat-value">{{ userInfo.stats.rank }}</span>
              <span class="stat-label">超过全校</span>
            </div>
          </div>
        </div>
        
        <div class="action-section">
          <el-button type="primary" plain circle @click="handleEdit">
            <el-icon><Edit /></el-icon>
          </el-button>
        </div>
      </div>
    </div>

    <!-- 荣誉称号列表 -->
    <div class="title-wall-card">
      <div class="section-header">
        <h2 class="section-title">
          <el-icon><Medal /></el-icon>
          我的荣誉称号
        </h2>
        <span class="badge-count">{{ ownedTitles.length }} 个</span>
      </div>

      <div class="title-pills" v-if="ownedTitles.length > 0">
        <div
          v-for="title in ownedTitles"
          :key="title.id"
          class="title-pill"
          :class="{ active: title.isEquipped }"
          @click="handleTitleEquip(title)"
        >
          <div class="pill-main">
            <span class="pill-icon">{{ title.icon }}</span>
            <span class="pill-name">{{ title.name }}</span>
            <span class="pill-level">Lv.{{ title.level }}</span>
          </div>
          <div class="pill-status">
            <el-icon v-if="title.isEquipped"><Select /></el-icon>
            <span>{{ title.isEquipped ? '已佩戴' : '点击佩戴' }}</span>
          </div>
        </div>
      </div>
      
      <div class="empty-hint" v-else>
        <el-icon :size="48" color="#c0c4cc"><Medal /></el-icon>
        <p>暂无称号，快去积分商城解锁吧！</p>
      </div>
    </div>

    <!-- 勋章墙 -->
    <div class="badge-wall-card">
      <div class="section-header">
        <h2 class="section-title">
          <el-icon><Trophy /></el-icon>
          我的荣誉勋章
        </h2>
        <span class="badge-count">{{ earnedBadges.length }} 枚</span>
      </div>
      
      <div class="badge-grid" v-if="earnedBadges.length > 0">
        <div 
          v-for="badge in earnedBadges" 
          :key="badge.id" 
          class="badge-item"
          :class="{ equipped: badge.isEquipped }"
          @click="handleBadgeClick(badge)"
        >
          <div class="badge-icon-wrapper">
            <span class="badge-icon">{{ badge.icon }}</span>
            <div class="equipped-badge" v-if="badge.isEquipped">
              <el-icon><Select /></el-icon>
            </div>
          </div>
          <div class="badge-name">{{ badge.name }}</div>
          <div class="badge-type">{{ getBadgeTypeName(badge.type) }}</div>
          <div class="equipped-label" v-if="badge.isEquipped">佩戴中</div>
        </div>
      </div>
      
      <div class="empty-hint" v-else>
        <el-icon :size="64" color="#c0c4cc"><Trophy /></el-icon>
        <p>暂无勋章，快去完成打卡任务吧！</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useGameStore } from '@/stores/game'
import { 
  Edit, 
  Trophy, 
  Medal,
  Select
} from '@element-plus/icons-vue'
import { getProfileData } from '@/api/profile'
import { toggleEquipTitle } from '@/api/mall'
import { toggleEquipBadge } from '@/api/mall'

const userStore = useUserStore()
const gameStore = useGameStore()
const loading = ref(false)

// 用户基础信息
const userInfo = reactive({
  name: userStore.userInfo.name || '',
  nickname: '',
  studentId: userStore.userInfo.studentId || '',
  avatar: userStore.userInfo.avatar || '',
  stats: {
    carbon: '0 kg',
    rank: '0%'
  }
})

// 已拥有的称号列表
const ownedTitles = reactive([])

// 已拥有的勋章列表
const earnedBadges = reactive([])

// 已佩戴的称号列表（计算属性）
const equippedTitles = computed(() => {
  return ownedTitles.filter(t => t.isEquipped)
})

// 已佩戴的勋章列表（计算属性）
const equippedBadges = computed(() => {
  return earnedBadges.filter(b => b.isEquipped)
})

// 勋章类型名称映射
const badgeTypeNames = {
  plate: '光盘系列',
  walk: '健步系列',
  ride: '骑行系列',
  general: '综合成就'
}

const getBadgeTypeName = (type) => {
  return badgeTypeNames[type] || '未知系列'
}

// 获取头像完整URL的辅助函数
const getAvatarUrl = () => {
  if (!userInfo.avatar || userInfo.avatar.trim() === '') {
    return ''
  }
  
  // 如果是完整URL，直接使用
  if (userInfo.avatar.startsWith('http')) {
    return userInfo.avatar
  }
  
  // 如果是相对路径，转换为完整URL
  if (userInfo.avatar.startsWith('/api')) {
    return `${window.location.origin}${userInfo.avatar}`
  }
  
  // 如果路径不完整，尝试补全
  return `${window.location.origin}/api${userInfo.avatar}`
}

// 加载我的荣誉页面数据
const loadProfileData = async () => {
  loading.value = true
  try {
    const res = await getProfileData()
    if (res.code === 200) {
      const data = res.data
      
      // 更新用户信息
      if (data.userProfile) {
        userInfo.name = data.userProfile.name || userStore.userInfo.name || ''
        userInfo.nickname = data.userProfile.nickname || data.userProfile.name || userStore.userInfo.name || ''
        userInfo.studentId = data.userProfile.studentId || userStore.userInfo.studentId || ''
        userInfo.avatar = data.userProfile.avatar || userStore.userInfo.avatar || ''
        userInfo.stats.carbon = `${(data.userProfile.carbonReduction || 0).toFixed(1)} kg`
        userInfo.stats.rank = `${data.userProfile.rankPercentage || 0}%`
        
        // 更新gameStore中的统计数据
        gameStore.userStats.totalCheckins = data.userProfile.totalCheckins || 0
      }
      
      // 更新称号列表
      ownedTitles.length = 0
      if (data.titles && data.titles.length > 0) {
        ownedTitles.push(...data.titles)
      }
      
      // 更新勋章列表
      earnedBadges.length = 0
      if (data.badges && data.badges.length > 0) {
        earnedBadges.push(...data.badges)
      }
    }
  } catch (error) {
    console.error('加载我的荣誉页面数据失败:', error)
  } finally {
    loading.value = false
  }
}

// 佩戴/卸下称号 (Toggle)
const handleTitleEquip = async (title) => {
  try {
    const res = await toggleEquipTitle(title.id)
    if (res.code === 200) {
      // 更新本地状态
      title.isEquipped = res.data.isEquipped
      
      if (title.isEquipped) {
        ElMessage.success({
          message: `👑 已佩戴「${title.name}」称号`,
          duration: 2000
        })
      } else {
        ElMessage.info({
          message: `已卸下「${title.name}」称号`,
          duration: 2000
        })
      }
    }
  } catch (error) {
    console.error('切换称号佩戴状态失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  }
}

// 点击勋章 - 切换佩戴状态
const handleBadgeClick = async (badge) => {
  try {
    const res = await toggleEquipBadge(badge.id)
    if (res.code === 200) {
      // 更新本地状态
      badge.isEquipped = res.data.isEquipped
      
      // 如果是同系列的其他勋章，需要更新它们的状态
      if (res.data.isEquipped) {
        earnedBadges.forEach(b => {
          if (b.type === badge.type && b.id !== badge.id) {
            b.isEquipped = false
          }
        })
      }
      
      if (badge.isEquipped) {
        ElMessage.success({
          message: `🎖️ 已佩戴「${badge.name}」勋章`,
          duration: 2000
        })
      } else {
        ElMessage.info({
          message: `已卸下「${badge.name}」勋章`,
          duration: 2000
        })
      }
    }
  } catch (error) {
    console.error('切换勋章佩戴状态失败:', error)
    // 错误消息已在 request.js 拦截器中统一处理
  }
}

// 编辑个人信息
const handleEdit = () => {
  ElMessage.info('编辑功能开发中...')
}

// 组件挂载时加载数据
onMounted(() => {
  loadProfileData()
})
</script>

<style scoped>
.profile-page {
  padding: 24px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
  animation: fadeInUp 0.6s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ==================== 身份卡片 ==================== */
.identity-card {
  position: relative;
  background: linear-gradient(135deg, #009688 0%, #00695c 100%);
  border-radius: 24px;
  padding: 40px;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: 0 12px 40px rgba(0, 105, 92, 0.3);
  animation: slideInDown 0.8s ease-out;
}

@keyframes slideInDown {
  from {
    opacity: 0;
    transform: translateY(-30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.card-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.bg-pattern {
  position: absolute;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 1px, transparent 1px);
  background-size: 40px 40px;
  animation: patternMove 20s linear infinite;
}

@keyframes patternMove {
  0% {
    transform: translate(0, 0);
  }
  100% {
    transform: translate(40px, 40px);
  }
}

.card-content {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 32px;
}

.avatar-section {
  flex-shrink: 0;
}

.avatar-wrapper {
  position: relative;
}

.user-avatar {
  background: rgba(255, 255, 255, 0.2);
  border: 4px solid rgba(255, 255, 255, 0.3);
  font-size: 48px;
  font-weight: 700;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.avatar-ring {
  position: absolute;
  inset: -8px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  animation: pulseRing 2s ease-in-out infinite;
}

@keyframes pulseRing {
  0%, 100% {
    transform: scale(1);
    opacity: 0.8;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.4;
  }
}

.info-section {
  flex: 1;
  color: #ffffff;
}

.user-name {
  font-size: 36px;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 12px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* ==================== 佩戴的称号 (Mini Tags) ==================== */
.equipped-titles-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.mini-title-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 10px;
  background: linear-gradient(135deg, #ffd54f 0%, #ffb300 100%);
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(255, 179, 0, 0.4),
              0 0 12px rgba(255, 179, 0, 0.2);
  animation: tagGlow 2s ease-in-out infinite;
}

.mini-title-tag.empty {
  background: rgba(255, 255, 255, 0.2);
  box-shadow: none;
  animation: none;
}

@keyframes tagGlow {
  0%, 100% {
    box-shadow: 0 2px 8px rgba(255, 179, 0, 0.4),
                0 0 12px rgba(255, 179, 0, 0.2);
  }
  50% {
    box-shadow: 0 2px 12px rgba(255, 179, 0, 0.6),
                0 0 20px rgba(255, 179, 0, 0.3);
  }
}

.mini-title-tag .tag-icon {
  font-size: 12px;
  line-height: 1;
}

.mini-title-tag .tag-name {
  font-size: 12px;
  font-weight: 600;
  color: #5d4037;
  line-height: 1;
}

.mini-title-tag.empty .tag-name {
  color: rgba(255, 255, 255, 0.8);
}

/* ==================== 佩戴的勋章 (Capsule Tag Style) ==================== */
.equipped-badges-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.mini-badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 20px;
  box-shadow: 0 3px 10px rgba(102, 126, 234, 0.4),
              0 0 15px rgba(118, 75, 162, 0.2);
  cursor: pointer;
  transition: all 0.25s ease;
  white-space: nowrap;
  animation: badgeTagGlow 2.5s ease-in-out infinite;
}

.mini-badge-tag:hover {
  transform: translateY(-2px);
  box-shadow: 0 5px 15px rgba(102, 126, 234, 0.5),
              0 0 20px rgba(118, 75, 162, 0.3);
}

.mini-badge-tag.empty {
  background: rgba(255, 255, 255, 0.2);
  box-shadow: none;
  cursor: default;
  animation: none;
}

.mini-badge-tag.empty:hover {
  transform: none;
  box-shadow: none;
}

@keyframes badgeTagGlow {
  0%, 100% {
    box-shadow: 0 3px 10px rgba(102, 126, 234, 0.4),
                0 0 15px rgba(118, 75, 162, 0.2);
  }
  50% {
    box-shadow: 0 3px 14px rgba(102, 126, 234, 0.55),
                0 0 22px rgba(118, 75, 162, 0.3);
  }
}

.mini-badge-tag .badge-tag-icon {
  font-size: 13px;
  line-height: 1;
}

.mini-badge-tag .badge-tag-name {
  font-size: 12px;
  font-weight: 600;
  color: #ffffff;
  line-height: 1;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.mini-badge-tag.empty .badge-tag-name {
  color: rgba(255, 255, 255, 0.7);
  text-shadow: none;
}

/* 统计数据行 */
.stats-row {
  display: flex;
  align-items: center;
  gap: 24px;
  background: rgba(255, 255, 255, 0.15);
  padding: 16px 24px;
  border-radius: 16px;
  backdrop-filter: blur(10px);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-icon {
  font-size: 20px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
}

.stat-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
}

.stat-divider {
  width: 1px;
  height: 32px;
  background: rgba(255, 255, 255, 0.3);
}

.action-section {
  flex-shrink: 0;
}

/* ==================== 称号墙 ==================== */
.title-wall-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
}

.title-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.title-pill {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  min-width: 180px;
  border-radius: 12px;
  border: 2px solid #e0e0e0;
  background: #f9fafb;
  color: #303133;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

.title-pill:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.08);
  border-color: #26a69a;
}

/* 已佩戴状态 */
.title-pill.active {
  border: 2px solid #ffb300;
  background: linear-gradient(135deg, #ffd54f 0%, #ffb300 50%, #ff8f00 100%);
  color: #5d4037;
  box-shadow: 0 6px 18px rgba(255, 179, 0, 0.35), 0 0 20px rgba(255, 179, 0, 0.25);
}

.title-pill .pill-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.title-pill .pill-icon {
  font-size: 20px;
}

.title-pill .pill-level {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.06);
}

.title-pill.active .pill-level {
  background: rgba(255, 255, 255, 0.35);
}

/* 状态指示 */
.pill-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #909399;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.04);
  border-radius: 6px;
  transition: all 0.2s;
}

.title-pill.active .pill-status {
  background: rgba(255, 255, 255, 0.3);
  color: #5d4037;
  font-weight: 600;
}

.title-pill:not(.active):hover .pill-status {
  background: rgba(38, 166, 154, 0.1);
  color: #26a69a;
}

/* ==================== 勋章墙 ==================== */
.badge-wall-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 32px;
  margin-bottom: 24px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
  animation: fadeInUp 0.8s ease-out 0.2s both;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #f0f0f0;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  margin: 0;
}

.section-title .el-icon {
  color: #26a69a;
}

.badge-count {
  font-size: 14px;
  color: #909399;
  background: #f5f5f5;
  padding: 6px 16px;
  border-radius: 20px;
}

.badge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 20px;
}

.badge-item {
  position: relative;
  background: linear-gradient(135deg, #f9fafb 0%, #ffffff 100%);
  border: 2px solid #f0f0f0;
  border-radius: 16px;
  padding: 24px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  animation: fadeInUp 0.6s ease-out both;
}

.badge-item:nth-child(1) { animation-delay: 0.1s; }
.badge-item:nth-child(2) { animation-delay: 0.15s; }
.badge-item:nth-child(3) { animation-delay: 0.2s; }
.badge-item:nth-child(4) { animation-delay: 0.25s; }
.badge-item:nth-child(5) { animation-delay: 0.3s; }
.badge-item:nth-child(6) { animation-delay: 0.35s; }

.badge-item:hover {
  transform: translateY(-8px) scale(1.05);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.12);
  border-color: #26a69a;
}

/* 佩戴中的勋章 - 金色边框高亮 */
.badge-item.equipped {
  border-color: #ffb300;
  border-width: 3px;
  background: linear-gradient(135deg, #fff8e1 0%, #fffde7 100%);
  box-shadow: 0 4px 20px rgba(255, 179, 0, 0.3),
              0 0 0 4px rgba(255, 179, 0, 0.1);
}

.badge-icon-wrapper {
  position: relative;
  margin-bottom: 12px;
  display: inline-block;
}

.badge-icon {
  font-size: 56px;
  display: block;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.1));
}

.equipped-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, #ffb300 0%, #ff8f00 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(255, 179, 0, 0.4);
  border: 2px solid #ffffff;
}

.badge-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.badge-type {
  font-size: 12px;
  color: #909399;
}

.equipped-label {
  position: absolute;
  top: 8px;
  right: 8px;
  background: linear-gradient(135deg, #ffb300 0%, #ff8f00 100%);
  color: #5d4037;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(255, 179, 0, 0.3);
}

.empty-hint {
  text-align: center;
  padding: 60px 0;
  color: #909399;
}

.empty-hint p {
  margin-top: 16px;
  font-size: 14px;
}

/* 响应式 */
@media (max-width: 768px) {
  .card-content {
    flex-direction: column;
    text-align: center;
  }
  
  .equipped-titles-row,
  .equipped-badges-row {
    justify-content: center;
  }
  
  .stats-row {
    flex-direction: column;
    gap: 12px;
  }
  
  .stat-divider {
    display: none;
  }
  
  .badge-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .title-pills {
    justify-content: center;
  }
  
  .title-pill {
    min-width: auto;
    flex-direction: column;
    gap: 8px;
  }
}
</style>
