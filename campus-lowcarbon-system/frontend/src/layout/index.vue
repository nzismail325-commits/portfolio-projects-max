<template>
  <el-container class="layout-container">
    <!-- 顶部导航栏 -->
    <el-header class="layout-header">
      <div class="header-left">
        <div class="logo" @click="goHome">
          <el-icon :size="32" color="#ffffff"><Sunny /></el-icon>
          <span class="logo-text">智能低碳行为管理系统</span>
        </div>
      </div>
      <div class="header-right">
        <!-- 消息通知图标 -->
        <div class="notification-icon" @click="goToNotifications">
          <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
            <el-icon :size="22" color="#ffffff" class="notification-bell">
              <Message />
            </el-icon>
          </el-badge>
        </div>
        
        <div class="user-info">
          <el-avatar :size="36" class="user-avatar">
            {{ userStore.userInfo.name?.charAt(0) || 'U' }}
          </el-avatar>
          <span class="user-name">{{ userStore.userInfo.name || '用户' }}</span>
          <el-tag
            :type="userStore.role === 'admin' ? 'warning' : 'success'"
            effect="light"
            size="small"
          >
            {{ userStore.role === 'admin' ? '管理员' : '学生' }}
          </el-tag>
        </div>
      </div>
    </el-header>

    <el-container class="main-container">
      <!-- 侧边栏导航 -->
      <el-aside :width="isCollapse ? '64px' : '220px'" class="layout-aside">
        <div class="collapse-btn" @click="toggleCollapse">
          <el-icon :size="20">
            <component :is="isCollapse ? 'Expand' : 'Fold'" />
          </el-icon>
        </div>
        
        <el-menu
          :default-active="$route.path"
          :collapse="isCollapse"
          :collapse-transition="false"
          unique-opened
          class="side-menu"
          router
        >
          <!-- 管理员菜单 -->
          <template v-if="userStore.role === 'admin'">
            <el-menu-item index="/dashboard">
              <el-icon><DataLine /></el-icon>
              <template #title>全局看板</template>
            </el-menu-item>
            <el-menu-item index="/rules">
              <el-icon><WarnTriangleFilled /></el-icon>
              <template #title>用户风控</template>
            </el-menu-item>
            <el-menu-item index="/review">
              <el-icon><Document /></el-icon>
              <template #title>异常审核</template>
            </el-menu-item>
            <el-sub-menu index="/checkin-manage">
              <template #title>
                <el-icon><Setting /></el-icon>
                <span>打卡管理</span>
              </template>
              <el-menu-item index="/checkin-manage/walk">低碳健步走</el-menu-item>
              <el-menu-item index="/checkin-manage/ride">绿色骑行</el-menu-item>
              <el-menu-item index="/checkin-manage/plate">光盘行动</el-menu-item>
              <el-menu-item index="/checkin-manage/transit">公共交通</el-menu-item>
            </el-sub-menu>
            <el-sub-menu index="/rank">
              <template #title>
                <el-icon><TrophyBase /></el-icon>
                <span>低碳风云榜</span>
              </template>
              <el-menu-item index="/rank/points">积分总榜</el-menu-item>
              <el-menu-item index="/rank/badges">勋章达人榜</el-menu-item>
              <el-menu-item index="/rank/titles">称号荣耀榜</el-menu-item>
              <el-menu-item index="/rank/checkins">勤奋打卡榜</el-menu-item>
            </el-sub-menu>
          </template>

          <!-- 学生菜单 -->
          <template v-else>
            <!-- 1. 我的首页 -->
            <el-menu-item index="/dashboard">
              <el-icon><HomeFilled /></el-icon>
              <template #title>我的首页</template>
            </el-menu-item>
            <!-- 2. 数据统计 -->
            <el-menu-item index="/personal-stats">
              <el-icon><DataAnalysis /></el-icon>
              <template #title>数据统计</template>
            </el-menu-item>
            <!-- 3. 智能顾问 -->
            <el-menu-item index="/advisor">
              <el-icon><ChatDotRound /></el-icon>
              <template #title>智能顾问</template>
            </el-menu-item>
            <!-- 3. 低碳打卡 -->
            <el-sub-menu index="/checkin">
              <template #title>
                <el-icon><Camera /></el-icon>
                <span>低碳打卡</span>
              </template>
              <el-menu-item index="/checkin/walk">低碳健步走</el-menu-item>
              <el-menu-item index="/checkin/ride">绿色骑行</el-menu-item>
              <el-menu-item index="/checkin/plate">光盘行动</el-menu-item>
              <el-menu-item index="/checkin/transit">公共交通</el-menu-item>
            </el-sub-menu>
            <!-- 4. 装扮商城 -->
            <el-sub-menu index="/mall">
              <template #title>
                <el-icon><Goods /></el-icon>
                <span>装扮商城</span>
              </template>
              <el-menu-item index="/mall/titles">
                <span class="menu-item-text">荣誉称号</span>
                <el-tag
                  v-if="gameStore.canUpgradeTitlesCount > 0"
                  type="danger"
                  effect="dark"
                  size="small"
                  round
                  class="menu-badge"
                >
                  {{ gameStore.canUpgradeTitlesCount }}
                </el-tag>
              </el-menu-item>
              <el-menu-item index="/mall/badges">
                <span class="menu-item-text">环保勋章</span>
                <el-tag
                  v-if="gameStore.canUnlockBadgesCount > 0"
                  type="danger"
                  effect="dark"
                  size="small"
                  round
                  class="menu-badge"
                >
                  {{ gameStore.canUnlockBadgesCount }}
                </el-tag>
              </el-menu-item>
            </el-sub-menu>
            <!-- 5. 低碳风云榜 -->
            <el-sub-menu index="/rank">
              <template #title>
                <el-icon><TrophyBase /></el-icon>
                <span>低碳风云榜</span>
              </template>
              <el-menu-item index="/rank/points">积分总榜</el-menu-item>
              <el-menu-item index="/rank/badges">勋章达人榜</el-menu-item>
              <el-menu-item index="/rank/titles">称号荣耀榜</el-menu-item>
              <el-menu-item index="/rank/checkins">勤奋打卡榜</el-menu-item>
            </el-sub-menu>
            <!-- 6. 我的荣誉 -->
            <el-menu-item index="/profile">
              <el-icon><TrophyBase /></el-icon>
              <template #title>我的荣誉</template>
            </el-menu-item>
          </template>

          <!-- 账号管理 - 所有角色可见 -->
          <el-sub-menu index="/account">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>账号管理</span>
            </template>
            <el-menu-item index="/user/info">
              <el-icon><Postcard /></el-icon>
              <span>个人信息</span>
            </el-menu-item>
            <el-menu-item @click="handleLogout">
              <el-icon><SwitchButton /></el-icon>
              <span>退出登录</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <!-- 主内容区 - 路由出口 -->
      <el-main class="layout-main">
        <router-view :key="$route.fullPath" />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, onMounted, onUnmounted, provide } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useGameStore } from '@/stores/game'
