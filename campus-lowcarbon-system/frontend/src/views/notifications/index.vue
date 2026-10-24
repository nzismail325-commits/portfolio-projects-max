<template>
  <div class="notifications-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-content">
        <h2 class="page-title">
          <el-icon><Message /></el-icon>
          <span>{{ isAdmin ? '管理员邮件' : '消息通知' }}</span>
        </h2>
        <p class="page-desc">
          {{ isAdmin ? '查看人工复核通知，发送邮件给学生' : '查看您的系统通知和审核结果' }}
        </p>
      </div>
      <div class="header-actions">
        <!-- 管理员：写邮件按钮 -->
        <el-button 
          v-if="isAdmin"
          type="primary"
          @click="showComposeMail = true"
        >
          <el-icon><EditPen /></el-icon>
          写邮件
        </el-button>
        <el-button 
          type="primary" 
          :disabled="unreadCount === 0"
          @click="markAllAsRead"
        >
          <el-icon><Check /></el-icon>
          全部标记为已读
        </el-button>
      </div>
    </div>

    <!-- 管理员：邮件编写区域（点击写邮件按钮后显示） -->
    <ComposeMail 
      v-if="isAdmin && showComposeMail"
      @close="showComposeMail = false"
      @success="handleMailSent"
    />

    <!-- 筛选标签 - 根据角色动态渲染 -->
    <div class="filter-tabs">
      <el-radio-group v-model="filterType" @change="handleFilterChange">
        <el-radio-button label="all">全部</el-radio-button>
        <el-radio-button label="unread">未读 ({{ unreadCount }})</el-radio-button>
        
        <!-- 用户端筛选 -->
        <template v-if="!isAdmin">
          <el-radio-button label="REJECT">驳回通知</el-radio-button>
          <el-radio-button label="APPROVE">通过通知</el-radio-button>
          <el-radio-button label="MAIL">管理员邮件</el-radio-button>
        </template>
        
        <!-- 管理员端筛选 -->
        <template v-else>
          <el-radio-button label="REVIEW">人工复核通知</el-radio-button>
        </template>
      </el-radio-group>
    </div>

    <!-- 消息列表 -->
    <div class="notification-list" v-loading="loading">
      <div v-if="notificationList.length === 0" class="empty-state">
        <el-empty :description="isAdmin ? '暂无通知' : '暂无消息通知'">
          <template #image>
            <el-icon :size="80" color="#c0c4cc"><Message /></el-icon>
          </template>
        </el-empty>
      </div>

      <div v-else class="notification-items">
        <div
          v-for="item in notificationList"
          :key="item.id"
          :class="['notification-item', { 'unread': !item.isRead }]"
          @click="handleItemClick(item)"
        >
          <div class="notification-icon-wrapper">
            <el-icon 
              :size="24" 
              :color="getTypeColor(item.type)"
              class="notification-type-icon"
            >
              <component :is="getTypeIcon(item.type)" />
            </el-icon>
            <div v-if="!item.isRead" class="unread-dot"></div>
          </div>
          
          <div class="notification-content">
            <div class="notification-header">
              <h3 class="notification-title">{{ item.title }}</h3>
              <span class="notification-time">{{ formatTime(item.createdAt) }}</span>
            </div>
            
            <!-- 管理员端：显示发送者信息 -->
            <div v-if="isAdmin && item.senderName" class="notification-sender">
              <el-icon><User /></el-icon>
              <span>发送者：{{ item.senderName }}</span>
            </div>
            
            <!-- 用户端：显示发送者信息（管理员邮件） -->
            <div v-if="!isAdmin && item.type === 'MAIL' && item.senderName" class="notification-sender">
              <el-icon><User /></el-icon>
              <span>来自：{{ item.senderName }}</span>
            </div>
            
            <p class="notification-text">{{ item.content }}</p>
            <div v-if="item.extraData" class="notification-extra">
              <el-tag v-if="item.extraData.sceneType" size="small" type="info">
                {{ getSceneName(item.extraData.sceneType) }}
              </el-tag>
              <el-tag v-if="item.extraData.userName" size="small" type="success">
                {{ item.extraData.userName }}
              </el-tag>
            </div>
          </div>
          
          <div class="notification-actions">
            <el-button
              v-if="!item.isRead"
              text
              type="primary"
              size="small"
              :icon="Checked"
              class="action-btn mark-read-btn"
              @click.stop="markAsRead(item.id)"
            >
              标记已读
            </el-button>
            <el-button
              text
              type="danger"
              size="small"
              :icon="Delete"
              class="action-btn delete-btn"
              @click.stop="deleteNotification(item.id)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > 0" class="pagination-wrapper">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Message,
  Check,
  Close,
  Warning,
  SuccessFilled,
  InfoFilled,
  EditPen,
  User,
  Checked,
  Delete
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useGameStore } from '@/stores/game'
import {
  getNotificationList,
  markAsRead as markAsReadApi,
  markAllAsRead as markAllAsReadApi,
  deleteNotification as deleteNotificationApi
} from '@/api/notification'
import { getUserAssets, getUserStats, getAllTitles, getAllBadges } from '@/api/mall'
import ComposeMail from './ComposeMail.vue'

