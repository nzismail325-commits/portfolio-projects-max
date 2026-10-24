<template>
  <div class="love-garden-page">
    <StarrySky />
    <header class="garden-header">
      <router-link to="/home" class="back-btn">
        <ArrowLeft :size="24" />
      </router-link>
      <h1 class="garden-title">爱情花园</h1>
      <div class="garden-level">Lv.{{ treeData.level }}</div>
    </header>

    <div class="partner-status-bar">
      <div class="partner-info">
        <span class="partner-name">{{ partnerName }}</span>
        <span :class="['partner-online', { online: partnerOnline }]">
          {{ partnerOnline ? '在线' : '离线' }}
        </span>
      </div>
      <div class="partner-actions">
        <span class="actions-today">今日完成: {{ partnerActionsCount }}/5</span>
      </div>
      <button class="mobile-stats-btn-inline mobile-only" @click="toggleStatsPanel">
        <ChartColumn :size="20" />
      </button>
    </div>

    <div class="garden-container">
      <div class="tree-stats-card">
        <div class="level-progress">
          <div class="level-info">
            <span class="current-level">Lv.{{ treeData.level }}</span>
            <span class="next-level">Lv.{{ treeData.level + 1 }}</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: levelProgressPercent + '%' }"></div>
          </div>
          <div class="exp-text">{{ treeData.experience }} / {{ nextLevelExp }} XP</div>
        </div>

        <div class="tree-stats-content">
          <div class="tree-display-area">
            <LoveTree
              :level="treeData.level"
              :health="treeData.health"
              :care="treeData.care"
              :companion="treeData.companion"
              :love="treeData.love"
              :sweetness="treeData.sweetness"
            />
          </div>

          <div class="stats-panel desktop-only">
            <div class="stats-grid">
              <div :class="['stat-item', statClass('health')]">
                <div class="stat-icon">💧</div>
                <div class="stat-info">
                  <div class="stat-label">健康度</div>
                  <div class="stat-value">{{ round(treeData.health) }}/100</div>
                </div>
                <div class="stat-bar">
                  <div class="stat-fill" :style="{ width: round(treeData.health) + '%' }"></div>
                </div>
              </div>
              <div :class="['stat-item', statClass('care')]">
                <div class="stat-icon">🌱</div>
                <div class="stat-info">
                  <div class="stat-label">关怀值</div>
                  <div class="stat-value">{{ round(treeData.care) }}/100</div>
                </div>
                <div class="stat-bar">
                  <div class="stat-fill" :style="{ width: round(treeData.care) + '%' }"></div>
                </div>
              </div>
              <div :class="['stat-item', statClass('companion')]">
                <div class="stat-icon">🦋</div>
                <div class="stat-info">
                  <div class="stat-label">陪伴值</div>
                  <div class="stat-value">{{ round(treeData.companion) }}/100</div>
                </div>
                <div class="stat-bar">
                  <div class="stat-fill" :style="{ width: round(treeData.companion) + '%' }"></div>
                </div>
              </div>
              <div :class="['stat-item', statClass('love')]">
                <div class="stat-icon">💖</div>
                <div class="stat-info">
                  <div class="stat-label">爱心值</div>
                  <div class="stat-value">{{ round(treeData.love) }}/100</div>
                </div>
                <div class="stat-bar">
                  <div class="stat-fill" :style="{ width: round(treeData.love) + '%' }"></div>
                </div>
              </div>
              <div :class="['stat-item', statClass('sweetness')]">
                <div class="stat-icon">✨</div>
                <div class="stat-info">
                  <div class="stat-label">甜蜜值</div>
                  <div class="stat-value">{{ round(treeData.sweetness) }}/100</div>
                </div>
                <div class="stat-bar">
                  <div class="stat-fill" :style="{ width: round(treeData.sweetness) + '%' }"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="actions-panel desktop-only">
        <div class="actions-grid">
          <ActionButton
            icon="💧"
            name="浇水"
            description="提升健康度"
            :disabled="false"
            :completed="todayActions.water"
            :has-online-bonus="hasOnlineBonus"
            @click="performAction('water')"
          />
          <ActionButton
            icon="🌱"
            name="施肥"
            description="提升关怀值"
            :disabled="false"
            :completed="todayActions.fertilize"
            :has-online-bonus="hasOnlineBonus"
            @click="performAction('fertilize')"
          />
          <ActionButton
            icon="🌿"
            name="除草"
            description="提升陪伴值"
            :disabled="false"
            :completed="todayActions.weed"
            :has-online-bonus="hasOnlineBonus"
            @click="performAction('weed')"
          />
          <ActionButton
            icon="💖"
            name="许愿"
            description="提升爱心值"
            :disabled="false"
            :completed="todayActions.wish"
            :has-online-bonus="hasOnlineBonus"
            @click="performAction('wish')"
          />
          <ActionButton
            icon="📸"
            name="合影"
            description="提升甜蜜值"
            :disabled="false"
            :completed="todayActions.photo"
            :has-online-bonus="hasOnlineBonus"
            @click="performAction('photo')"
          />
        </div>
      </div>

      <div class="mobile-actions-panel mobile-only">
        <div class="mobile-actions-grid">
          <ActionButton
            icon="💧"
            name="浇水"
            description="提升健康度"
            :disabled="false"
            :completed="todayActions.water"
            :has-online-bonus="hasOnlineBonus"
            compact
            @click="performAction('water')"
          />
          <ActionButton
            icon="🌱"
            name="施肥"
            description="提升关怀值"
            :disabled="false"
            :completed="todayActions.fertilize"
            :has-online-bonus="hasOnlineBonus"
            compact
            @click="performAction('fertilize')"
          />
          <ActionButton
            icon="🌿"
            name="除草"
            description="提升陪伴值"
            :disabled="false"
            :completed="todayActions.weed"
            :has-online-bonus="hasOnlineBonus"
            compact
            @click="performAction('weed')"
          />
          <ActionButton
            icon="💖"
            name="许愿"
            description="提升爱心值"
            :disabled="false"
            :completed="todayActions.wish"
            :has-online-bonus="hasOnlineBonus"
            compact
            @click="performAction('wish')"
          />
          <ActionButton
            icon="📸"
            name="合影"
            description="提升甜蜜值"
            :disabled="false"
            :completed="todayActions.photo"
            :has-online-bonus="hasOnlineBonus"
            compact
            @click="performAction('photo')"
          />
        </div>
      </div>
    </div>

    <transition name="slide-from-right">
      <div v-if="showStatsPanel" class="stats-panel-overlay mobile-only" @click="closeStatsPanel">
        <div class="stats-panel-sidebar" @click.stop>
          <div class="panel-header">
            <h3>数值详情</h3>
            <button @click="closeStatsPanel" class="close-panel-btn">
              <X :size="24" />
            </button>
          </div>
          <div class="panel-content">
            <div class="mobile-stat-item">
              <div class="mobile-stat-icon">💧</div>
              <div class="mobile-stat-info">
                <div class="mobile-stat-label">健康度</div>
                <div class="mobile-stat-value">{{ round(treeData.health) }}/100</div>
                <div class="mobile-stat-bar">
                  <div class="mobile-stat-fill" :style="{ width: round(treeData.health) + '%' }"></div>
                </div>
              </div>
            </div>
            <div class="mobile-stat-item">
              <div class="mobile-stat-icon">🌱</div>
              <div class="mobile-stat-info">
                <div class="mobile-stat-label">关怀值</div>
                <div class="mobile-stat-value">{{ round(treeData.care) }}/100</div>
                <div class="mobile-stat-bar">
                  <div class="mobile-stat-fill" :style="{ width: round(treeData.care) + '%' }"></div>
                </div>
              </div>
            </div>
            <div class="mobile-stat-item">
              <div class="mobile-stat-icon">🦋</div>
              <div class="mobile-stat-info">
                <div class="mobile-stat-label">陪伴值</div>
                <div class="mobile-stat-value">{{ round(treeData.companion) }}/100</div>
                <div class="mobile-stat-bar">
                  <div class="mobile-stat-fill" :style="{ width: round(treeData.companion) + '%' }"></div>
                </div>
              </div>
            </div>
            <div class="mobile-stat-item">
              <div class="mobile-stat-icon">💖</div>
              <div class="mobile-stat-info">
                <div class="mobile-stat-label">爱心值</div>
                <div class="mobile-stat-value">{{ round(treeData.love) }}/100</div>
                <div class="mobile-stat-bar">
                  <div class="mobile-stat-fill" :style="{ width: round(treeData.love) + '%' }"></div>
                </div>
              </div>
            </div>
            <div class="mobile-stat-item">
              <div class="mobile-stat-icon">✨</div>
              <div class="mobile-stat-info">
                <div class="mobile-stat-label">甜蜜值</div>
                <div class="mobile-stat-value">{{ round(treeData.sweetness) }}/100</div>
                <div class="mobile-stat-bar">
                  <div class="mobile-stat-fill" :style="{ width: round(treeData.sweetness) + '%' }"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ArrowLeft, X, ChartColumn } from 'lucide-vue-next'