import { useCheckinStore } from '@/stores/checkin'
import { getUserAssets, getUserStats, getAllTitles, getAllBadges } from '@/api/mall'
import { getUnreadNotificationCount } from '@/api/notification'
import { 
  Sunny,
  Setting,
  SwitchButton,
  Expand,
  Fold,
  DataLine,
  Document,
  HomeFilled,
  Camera,
  Goods,
  ChatDotRound,
  TrophyBase,
  Postcard,
  WarnTriangleFilled,
  Message,
  DataAnalysis
} from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()
const gameStore = useGameStore()
const checkinStore = useCheckinStore()

// 加载商城数据到 gameStore（用于侧边栏红点提示）
const loadMallDataToStore = async () => {
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
    // 静默失败，不影响应用启动
    console.debug('加载商城数据失败（不影响应用启动）:', error)
  }
}

// 应用启动时加载场景配置和商城数据
onMounted(async () => {
  try {
    await checkinStore.loadAllConfigs()
  } catch (error) {
    console.error('加载场景配置失败:', error)
  }
  
  // 加载商城数据（用于侧边栏红点提示）
  await loadMallDataToStore()
  
  // 加载未读消息数量
  await loadUnreadCount()
  
  // 每10秒轮询一次未读消息数量
  notificationTimer = setInterval(() => {
    loadUnreadCount()
  }, 10000)
})

// 组件卸载时清除定时器
onUnmounted(() => {
  if (notificationTimer) {
    clearInterval(notificationTimer)
  }
})

// 侧边栏折叠状态
const isCollapse = ref(false)

// 未读消息数量
const unreadCount = ref(0)

// 消息轮询定时器
let notificationTimer = null