const router = useRouter()
const userStore = useUserStore()
const gameStore = useGameStore()

// 注入布局组件提供的更新未读数量方法
const updateUnreadCount = inject('updateUnreadCount', null)

// 判断是否是管理员
const isAdmin = computed(() => userStore.role === 'admin')

// 筛选类型
const filterType = ref('all')

// 加载状态
const loading = ref(false)

// 分页参数
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// 未读数量
const unreadCount = ref(0)

// 消息列表
const notificationList = ref([])

// 显示写邮件组件
const showComposeMail = ref(false)

// 加载消息列表
const loadNotificationList = async (silent = false) => {
  if (!silent) {
    loading.value = true
  }
  try {
    const params = {
      page: currentPage.value,
      pageSize: pageSize.value
    }
    
    // 根据筛选类型添加参数
    if (filterType.value === 'unread') {
      params.isRead = 0
    } else if (filterType.value !== 'all') {
      params.type = filterType.value
    }
    
    const res = await getNotificationList(params)
    if (res.code === 200 && res.data) {
      notificationList.value = res.data.records || []
      total.value = res.data.total || 0
      unreadCount.value = res.data.unreadCount || 0
      // 同步更新布局组件的角标
      if (updateUnreadCount) {
        updateUnreadCount()
      }
    } else {
      notificationList.value = []
      total.value = 0
      unreadCount.value = 0
    }
    
  } catch (error) {
    console.error('加载消息列表失败:', error)
    ElMessage.error('加载消息列表失败')
  } finally {
    loading.value = false
  }
}

// 邮件发送成功后的处理
const handleMailSent = () => {
  // 刷新消息列表
  loadNotificationList()
}

// 筛选变化处理
const handleFilterChange = () => {
  currentPage.value = 1
  loadNotificationList()
}

// 分页大小变化
const handleSizeChange = () => {
  currentPage.value = 1
  loadNotificationList()
}

// 页码变化
const handlePageChange = () => {
  loadNotificationList()
}

// 标记为已读
const markAsRead = async (notificationId) => {
  try {
    const res = await markAsReadApi(notificationId)
    if (res.code === 200) {
      // 更新本地状态
      const item = notificationList.value.find(n => n.id === notificationId)
      if (item) {
        item.isRead = true
        if (unreadCount.value > 0) {
          unreadCount.value--
        }
      }
      // 更新布局组件的角标
      if (updateUnreadCount) {
        updateUnreadCount()
      }
      ElMessage.success('已标记为已读')
    } else {
      ElMessage.error(res.message || '标记已读失败')
    }
  } catch (error) {
    console.error('标记已读失败:', error)
    ElMessage.error('标记已读失败')
  }
}