import apiClient from '../api'
import socketService from '../services/socket'
import { getErrorMessage } from '../utils/errors'
import LoveTree from '../components/LoveTree.vue'
import ActionButton from '../components/ActionButton.vue'
import StarrySky from '../components/StarrySky.vue'

const treeData = reactive({
  level: 1,
  experience: 0,
  health: 10,
  care: 0,
  companion: 0,
  love: 0,
  sweetness: 0
})

const todayActions = reactive({
  water: false,
  fertilize: false,
  weed: false,
  wish: false,
  photo: false
})

const partnerName = computed(() => (currentUserId.value === 1 ? '男朋友' : '女朋友'))
const partnerOnline = ref(false)
const currentUserId = ref(null)
const partnerActionsCount = ref(0)
const LEVEL_THRESHOLDS = [0, 2500, 4500, 6600, 8000]

const nextLevelExp = computed(() =>
  treeData.level >= 5 ? LEVEL_THRESHOLDS[4] : LEVEL_THRESHOLDS[treeData.level]
)

const levelProgressPercent = computed(() => {
  if (treeData.level >= 5) return 100
  const current = LEVEL_THRESHOLDS[treeData.level - 1]
  const next = LEVEL_THRESHOLDS[treeData.level]
  const gained = treeData.experience - current
  const needed = next - current
  return Math.min(100, (gained / needed) * 100)
})

