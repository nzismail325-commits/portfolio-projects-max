<template>
  <div class="review-page">
    <!-- 顶部统计卡片 -->
    <div class="stats-header">
      <div class="stat-card pending">
        <div class="stat-icon">🟠</div>
        <div class="stat-content">
          <span class="stat-value">{{ pendingCount }}</span>
          <span class="stat-label">待处理异常</span>
        </div>
        <el-tag type="warning" effect="dark" size="small">需要关注</el-tag>
      </div>
      <div class="stat-card rejected">
        <div class="stat-icon">🔴</div>
        <div class="stat-content">
          <span class="stat-value">{{ todayRejectedCount }}</span>
          <span class="stat-label">今日自动驳回</span>
        </div>
        <el-tag type="danger" effect="plain" size="small">AI 拦截</el-tag>
      </div>
      <div class="stat-card approved">
        <div class="stat-icon">🟢</div>
        <div class="stat-content">
          <span class="stat-value">{{ todayApprovedCount }}</span>
          <span class="stat-label">人工复核通过</span>
        </div>
        <el-tag type="success" effect="plain" size="small">已放行</el-tag>
      </div>
      <div class="stat-card ai-approved">
        <div class="stat-icon">🟢</div>
        <div class="stat-content">
          <span class="stat-value">{{ todayAiApprovedCount }}</span>
          <span class="stat-label">AI通过数量</span>
        </div>
        <el-tag type="success" effect="plain" size="small">已放行</el-tag>
      </div>
    </div>

    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">
          <el-icon><Warning /></el-icon>
          异常审核工作台
        </h1>
        <p class="page-desc">复核被规则引擎或 AI 拦截的可疑打卡记录</p>
      </div>
      <div class="header-right">
        <el-button :icon="Refresh" @click="refreshList">刷新列表</el-button>
        <el-dropdown trigger="click">
          <el-button>
            筛选场景
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="handleSceneFilter('全部场景')">全部场景</el-dropdown-item>
              <el-dropdown-item @click="handleSceneFilter('walk')">低碳健步走</el-dropdown-item>
              <el-dropdown-item @click="handleSceneFilter('plate')">光盘行动</el-dropdown-item>
              <el-dropdown-item @click="handleSceneFilter('ride')">绿色骑行</el-dropdown-item>
              <el-dropdown-item @click="handleSceneFilter('transit')">公共交通</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 审核表格 -->
    <div class="review-table-wrapper" v-loading="loading">
      <el-table 
        :data="reviewList" 
        stripe 
        style="width: 100%"
        :row-class-name="tableRowClassName"
        empty-text="🎉 太棒了！暂无待处理的异常记录"
      >
        <!-- 申请人 -->
        <el-table-column label="申请人" width="180">
          <template #default="{ row }">
            <div class="applicant-cell">
              <el-avatar :size="42" :style="{ background: row.avatarBg }">
                {{ row.name.charAt(0) }}
              </el-avatar>
              <div class="applicant-info">
                <span class="applicant-name">{{ row.name }}</span>
                <span class="applicant-id">{{ row.studentId }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <!-- 打卡场景 -->
        <el-table-column label="打卡场景" width="150">
          <template #default="{ row }">
            <div class="scene-cell">
              <span class="scene-icon">{{ row.sceneIcon }}</span>
              <span class="scene-name">{{ row.scene }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 凭证快照 -->
        <el-table-column label="凭证快照" width="320">
          <template #default="{ row }">
            <div class="evidence-cell">
              <el-image 
                :src="row.evidence" 
                :preview-src-list="[row.evidence]"
                fit="cover"
                class="evidence-image"
                :preview-teleported="true"
              >
                <template #error>
                  <div class="image-error">
                    <el-icon><Picture /></el-icon>
                  </div>
                </template>
              </el-image>
               <div class="reason-info">
                 <el-tag 
                   :type="row.reasonType" 
                   effect="dark"
                   class="reason-tag"
                   size="small"
                 >
                   {{ row.reasonIcon }}
                 </el-tag>
                 <div class="reason-detail">
                   {{ row.reason || row.aiReason || '需要人工审核' }}
                 </div>
               </div>
            </div>
          </template>
        </el-table-column>

        <!-- AI 建议 -->
        <el-table-column label="AI 异常置信度" width="200">
          <template #default="{ row }">
            <div class="confidence-cell">
              <div class="confidence-bar">
                <el-progress 
                  :percentage="row.confidence" 
                  :stroke-width="12"
                  :color="getConfidenceColor(row.confidence)"
                  :show-text="false"
                />
              </div>
              <div class="confidence-info">
                <span 
                  class="confidence-value" 
                  :style="{ color: getConfidenceColor(row.confidence) }"
                >
                  {{ row.confidence }}%
                </span>
                <span class="confidence-label">{{ getConfidenceLabel(row.confidence) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <!-- 提交时间 -->
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">
            <div class="time-cell">
              <span class="time-date">{{ row.submitDate }}</span>
              <span class="time-hour">{{ row.submitTime }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 决策操作 -->
        <el-table-column label="决策操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="action-cell">
              <el-button 
                type="success" 
                size="small"
                @click="handleApprove(row)"
              >
                <el-icon><Select /></el-icon>
                通过
              </el-button>
              <el-button 
                type="danger" 
                size="small"
                @click="handleReject(row)"
              >
                <el-icon><CloseBold /></el-icon>
                驳回
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrapper" v-if="reviewList.length > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        background
        @current-change="handlePageChange"
      />
    </div>

    <!-- 空状态 -->
    <div class="empty-state" v-if="reviewList.length === 0">
      <div class="empty-icon">🎉</div>
      <h3>处理完毕</h3>
      <p>当前没有待审核的异常记录</p>
      <el-button type="primary" @click="refreshList">刷新检查</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { 
  Warning, 
  Refresh, 
  ArrowDown, 
  Picture, 
  Select, 
  CloseBold 
} from '@element-plus/icons-vue'
import { getReviewList, getReviewStatistics, reviewAction } from '@/api/review'
import { useGameStore } from '@/stores/game'
import { getUserAssets, getUserStats, getAllTitles, getAllBadges } from '@/api/mall'

// 当前页码
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const selectedSceneType = ref(null) // 选中的场景类型

// 统计数据
const pendingCount = ref(0)
const todayRejectedCount = ref(0)
const todayApprovedCount = ref(0)
const todayAiApprovedCount = ref(0)

// 审核列表
const reviewList = reactive([])

// 加载状态
const loading = ref(false)

// gameStore（用于刷新小红点提示）
const gameStore = useGameStore()

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
    console.error('刷新gameStore数据失败:', error)
  }
}

// 获取置信度颜色
const getConfidenceColor = (confidence) => {
  if (confidence >= 90) return '#f56c6c'
  if (confidence >= 70) return '#e6a23c'
  if (confidence >= 50) return '#909399'
  return '#67c23a'
}

// 获取置信度标签
const getConfidenceLabel = (confidence) => {
  if (confidence >= 90) return '极大概率作弊'
  if (confidence >= 70) return '高度可疑'
  if (confidence >= 50) return '存在疑点'
  return '风险较低'
}

// 表格行样式
const tableRowClassName = ({ row }) => {
  if (row.confidence >= 90) return 'danger-row'
  if (row.confidence >= 70) return 'warning-row'
  return ''
}

// 加载审核列表
const loadReviewList = async () => {
  loading.value = true
  try {
    const res = await getReviewList({
      page: currentPage.value,
      pageSize: pageSize.value,
      sceneType: selectedSceneType.value
    })
    if (res.code === 200 && res.data) {
      // 清空列表
      reviewList.length = 0
      // 填充数据
      if (res.data.records && res.data.records.length > 0) {
        reviewList.push(...res.data.records)
      }
      // 更新总数
      total.value = res.data.total || 0
      // 更新统计数据
      if (res.data.statistics) {
        pendingCount.value = res.data.statistics.pendingCount || 0
        todayRejectedCount.value = res.data.statistics.todayRejectedCount || 0
        todayApprovedCount.value = res.data.statistics.todayApprovedCount || 0
        todayAiApprovedCount.value = res.data.statistics.todayAiApprovedCount || 0
      }
    }
  } catch (error) {
    console.error('加载审核列表失败:', error)
    ElMessage.error('加载审核列表失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// 加载统计数据
const loadStatistics = async () => {
  try {
    const res = await getReviewStatistics()
    if (res.code === 200 && res.data) {
      pendingCount.value = res.data.pendingCount || 0
      todayRejectedCount.value = res.data.todayRejectedCount || 0
      todayApprovedCount.value = res.data.todayApprovedCount || 0
      todayAiApprovedCount.value = res.data.todayAiApprovedCount || 0
      
      // 调试日志
      console.log('审核统计数据:', {
        pendingCount: pendingCount.value,
        todayRejectedCount: todayRejectedCount.value,
        todayApprovedCount: todayApprovedCount.value,
        todayAiApprovedCount: todayAiApprovedCount.value,
        rawData: res.data
      })
    }
  } catch (error) {
    console.error('加载统计数据失败:', error)
  }
}

// 刷新列表
const refreshList = () => {
  loadReviewList()
  loadStatistics()
  ElMessage.success('列表已刷新')
}

// 页码变化处理
const handlePageChange = (page) => {
  currentPage.value = page
  loadReviewList()
}

// 场景筛选处理
const handleSceneFilter = (sceneType) => {
  selectedSceneType.value = sceneType === '全部场景' ? null : sceneType
  currentPage.value = 1
  loadReviewList()
}

// 通过操作
const handleApprove = (row) => {
  // 如果是步行或骑行场景，需要输入步数/里程
  const isWalkOrRide = row.sceneType === 'walk' || row.sceneType === 'ride'
  const inputLabel = row.sceneType === 'walk' ? '步数' : '里程(km)'
  const inputPlaceholder = row.sceneType === 'walk' ? '请输入步数（如：8000）' : '请输入里程（如：2.5）'
  
  if (isWalkOrRide) {
    // 使用prompt让管理员输入步数/里程
    ElMessageBox.prompt(
      `请输入${inputLabel}（用于计算动态积分）：`,
      `✅ 通过 ${row.name} 的 [${row.scene}] 打卡申请`,
      {
        confirmButtonText: '确认通过',
        cancelButtonText: '取消',
        inputType: 'number',
        inputPlaceholder: inputPlaceholder,
        inputValidator: (value) => {
          if (!value || value.trim() === '') {
            return `请输入${inputLabel}`
          }
          const numValue = parseFloat(value)
          if (isNaN(numValue) || numValue <= 0) {
            return `${inputLabel}必须是大于0的数字`
          }
          if (row.sceneType === 'walk' && numValue < 1000) {
            return '步数应该至少1000步'
          }
          if (row.sceneType === 'ride' && numValue < 0.1) {
            return '里程应该至少0.1km'
          }
          return true
        }
      }
    ).then(async ({ value }) => {
      try {
        const extractedValue = parseFloat(value)
        const res = await reviewAction({
          reviewId: row.id,
          action: 'APPROVE',
          comment: '管理员审核通过',
          extractedValue: extractedValue
        })
        if (res.code === 200) {
          ElMessage.success({
            message: `✅ 已通过 ${row.name} 的 [${row.scene}] 打卡申请，积分已发放`,
            duration: 3000
          })
          // 刷新列表和统计
          loadReviewList()
          loadStatistics()
          // 刷新gameStore数据（用于更新小红点提示）
          refreshGameStoreData()
          // 触发全局刷新事件，通知mall页面刷新数据
          window.dispatchEvent(new Event('refreshMallData'))
        } else {
          ElMessage.error(res.message || '操作失败')
        }
      } catch (error) {
        console.error('审核通过失败:', error)
        ElMessage.error('操作失败，请稍后重试')
      }
    }).catch(() => {
      // 取消操作
    })
  } else {
    // 其他场景直接确认通过
    ElMessageBox.confirm(
      `确认该记录无异常，强制放行？\n\n申请人：${row.name}\n场景：${row.scene}\nAI 拦截原因：${row.reason}`,
      '✅ 强制通过确认',
      {
        confirmButtonText: '确认放行',
        cancelButtonText: '取消',
        type: 'success',
        dangerouslyUseHTMLString: false
      }
    ).then(async () => {
      try {
        const res = await reviewAction({
          reviewId: row.id,
          action: 'APPROVE',
          comment: '管理员审核通过'
        })
        if (res.code === 200) {
          ElMessage.success({
            message: `✅ 已通过 ${row.name} 的 [${row.scene}] 打卡申请，积分已发放`,
            duration: 3000
          })
          // 刷新列表和统计
          loadReviewList()
          loadStatistics()
          // 刷新gameStore数据（用于更新小红点提示）
          refreshGameStoreData()
          // 触发全局刷新事件，通知mall页面刷新数据
          window.dispatchEvent(new Event('refreshMallData'))
        } else {
          ElMessage.error(res.message || '操作失败')
        }
      } catch (error) {
        console.error('审核通过失败:', error)
        ElMessage.error('操作失败，请稍后重试')
      }
    }).catch(() => {
      // 取消操作
    })
  }
}

// 驳回操作
const handleReject = (row) => {
  ElMessageBox.prompt(
    `请输入驳回理由（将通知学生）：`,
    `❌ 驳回 ${row.name} 的打卡申请`,
    {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValue: row.aiReason || '',
      inputPlaceholder: '请输入驳回理由...',
      type: 'warning',
      inputValidator: (value) => {
        if (!value || value.trim().length < 5) {
          return '驳回理由至少需要 5 个字符'
        }
        return true
      }
    }
  ).then(async ({ value }) => {
    try {
      const res = await reviewAction({
        reviewId: row.id,
        action: 'REJECT',
        comment: value.trim()
      })
      if (res.code === 200) {
        ElMessage.warning({
          message: `❌ 已驳回 ${row.name} 的 [${row.scene}] 打卡申请`,
          duration: 3000
        })
        // 刷新列表和统计
        loadReviewList()
        loadStatistics()
      } else {
        ElMessage.error(res.message || '操作失败')
      }
    } catch (error) {
      console.error('审核驳回失败:', error)
      ElMessage.error('操作失败，请稍后重试')
    }
  }).catch(() => {
    // 取消操作
  })
}

// 页面加载时获取数据
onMounted(() => {
  loadReviewList()
  loadStatistics()
})
</script>

<style scoped>
.review-page {
  padding: 24px;
  background: #f0f2f5;
  min-height: calc(100vh - 60px);
}

/* 顶部统计卡片 */
.stats-header {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
  transition: all 0.3s;
}

.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
}

.stat-card.pending {
  border-left: 4px solid #e6a23c;
}

.stat-card.rejected {
  border-left: 4px solid #f56c6c;
}

.stat-card.approved {
  border-left: 4px solid #67c23a;
}

.stat-card.ai-approved {
  border-left: 4px solid #67c23a;
}

.stat-icon {
  font-size: 32px;
}

.stat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

/* 页面标题 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.header-left {
  flex: 1;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  margin: 0 0 8px;
}

.page-title .el-icon {
  color: #e6a23c;
}

.page-desc {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

.header-right {
  display: flex;
  gap: 12px;
}

/* 审核表格 */
.review-table-wrapper {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

/* 申请人单元格 */
.applicant-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.applicant-info {
  display: flex;
  flex-direction: column;
}

.applicant-name {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.applicant-id {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

/* 场景单元格 */
.scene-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scene-icon {
  font-size: 22px;
}

.scene-name {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}

/* 凭证单元格 */
.evidence-cell {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.evidence-image {
  width: 80px;
  height: 80px;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
  border: 2px solid #f0f2f5;
  transition: all 0.3s;
}

.evidence-image:hover {
  border-color: #009688;
  transform: scale(1.05);
}

.image-error {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  color: #c0c4cc;
  font-size: 24px;
}

.reason-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.reason-tag {
  font-size: 12px;
  padding: 4px 8px;
  line-height: 1.5;
  white-space: normal;
  word-break: break-word;
  width: fit-content;
  max-width: 100%;
}

.reason-detail {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  word-break: break-word;
  padding: 6px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  border-left: 3px solid #909399;
  white-space: normal;
  max-width: 100%;
}

/* 置信度单元格 */
.confidence-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.confidence-bar {
  width: 100%;
}

.confidence-bar :deep(.el-progress-bar__outer) {
  border-radius: 6px;
}

.confidence-bar :deep(.el-progress-bar__inner) {
  border-radius: 6px;
}

.confidence-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.confidence-value {
  font-size: 18px;
  font-weight: 700;
}

.confidence-label {
  font-size: 12px;
  color: #909399;
}

/* 时间单元格 */
.time-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.time-date {
  font-size: 14px;
  color: #303133;
}

.time-hour {
  font-size: 12px;
  color: #909399;
}

/* 操作单元格 */
.action-cell {
  display: flex;
  gap: 8px;
}

/* 表格行样式 */
:deep(.el-table .danger-row) {
  background-color: rgba(245, 108, 108, 0.05);
}

:deep(.el-table .warning-row) {
  background-color: rgba(230, 162, 60, 0.05);
}

:deep(.el-table .el-table__row:hover > td) {
  background-color: rgba(0, 150, 136, 0.05) !important;
}

:deep(.el-table th.el-table__cell) {
  background-color: #fafbfc;
  font-weight: 600;
  color: #606266;
}

/* 分页 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
  padding: 16px 20px;
  background: #ffffff;
  border-radius: 0 0 12px 12px;
  margin-top: -1px;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 80px 40px;
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.empty-icon {
  font-size: 72px;
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 20px;
  color: #303133;
  margin: 0 0 8px;
}

.empty-state p {
  font-size: 14px;
  color: #909399;
  margin: 0 0 24px;
}

/* 响应式 */
@media (max-width: 1400px) {
  .stats-header {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .review-page {
    padding: 16px;
  }
  
  .stats-header {
    grid-template-columns: 1fr;
  }
  
  .page-header {
    flex-direction: column;
    gap: 16px;
  }
  
  .header-right {
    width: 100%;
  }
  
  .evidence-cell {
    flex-direction: column;
  }
  
  .reason-info {
    width: 100%;
  }
  
  .reason-tag {
    max-width: 100%;
  }
  
  .reason-detail {
    max-width: 100%;
  }
}
</style>