// 标记全部为已读
const markAllAsRead = async () => {
  try {
    ElMessageBox.confirm('确定要将所有消息标记为已读吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'info'
    }).then(async () => {
      const res = await markAllAsReadApi()
      if (res.code === 200) {
        // 更新本地状态
        notificationList.value.forEach(item => {
          item.isRead = true
        })
        unreadCount.value = 0
        // 更新布局组件的角标
        if (updateUnreadCount) {
          updateUnreadCount()
        }
        ElMessage.success('已全部标记为已读')
      } else {
        ElMessage.error(res.message || '标记全部已读失败')
      }
    }).catch(() => {})
  } catch (error) {
    console.error('标记全部已读失败:', error)
    ElMessage.error('标记全部已读失败')
  }
}

// 删除消息
const deleteNotification = async (notificationId) => {
  try {
    ElMessageBox.confirm('确定要删除这条消息吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    }).then(async () => {
      const res = await deleteNotificationApi(notificationId)
      if (res.code === 200) {
        // 更新本地状态
        const index = notificationList.value.findIndex(n => n.id === notificationId)
        if (index !== -1) {
          const item = notificationList.value[index]
          if (!item.isRead && unreadCount.value > 0) {
            unreadCount.value--
          }
          notificationList.value.splice(index, 1)
          total.value--
        }
        // 更新布局组件的角标
        if (updateUnreadCount) {
          updateUnreadCount()
        }
        ElMessage.success('删除成功')
      } else {
        ElMessage.error(res.message || '删除失败')
      }
    }).catch(() => {})
  } catch (error) {
    console.error('删除消息失败:', error)
    ElMessage.error('删除消息失败')
  }
}


// 点击消息项
const handleItemClick = async (item) => {
  if (!item.isRead) {
    // 点击未读消息时自动标记为已读
    await markAsRead(item.id)
  }
  
  // 如果有关联的打卡记录，可以跳转到详情页
  if (item.extraData && item.extraData.checkinId) {
    if (isAdmin.value && item.type === 'REVIEW') {
      // 管理员点击复核通知，跳转到审核页面
      router.push('/review')
    }
    // TODO: 用户端跳转到打卡记录详情页
    // else {
    //   router.push(`/checkin/detail/${item.extraData.checkinId}`)
    // }
  }
}

// 获取消息类型图标
const getTypeIcon = (type) => {
  const iconMap = {
    'REJECT': Close,
    'APPROVE': SuccessFilled,
    'SYSTEM': InfoFilled,
    'MAIL': Message,
    'REVIEW': Warning
  }
  return iconMap[type] || InfoFilled
}

// 获取消息类型颜色
const getTypeColor = (type) => {
  const colorMap = {
    'REJECT': '#f56c6c',
    'APPROVE': '#67c23a',
    'SYSTEM': '#409eff',
    'MAIL': '#26a69a',
    'REVIEW': '#e6a23c'
  }
  return colorMap[type] || '#909399'
}

// 获取场景名称
const getSceneName = (sceneType) => {
  const nameMap = {
    'walk': '低碳健步走',
    'ride': '绿色骑行',
    'plate': '光盘行动',
    'transit': '公共交通'
  }
  return nameMap[sceneType] || sceneType
}

// 格式化时间
const formatTime = (timeStr) => {
  if (!timeStr) return ''
  
  const time = new Date(timeStr)
  const now = new Date()
  const diff = now - time
  
  // 小于1分钟
  if (diff < 60000) {
    return '刚刚'
  }
  
  // 小于1小时
  if (diff < 3600000) {
    return `${Math.floor(diff / 60000)}分钟前`
  }
  
  // 小于24小时
  if (diff < 86400000) {
    return `${Math.floor(diff / 3600000)}小时前`
  }
  
  // 小于7天
  if (diff < 604800000) {
    return `${Math.floor(diff / 86400000)}天前`
  }
  
  // 格式化日期
  const year = time.getFullYear()
  const month = String(time.getMonth() + 1).padStart(2, '0')
  const day = String(time.getDate()).padStart(2, '0')
  const hour = String(time.getHours()).padStart(2, '0')
  const minute = String(time.getMinutes()).padStart(2, '0')
  
  if (year === now.getFullYear()) {
    return `${month}-${day} ${hour}:${minute}`
  } else {
    return `${year}-${month}-${day} ${hour}:${minute}`
  }
}