const statClass = (key) => {
  const value = treeData[key]
  if (value < 20) return 'stat-low'
  if (value < 40) return 'stat-medium'
  if (value < 80) return 'stat-high'
  return 'stat-max'
}

const round = (value) => Math.round(value)

const hasOnlineBonus = computed(() => partnerOnline.value)

const actionNames = {
  water: '浇水',
  fertilize: '施肥',
  weed: '除草',
  wish: '许愿',
  photo: '合影'
}

const performAction = async (action) => {
  try {
    const response = await apiClient.post('/api/garden/action', {
      action,
      hasOnlineBonus: hasOnlineBonus.value
    })
    if (response.data.success) {
      todayActions[action] = true
      Object.assign(treeData, response.data.treeData)
      let message = `${actionNames[action]}完成！`
      if (hasOnlineBonus.value) message += ' (获得同时在线加成)'
      if (response.data.levelUp) {
        message += ` 🎉 恭喜升级到 Lv.${response.data.treeData.level}！`
      }
      window.$toast?.success(message)
      if (response.data.levelUp) celebrateLevelUp()
    }
  } catch (err) {
    console.error('执行操作失败:', err)
    window.$toast?.error(getErrorMessage(err, '操作失败，请稍后重试'))
  }
}

const celebrateLevelUp = () => {}

const toggleStatsPanel = () => {
  showStatsPanel.value = !showStatsPanel.value
}

const showStatsPanel = ref(false)

const closeStatsPanel = () => {
  showStatsPanel.value = false
}