// 加载未读消息数量
const loadUnreadCount = async () => {
  try {
    const res = await getUnreadNotificationCount()
    if (res.code === 200 && res.data) {
      unreadCount.value = res.data.unreadCount || 0
    } else {
      unreadCount.value = 0
    }
  } catch (error) {
    console.error('加载未读消息数量失败:', error)
    unreadCount.value = 0
  }
}

// 提供给子组件使用的更新未读数量方法
provide('updateUnreadCount', loadUnreadCount)

// 跳转到消息页面
const goToNotifications = () => {
  router.push('/notifications')
}

// 切换侧边栏折叠
const toggleCollapse = () => {
  isCollapse.value = !isCollapse.value
}

// 点击 Logo 回首页
const goHome = () => {
  router.push('/dashboard')
}

// 退出登录
const handleLogout = () => {
  ElMessageBox.confirm('确定要退出登录吗？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    userStore.logout()
    ElMessage.success('退出成功')
    router.push('/login')
  }).catch(() => {})
}
</script>

<style scoped>
.layout-container {
  width: 100%;
  height: 100vh;
  background: #f0f2f5;
}

/* 顶部导航栏 */
.layout-header {
  height: 60px;
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  position: relative;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.logo:hover {
  opacity: 0.9;
}

.logo-text {
  font-size: 20px;
  font-weight: 600;
  color: #ffffff;
  letter-spacing: 1px;
}

.header-right {
  display: flex;
  align-items: center;
}

.notification-icon {
  margin-right: 16px;
  cursor: pointer;
  padding: 8px;
  border-radius: 50%;
  transition: background-color 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.notification-icon:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.notification-bell {
  transition: transform 0.2s;
}

.notification-icon:hover .notification-bell {
  transform: scale(1.1);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
}

.user-avatar {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
  font-weight: 600;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: #ffffff;
}

/* 主容器 */
.main-container {
  height: calc(100vh - 60px);
}

/* 侧边栏 */
.layout-aside {
  background: #ffffff;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.05);
  transition: width 0.3s;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.collapse-btn {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #606266;
  border-bottom: 1px solid #f0f0f0;
  transition: all 0.2s;
}

.collapse-btn:hover {
  color: #26a69a;
  background: #f5f7fa;
}

.side-menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 隐藏侧边栏滚动条 - Webkit 浏览器 */
.side-menu::-webkit-scrollbar {
  width: 0;
  background: transparent;
}

/* 隐藏侧边栏滚动条 - Firefox */
.side-menu {
  scrollbar-width: none;
}

.side-menu:not(.el-menu--collapse) {
  width: 220px;
}

.side-menu .el-menu-item {
  height: 50px;
  line-height: 50px;
  margin: 4px 8px;
  border-radius: 8px;
}

.side-menu .el-menu-item:hover {
  background: #f0f9f8;
}

.side-menu .el-menu-item.is-active {
  background: linear-gradient(135deg, #26a69a 0%, #00897b 100%);
  color: #ffffff;
}

.side-menu .el-menu-item.is-active .el-icon {
  color: #ffffff;
}

/* 主内容区 */
.layout-main {
  padding: 0;
  overflow-y: auto;
  background: #f0f2f5;
}

/* 子菜单样式 */
.side-menu :deep(.el-sub-menu__title) {
  height: 50px;
  line-height: 50px;
  margin: 4px 8px;
  border-radius: 8px;
}

.side-menu :deep(.el-sub-menu__title:hover) {
  background: #f0f9f8;
}

.side-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: #26a69a;
}

.side-menu :deep(.el-sub-menu .el-menu-item) {
  height: 44px;
  line-height: 44px;
  min-width: auto;
  padding-left: 48px !important;
  margin: 2px 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* 子菜单项文本 */
.menu-item-text {
  flex: 1;
}

/* 侧边栏红点标记 */
.menu-badge {
  transform: scale(0.8);
  margin-left: 8px;
  padding: 0 6px;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  font-size: 11px;
}

.side-menu :deep(.el-sub-menu__icon-arrow) {
  right: 16px;
}

/* Element Plus 样式覆盖 */
:deep(.el-menu-item .el-icon) {
  font-size: 18px;
  margin-right: 8px;
}

:deep(.el-sub-menu__title .el-icon) {
  font-size: 18px;
  margin-right: 8px;
}

/* 响应式 */
@media (max-width: 768px) {
  .logo-text {
    display: none;
  }
  
  .user-name {
    display: none;
  }
}
</style>