// 消息轮询定时器
let pollTimer = null

// 页面加载时获取消息列表
onMounted(() => {
  loadNotificationList()
  // 每10秒自动刷新列表
  pollTimer = setInterval(() => {
    // 只有在非加载状态下才刷新，避免闪烁
    if (!loading.value) {
      loadNotificationList(true) // 传入 silent=true 参数，不显示loading
    }
  }, 10000)
})

import { onUnmounted } from 'vue'

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
  }
})
</script>

<style scoped>
.notifications-page {
  padding: 24px;
  background: #f0f2f5;
  min-height: calc(100vh - 60px);
}

/* 页面标题 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  background: #ffffff;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.header-content {
  flex: 1;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
}

.page-title .el-icon {
  color: #26a69a;
}

.page-desc {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
}

/* 筛选标签 */
.filter-tabs {
  margin-bottom: 24px;
  background: #ffffff;
  padding: 16px 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

/* 消息列表 */
.notification-list {
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  min-height: 400px;
}

.empty-state {
  padding: 80px 20px;
  text-align: center;
}

.notification-items {
  padding: 8px 0;
}

.notification-item {
  display: flex;
  align-items: flex-start;
  padding: 20px 24px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background-color 0.2s;
  position: relative;
}

.notification-item:hover {
  background-color: #f5f7fa;
}

.notification-item.unread {
  background-color: #f0f9ff;
}

.notification-item.unread:hover {
  background-color: #e0f2fe;
}

.notification-icon-wrapper {
  position: relative;
  margin-right: 16px;
  flex-shrink: 0;
}

.notification-type-icon {
  display: block;
}

.unread-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  background: #f56c6c;
  border-radius: 50%;
  border: 2px solid #ffffff;
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.notification-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin: 0;
  flex: 1;
}

.notification-time {
  font-size: 12px;
  color: #909399;
  margin-left: 12px;
  flex-shrink: 0;
}

.notification-sender {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.notification-text {
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  margin: 0 0 8px 0;
  word-break: break-word;
}

.notification-extra {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.notification-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-left: 16px;
  flex-shrink: 0;
}

.action-btn {
  padding: 8px 14px;
  border-radius: 6px;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-weight: 500;
  min-width: 90px;
  border: 1px solid transparent;
  background-color: transparent;
}

.action-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.mark-read-btn {
  color: #409eff;
}

.mark-read-btn:hover {
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.1) 0%, rgba(64, 158, 255, 0.15) 100%);
  border-color: rgba(64, 158, 255, 0.3);
  color: #409eff;
}

.delete-btn {
  color: #f56c6c;
}

.delete-btn:hover {
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.1) 0%, rgba(245, 108, 108, 0.15) 100%);
  border-color: rgba(245, 108, 108, 0.3);
  color: #f56c6c;
}

.action-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
}

.action-btn .el-icon {
  font-size: 15px;
}

/* 分页 */
.pagination-wrapper {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  background: #ffffff;
  padding: 16px 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

/* 响应式 */
@media (max-width: 768px) {
  .notifications-page {
    padding: 16px;
  }
  
  .page-header {
    flex-direction: column;
    gap: 16px;
  }
  
  .header-actions {
    width: 100%;
  }
  
  .header-actions .el-button {
    width: 100%;
  }
  
  .notification-item {
    flex-direction: column;
    gap: 12px;
  }
  
  .notification-actions {
    width: 100%;
    flex-direction: row;
    justify-content: flex-end;
    margin-left: 0;
    margin-top: 12px;
  }
  
  .action-btn {
    flex: 1;
    min-width: auto;
  }
}
</style>