const checkDailySettlement = async () => {
  try {
    const response = await apiClient.get('/api/garden/check-settlement')
    if (response.data && response.data.success && response.data.settlement_executed) {
      console.log('执行了每日结算:', response.data)
      if (response.data.treeData) Object.assign(treeData, response.data.treeData)
      let message = '每日结算已完成'
      if (response.data.totalPenaltyExp > 0) {
        message += `，经验惩罚: ${response.data.totalPenaltyExp}`
      }
      window.$toast?.warning(message)
    }
  } catch (err) {
    console.error('检查每日结算失败:', err)
  }
}

const loadGardenData = async (initial = false) => {
  try {
    const response = await apiClient.get('/api/garden/data')
    if (response.data && response.data.success) {
      Object.assign(treeData, response.data.treeData)
      Object.assign(todayActions, response.data.todayActions)
      partnerActionsCount.value = response.data.partnerActionsCount
      currentUserId.value = response.data.currentUserId
    }
  } catch (err) {
    console.error('加载花园数据失败:', err)
    window.$toast?.error(getErrorMessage(err, '加载数据失败'))
  }
}

const onPartnerGardenAction = (data) => {
  if (data.treeData) Object.assign(treeData, data.treeData)
  partnerActionsCount.value += 1
  let message = `${data.userId === 1 ? '女朋友' : '男朋友'}完成了${actionNames[data.action]}`
  if (data.levelUp) {
    message += ` 🎉 爱情树升级到 Lv.${data.treeData.level}！`
  }
  window.$toast?.info(message)
}

const onPartnerGardenStatus = (data) => {
  if (currentUserId.value && data.user_id !== currentUserId.value) {
    partnerOnline.value = data.status === 'online'
    console.log('伙伴花园状态更新:', data)
  }
}

const onGardenSettlement = (data) => {
  console.log('收到每日结算通知:', data)
  if (data.treeData) Object.assign(treeData, data.treeData)
  let message = '每日结算已完成'
  if (data.totalPenaltyExp > 0) {
    message += `，经验惩罚: ${data.totalPenaltyExp}`
  }
  window.$toast?.warning(message)
  loadGardenData()
}

const handleSocketReconnected = () => {
  if (!currentUserId.value) return
  console.log('花园页面侦测到 socket 重连成功，正在重新同步状态...')
  socketService.updateGardenStatus('online')
}

const handleVisibilityChange = () => {
  if (!currentUserId.value || !socketService.socket.connected) return
  socketService.updateGardenStatus(document.visibilityState === 'visible' ? 'online' : 'offline')
}

onMounted(async () => {
  await checkDailySettlement()
  await loadGardenData(true)
  if (currentUserId.value) {
    socketService.on('partner_garden_action', onPartnerGardenAction)
    socketService.on('partner_garden_status', onPartnerGardenStatus)
    socketService.on('garden_settlement', onGardenSettlement)
    window.addEventListener('socket-reconnected', handleSocketReconnected)
    window.addEventListener('visibilitychange', handleVisibilityChange)
    if (!socketService.socket.connected) {
      try {
        await socketService.connect()
      } catch (err) {
        console.error('花园页面连接失败:', err)
        window.$toast?.error('连接失败，请刷新页面重试')
        return
      }
    }
    socketService.joinRoom(currentUserId.value)
    socketService.enterGarden(currentUserId.value)
  }
})

onBeforeUnmount(() => {
  if (currentUserId.value) {
    socketService.leaveGarden()
    socketService.off('partner_garden_action', onPartnerGardenAction)
    socketService.off('partner_garden_status', onPartnerGardenStatus)
    socketService.off('garden_settlement', onGardenSettlement)
    window.removeEventListener('socket-reconnected', handleSocketReconnected)
    window.removeEventListener('visibilitychange', handleVisibilityChange)
  }
})
</script>

<style scoped>
.love-garden-page {
  min-height: 100vh;
  position: relative;
  background: linear-gradient(135deg, #667eea, #764ba2);
  overflow-x: hidden;
}
.garden-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  background: rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  position: sticky;
  top: 0;
  z-index: 100;
}
.back-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  text-decoration: none;
  transition: all 0.3s ease;
}
.back-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.1);
}
.garden-title {
  color: #fff;
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0;
}
.garden-level {
  background: linear-gradient(45deg, #ff6b6b, #feca57);
  color: #fff;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  font-weight: 600;
  font-size: 0.9rem;
}
.partner-status-bar {
  background: rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  padding: 1rem 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: relative;
}
.partner-actions {
  display: flex;
  align-items: center;
  margin-right: 3rem;
}
.garden-container {
  padding: 1rem;
  max-width: 1400px;
  margin: 0 auto;
  min-height: calc(100vh - 140px);
}
.tree-stats-card {
  background: rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  padding: 1.5rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
  margin-bottom: 2rem;
}
.level-progress {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.level-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}
.current-level,
.next-level {
  color: #fff;
  font-weight: 600;
}
.progress-bar {
  height: 8px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4facfe, #00f2fe);
  border-radius: 4px;
  transition: width 0.3s ease;
}
.exp-text {
  text-align: center;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.9rem;
}
.tree-stats-content {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 2rem;
  align-items: start;
}
.tree-display-area {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 2rem;
}
.stats-panel {
  display: flex;
  flex-direction: column;
}
.stats-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.stat-item {
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 1rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
  transition: all 0.3s ease;
}
.stat-item:hover {
  background: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
}
.stat-item.low {
  border-color: rgba(239, 68, 68, 0.5);
  background: rgba(239, 68, 68, 0.1);
}
.stat-item.medium {
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(245, 158, 11, 0.1);
}
.stat-item.high {
  border-color: rgba(34, 197, 94, 0.5);
  background: rgba(34, 197, 94, 0.1);
}
.stat-icon {
  font-size: 1.5rem;
  margin-right: 1rem;
}
.stat-info {
  flex: 1;
  margin-right: 1rem;
}
.stat-name,
.stat-label {
  color: #fff;
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.stat-value {
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.9rem;
}
.stat-bar {
  width: 60px;
  height: 6px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
  overflow: hidden;
}
.stat-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}
.stat-low .stat-fill {
  background: linear-gradient(90deg, #ff6b6b, #ee5a52);
}
.stat-medium .stat-fill {
  background: linear-gradient(90deg, #feca57, #ff9ff3);
}
.stat-high .stat-fill {
  background: linear-gradient(90deg, #48dbfb, #0abde3);
}
.stat-max .stat-fill {
  background: linear-gradient(90deg, #1dd1a1, #10ac84);
}
.actions-panel {
  background: rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  padding: 1.5rem;
  margin-bottom: 2rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.actions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}
.partner-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.partner-name {
  color: #fff;
  font-weight: 600;
  font-size: 1.1rem;
}
.partner-online {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 500;
  background: rgba(255, 107, 107, 0.3);
  color: #ff6b6b;
  border: 1px solid rgba(255, 107, 107, 0.5);
}
.partner-online.online {
  background: rgba(29, 209, 161, 0.3);
  color: #1dd1a1;
  border: 1px solid rgba(29, 209, 161, 0.5);
}
.actions-today {
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.9rem;
}
.desktop-only { display: block; }
.mobile-only { display: none; }
.mobile-actions-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(255, 255, 255, 0.1);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 255, 255, 0.2);
  padding: 1rem;
  z-index: 100;
}
.mobile-actions-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.5rem;
  max-width: 500px;
  margin: 0 auto;
}
@media (max-width: 1024px) {
  .tree-stats-content {
    grid-template-columns: 1fr;
    gap: 1.5rem;
  }
  .tree-display-area {
    min-height: 300px;
    order: 1;
  }
  .stats-panel { order: 2; }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.8rem;
  }
  .desktop-only { display: block; }
  .mobile-only { display: none; }
}
@media (max-width: 768px) {
  .garden-container {
    padding: 0.5rem 0.5rem 6rem;
  }
  .partner-status-bar {
    padding: 0.8rem 1rem;
    flex-direction: column;
    gap: 0.5rem;
    text-align: center;
  }
  .tree-stats-card {
    padding: 0.8rem;
    margin-bottom: 1rem;
  }
  .tree-stats-content {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
  }
  .tree-display-area {
    padding: 1rem;
    min-height: 280px;
    max-height: 320px;
    order: 1;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
  }
  .stats-panel { order: 2; }
  .stats-grid {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .stat-item {
    display: flex;
    align-items: center;
    padding: 0.6rem 0.8rem;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.15);
  }
  .stat-icon {
    font-size: 1.2rem;
    margin-right: 0.6rem;
    flex-shrink: 0;
  }
  .stat-info {
    flex: 1;
    margin-right: 0.6rem;
    min-width: 0;
  }
  .stat-label,
  .stat-name {
    font-size: 0.75rem;
    margin-bottom: 0.1rem;
    white-space: nowrap;
  }
  .stat-value {
    font-size: 0.8rem;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
  }
  .stat-bar {
    width: 50px;
    height: 4px;
    flex-shrink: 0;
  }
  .desktop-only { display: none; }
  .mobile-only { display: block; }
  .level-progress {
    padding: 0.8rem;
    margin-bottom: 0.8rem;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
  }
  .level-progress .level-info { font-size: 0.85rem; }
  .level-progress .exp-text { font-size: 0.75rem; }
  .mobile-stats-btn-inline {
    position: absolute;
    right: 1rem;
    top: 50%;
    transform: translateY(-50%);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: linear-gradient(45deg, #667eea, #764ba2);
    border: none;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    cursor: pointer;
    transition: all 0.3s ease;
  }
  .mobile-stats-btn-inline:hover {
    transform: translateY(-50%) scale(1.1);
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.5);
  }
  .stats-panel-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.5);
    z-index: 200;
    display: flex;
    justify-content: flex-end;
  }
  .stats-panel-sidebar {
    width: 80%;
    max-width: 350px;
    height: 100%;
    background-color: #1c2a38;
    box-shadow: -5px 0 25px rgba(0, 0, 0, 0.3);
    display: flex;
    flex-direction: column;
  }
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    flex-shrink: 0;
  }
  .panel-header h3 {
    margin: 0;
    font-size: 1.2rem;
    color: #fff;
  }
  .close-panel-btn {
    background: none;
    border: none;
    color: #fff;
    cursor: pointer;
    padding: 5px;
    border-radius: 50%;
    transition: background-color 0.2s ease;
  }
  .close-panel-btn:hover {
    background: rgba(255, 255, 255, 0.1);
  }
  .panel-content {
    padding: 1.5rem;
    overflow-y: auto;
    flex-grow: 1;
  }
  .mobile-stat-item {
    display: flex;
    align-items: center;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    margin-bottom: 1rem;
  }
  .mobile-stat-icon {
    font-size: 1.5rem;
    margin-right: 1rem;
    flex-shrink: 0;
  }
  .mobile-stat-info { flex: 1; }
  .mobile-stat-label {
    font-size: 0.9rem;
    color: rgba(255, 255, 255, 0.8);
    margin-bottom: 0.3rem;
  }
  .mobile-stat-value {
    font-size: 1rem;
    font-weight: 600;
    color: #fff;
    margin-bottom: 0.5rem;
  }
  .mobile-stat-bar {
    width: 100%;
    height: 6px;
    background: rgba(255, 255, 255, 0.2);
    border-radius: 3px;
    overflow: hidden;
  }
  .mobile-stat-fill {
    height: 100%;
    background: linear-gradient(90deg, #667eea, #764ba2);
    border-radius: 3px;
    transition: width 0.3s ease;
  }
  .slide-from-right-enter-active,
  .slide-from-right-leave-active {
    transition: background-color 0.4s ease;
  }
  .slide-from-right-enter-active .stats-panel-sidebar,
  .slide-from-right-leave-active .stats-panel-sidebar {
    transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .slide-from-right-enter-from,
  .slide-from-right-leave-to {
    background-color: transparent;
  }
  .slide-from-right-enter-from .stats-panel-sidebar,
  .slide-from-right-leave-to .stats-panel-sidebar {
    transform: translate(100%);
  }
}
@media (max-width: 480px) {
  .actions-grid { grid-template-columns: 1fr; }
  .garden-header { padding: 0.8rem 1rem; }
  .garden-title { font-size: 1.2rem; }
}
</style>
