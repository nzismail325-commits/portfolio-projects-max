<template>
  <div class="risk-management-page">
    <!-- 页面标题区域 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">
          <el-icon><WarningFilled /></el-icon>
          用户风控管理
        </h1>
        <p class="page-desc">实时监控全校学生的低碳打卡行为，保障数据真实性</p>
      </div>
      <div class="header-stats">
        <div class="stat-item danger">
          <span class="stat-value">{{ highRiskCount }}</span>
          <span class="stat-label">高危用户</span>
        </div>
        <div class="stat-item warning">
          <span class="stat-value">{{ suspiciousCount }}</span>
          <span class="stat-label">存疑用户</span>
        </div>
        <div class="stat-item banned">
          <span class="stat-value">{{ bannedCount }}</span>
          <span class="stat-label">已封禁</span>
        </div>
      </div>
    </div>

    <!-- 主内容卡片 -->
    <el-card shadow="hover" class="main-card">
      <!-- 搜索筛选区域 -->
      <div class="filter-section">
        <div class="filter-row">
          <!-- 搜索框 -->
          <div class="filter-item search-item">
            <el-input
              v-model="searchKeyword"
              placeholder="输入学号或姓名进行搜索..."
              clearable
              class="search-input"
              :prefix-icon="Search"
              size="large"
            />
          </div>
          
          <!-- 账号状态筛选 -->
          <div class="filter-item">
            <div class="filter-label">账号状态</div>
            <el-select
              v-model="statusFilter"
              placeholder="全部状态"
              clearable
              class="filter-select status-select"
              size="large"
            >
              <el-option label="正常" value="normal">
                <div class="option-content status-option">
                  <el-tag type="success" effect="light" round class="status-tag">
                    <span class="status-dot normal"></span>
                    正常
                  </el-tag>
                </div>
              </el-option>
              <el-option label="已封禁" value="banned">
                <div class="option-content status-option">
                  <el-tag type="danger" effect="dark" round class="status-tag">
                    <span class="status-dot banned"></span>
                    已封禁
                  </el-tag>
                </div>
              </el-option>
            </el-select>
          </div>
          
          <!-- 风险指标筛选 -->
          <div class="filter-item">
            <div class="filter-label">风险指标</div>
            <el-select
              v-model="riskLevelFilter"
              placeholder="全部风险"
              clearable
              class="filter-select"
              size="large"
            >
              <el-option label="高危" value="high">
                <div class="option-content">
                  <el-tag type="danger" size="small" effect="dark" class="risk-tag-option">🔥 高危</el-tag>
                </div>
              </el-option>
              <el-option label="存疑" value="suspicious">
                <div class="option-content">
                  <el-tag type="warning" size="small" effect="light" class="risk-tag-option">⚠️ 存疑</el-tag>
                </div>
              </el-option>
              <el-option label="信用良好" value="safe">
                <div class="option-content">
                  <el-tag type="info" size="small" effect="plain" class="risk-tag-option">✓ 信用良好</el-tag>
                </div>
              </el-option>
            </el-select>
          </div>
          
          <!-- 清除所有Token按钮 -->
          <div class="filter-item">
            <el-button
              type="warning"
              size="large"
              :icon="SwitchButton"
              @click="handleClearAllTokens"
              class="clear-tokens-btn"
            >
              清除所有登录状态
            </el-button>
          </div>
        </div>
      </div>

      <!-- 数据表格 -->
      <el-table
        :data="paginatedData"
        class="user-table"
        v-loading="loading"
        row-class-name="table-row"
      >
        <!-- 用户信息列 -->
        <el-table-column label="用户信息" min-width="240">
          <template #default="{ row }">
            <div class="user-info-cell">
              <el-avatar 
                :size="48" 
                :src="row.avatar || `https://api.dicebear.com/7.x/avataaars/svg?seed=${row.name || row.studentId}`" 
                class="user-avatar"
              >
                {{ row.name ? row.name.charAt(0) : '?' }}
              </el-avatar>
              <div class="user-detail">
                <span class="user-name">{{ row.name }}</span>
                <span class="user-student-id">{{ row.studentId }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <!-- 学院/班级列 -->
        <el-table-column label="学院 / 班级" min-width="200">
          <template #default="{ row }">
            <div class="college-cell">
              <span class="college">{{ row.college }}</span>
              <span class="class-name">{{ row.className }}</span>
            </div>
          </template>
        </el-table-column>

        <!-- 风险指标列 -->
        <el-table-column label="风险指标" min-width="160" align="center">
          <template #default="{ row }">
            <!-- 高危: >= 5 次 -->
            <el-tag
              v-if="row.suspiciousCount >= 5"
              type="danger"
              effect="dark"
              class="risk-tag risk-high"
            >
              🔥 高危 ({{ row.suspiciousCount }}次)
            </el-tag>
            <!-- 存疑: 1-4 次 -->
            <el-tag
              v-else-if="row.suspiciousCount > 0"
              type="warning"
              effect="light"
              class="risk-tag risk-warning"
            >
              ⚠️ 存疑 ({{ row.suspiciousCount }}次)
            </el-tag>
            <!-- 安全: 0 次 -->
            <el-tag
              v-else
              type="info"
              effect="plain"
              class="risk-tag risk-safe"
            >
              ✓ 信用良好
            </el-tag>
          </template>
        </el-table-column>

        <!-- 账号状态列 -->
        <el-table-column label="账号状态" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'normal' ? 'success' : 'danger'"
              :effect="row.status === 'normal' ? 'light' : 'dark'"
              round
            >
              <span class="status-dot" :class="row.status"></span>
              {{ row.status === 'normal' ? '正常' : '已封禁' }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- 操作列 -->
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'normal'"
              type="danger"
              size="small"
              class="action-btn ban-btn"
              @click="handleBan(row)"
            >
              <el-icon><Lock /></el-icon>
              封禁
            </el-button>
            <el-button
              v-else
              type="success"
              size="small"
              class="action-btn unban-btn"
              @click="handleUnban(row)"
            >
              <el-icon><Unlock /></el-icon>
              解封
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="filteredData.length"
          layout="total, sizes, prev, pager, next, jumper"
          background
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { WarningFilled, Search, Lock, Unlock, SwitchButton } from '@element-plus/icons-vue'
import { getUserRiskList, banUser, unbanUser, clearAllUserTokens } from '@/api/risk'

// 加载状态
const loading = ref(false)

// 搜索与筛选
const searchKeyword = ref('')
const statusFilter = ref('')
const riskLevelFilter = ref('')

// 分页配置
const currentPage = ref(1)
const pageSize = ref(10)

// 原始用户数据
const users = ref([])

// 统计数据
const statistics = ref({
  highRiskCount: 0,
  suspiciousCount: 0,
  bannedCount: 0
})

/**
 * 风险判定模型 (Risk Model)
 * - 高危 (High Risk): suspiciousCount >= 5
 * - 存疑 (Suspicious): 0 < suspiciousCount < 5
 * - 安全 (Safe): suspiciousCount === 0
 */
const RISK_THRESHOLD = 5

// 统计数据（从后端获取）
const highRiskCount = computed(() => statistics.value.highRiskCount || 0)
const suspiciousCount = computed(() => statistics.value.suspiciousCount || 0)
const bannedCount = computed(() => statistics.value.bannedCount || 0)

/**
 * 加载用户风控列表
 */
const loadUserRiskList = async () => {
  loading.value = true
  try {
    const params = {}
    if (searchKeyword.value) {
      params.keyword = searchKeyword.value
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    
    const response = await getUserRiskList(params)
    if (response.code === 200 && response.data) {
      users.value = response.data.users || []
      statistics.value = response.data.statistics || {
        highRiskCount: 0,
        suspiciousCount: 0,
        bannedCount: 0
      }
    } else {
      ElMessage.error(response.message || '获取用户风控列表失败')
    }
  } catch (error) {
    console.error('加载用户风控列表失败:', error)
    ElMessage.error('加载用户风控列表失败')
  } finally {
    loading.value = false
  }
}

// 监听搜索关键词变化
watch(searchKeyword, () => {
  currentPage.value = 1 // 重置到第一页
  loadUserRiskList()
})

// 监听状态筛选变化
watch(statusFilter, () => {
  currentPage.value = 1 // 重置到第一页
  loadUserRiskList()
})

// 监听风险指标筛选变化
watch(riskLevelFilter, () => {
  currentPage.value = 1 // 重置到第一页
  // 风险指标筛选在前端进行，不需要重新加载数据
})

// 页面加载时获取数据
onMounted(() => {
  loadUserRiskList()
})

/**
 * 后端已排序，直接使用
 */
const sortedUsers = computed(() => {
  return users.value
})

/**
 * 前端风险指标筛选
 */
const filteredData = computed(() => {
  let result = sortedUsers.value
  
  // 风险指标筛选（前端筛选）
  if (riskLevelFilter.value) {
    result = result.filter(user => {
      if (riskLevelFilter.value === 'high') {
        // 高危：异常次数 >= 5
        return user.suspiciousCount >= RISK_THRESHOLD
      } else if (riskLevelFilter.value === 'suspicious') {
        // 存疑：0 < 异常次数 < 5
        return user.suspiciousCount > 0 && user.suspiciousCount < RISK_THRESHOLD
      } else if (riskLevelFilter.value === 'safe') {
        // 信用良好：异常次数 = 0
        return user.suspiciousCount === 0
      }
      return true
    })
  }
  
  return result
})

/**
 * 分页数据
 */
const paginatedData = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return filteredData.value.slice(start, end)
})

/**
 * 获取异常次数的样式类名
 * > 5: 红色 + 火苗
 * > 0: 橙色
 * = 0: 灰色
 */
const getSuspiciousClass = (count) => {
  if (count > 5) return 'suspicious-danger'
  if (count > 0) return 'suspicious-warning'
  return 'suspicious-normal'
}

/**
 * 封禁用户
 */
const handleBan = (user) => {
  ElMessageBox.prompt(
    `确定要封禁用户 "${user.name}" 吗？封禁后该用户将无法登录。\n\n封禁原因最多200字，超出部分将被截断。`,
    '⚠️ 封禁确认',
    {
      confirmButtonText: '确定封禁',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
      inputPlaceholder: '请输入封禁原因（可选，最多200字）',
      inputType: 'textarea',
      inputValue: '',
      inputAttributes: {
        maxlength: 200,
        rows: 4,
        showWordLimit: true
      },
      inputValidator: (value) => {
        // 封禁原因可选，但如果填写了，检查字数
        if (value && value.length > 200) {
          return '封禁原因不能超过200字'
        }
        return true
      }
    }
  ).then(({ value }) => {
    // 调用封禁API（后端会再次限制字数）
    return banUser({
      userId: user.id,
      reason: value || '管理员封禁'
    })
  }).then(() => {
    ElMessage.success(`用户 "${user.name}" 已封禁`)
    // 重新加载列表
    loadUserRiskList()
  }).catch((error) => {
    if (error !== 'cancel') {
      console.error('封禁用户失败:', error)
      ElMessage.error(error.message || '封禁用户失败')
    }
  })
}

/**
 * 解封用户
 */
const handleUnban = (user) => {
  ElMessageBox.confirm(
    `确定要解封用户 "${user.name}" 吗？`,
    '解封确认',
    {
      confirmButtonText: '确定解封',
      cancelButtonText: '取消',
      type: 'info'
    }
  ).then(() => {
    // 调用解封API
    return unbanUser({
      userId: user.id
    })
  }).then(() => {
    ElMessage.success(`用户 "${user.name}" 已恢复正常`)
    // 重新加载列表
    loadUserRiskList()
  }).catch((error) => {
    if (error !== 'cancel') {
      console.error('解封用户失败:', error)
      ElMessage.error(error.message || '解封用户失败')
    }
  })
}

/**
 * 清除所有学生用户的Token（强制所有学生用户退出登录）
 */
const handleClearAllTokens = () => {
  ElMessageBox.confirm(
    '确定要清除所有学生用户的登录状态吗？\n\n此操作将强制所有学生用户退出登录，需要重新登录才能继续使用系统。\n\n注意：管理员账号不受影响。',
    '⚠️ 清除所有学生登录状态',
    {
      confirmButtonText: '确定清除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
      dangerouslyUseHTMLString: false
    }
  ).then(() => {
    // 调用清除所有Token的API
    return clearAllUserTokens()
  }).then((response) => {
    const count = response.data || 0
    ElMessage.success(`已清除 ${count} 个学生用户的登录状态，学生用户需要重新登录`)
  }).catch((error) => {
    if (error !== 'cancel') {
      console.error('清除所有学生用户Token失败:', error)
      ElMessage.error(error.message || '清除所有学生用户Token失败')
    }
  })
}
</script>

<style scoped>
.risk-management-page {
  padding: 24px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}

/* ==================== 页面标题区域 ==================== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  padding: 24px 28px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.25);
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

.page-title .el-icon {
  font-size: 28px;
}

.page-desc {
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  margin: 0;
  letter-spacing: 0.5px;
}

/* 统计指标 */
.header-stats {
  display: flex;
  gap: 16px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 24px;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  min-width: 90px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #ffffff;
  line-height: 1;
}

.stat-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  margin-top: 6px;
}

.stat-item.danger .stat-value {
  color: #ff6b6b;
}

.stat-item.warning .stat-value {
  color: #feca57;
}

.stat-item.banned .stat-value {
  color: #ff9ff3;
}

/* ==================== 主内容卡片 ==================== */
.main-card {
  border-radius: 16px;
  border: none;
}

:deep(.main-card .el-card__body) {
  padding: 24px;
}

/* ==================== 搜索筛选区域 ==================== */
.filter-section {
  margin-bottom: 24px;
  padding: 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.filter-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.filter-item:has(.clear-tokens-btn) {
  justify-content: flex-end;
}

.clear-tokens-btn {
  white-space: nowrap;
}

.filter-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 4px;
}

.search-item {
  flex: 1;
  min-width: 280px;
}

.search-input {
  width: 100%;
}

:deep(.search-input .el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  background: #ffffff;
  border: 1px solid #e2e8f0;
  transition: all 0.3s ease;
}

:deep(.search-input .el-input__wrapper:hover) {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

:deep(.search-input .el-input__wrapper.is-focus) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.filter-select {
  width: 160px;
}

:deep(.filter-select .el-select__wrapper) {
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  background: #ffffff;
  border: 1px solid #e2e8f0;
  transition: all 0.3s ease;
}

:deep(.filter-select .el-select__wrapper:hover) {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

:deep(.filter-select.is-focused .el-select__wrapper) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

/* 下拉选项样式 */
.option-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-option {
  justify-content: flex-start;
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-weight: 500;
  font-size: 13px;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.normal {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}

.status-dot.banned {
  background: #ffffff;
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.5);
}

.risk-tag-option {
  border-radius: 12px;
  font-weight: 600;
  font-size: 12px;
}

/* 下拉菜单横向布局 */
:deep(.status-select .el-select-dropdown__list) {
  display: flex;
  flex-direction: row;
  gap: 12px;
  padding: 12px;
  flex-wrap: wrap;
}

:deep(.status-select .el-select-dropdown__item) {
  padding: 0;
  height: auto;
  margin: 0;
  flex: 0 0 auto;
}

:deep(.status-select .el-select-dropdown__item:hover) {
  background: transparent;
}

:deep(.status-select .el-select-dropdown__item.is-selected) {
  background: transparent;
  color: inherit;
}

:deep(.status-select .el-select-dropdown__item .option-content) {
  width: 100%;
}

/* ==================== 数据表格 ==================== */
.user-table {
  border-radius: 12px;
  overflow: hidden;
}

:deep(.el-table__header th) {
  background: #f8fafc !important;
  color: #475569;
  font-weight: 600;
  font-size: 13px;
  padding: 16px 0;
  border-bottom: 2px solid #e2e8f0;
}

:deep(.el-table__row) {
  transition: all 0.2s ease;
}

:deep(.el-table__row:hover > td) {
  background: #f8fafc !important;
}

:deep(.el-table__row td) {
  padding: 16px 0;
  border-bottom: 1px solid #f1f5f9;
}

/* ==================== 用户信息单元格 ==================== */
.user-info-cell {
  display: flex;
  align-items: center;
  gap: 14px;
}

.user-avatar {
  flex-shrink: 0;
  border: 2px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.user-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.user-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 15px;
  line-height: 1.3;
}

.user-student-id {
  font-size: 12px;
  color: #94a3b8;
  font-family: 'SF Mono', 'Consolas', monospace;
  letter-spacing: 0.5px;
}

/* ==================== 学院/班级单元格 ==================== */
.college-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.college {
  font-size: 14px;
  color: #334155;
  font-weight: 500;
}

.class-name {
  font-size: 12px;
  color: #94a3b8;
}

/* ==================== 风险指标 Tag ==================== */
.risk-tag {
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
}

.risk-high {
  animation: pulse-danger 2s ease-in-out infinite;
}

@keyframes pulse-danger {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(245, 108, 108, 0); }
}

.risk-warning {
  background: #fef3cd !important;
  border-color: #ffc107 !important;
  color: #856404 !important;
}

.risk-safe {
  background: #f8fafc !important;
  border-color: #e2e8f0 !important;
  color: #64748b !important;
}

/* ==================== 账号状态 ==================== */
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
}

.status-dot.normal {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}

.status-dot.banned {
  background: #ffffff;
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.5);
}

/* ==================== 操作按钮 (实心高亮) ==================== */
.action-btn {
  font-weight: 600;
  font-size: 13px;
  padding: 8px 14px;
  border-radius: 8px;
  transition: all 0.25s ease;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.action-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.action-btn:active {
  transform: translateY(0);
}

/* 封禁按钮 - 红色实心 */
.ban-btn {
  background: linear-gradient(135deg, #f56c6c 0%, #e53935 100%);
  border: none;
}

.ban-btn:hover {
  background: linear-gradient(135deg, #e53935 0%, #c62828 100%);
}

/* 解封按钮 - 绿色实心 */
.unban-btn {
  background: linear-gradient(135deg, #67c23a 0%, #43a047 100%);
  border: none;
}

.unban-btn:hover {
  background: linear-gradient(135deg, #43a047 0%, #2e7d32 100%);
}

:deep(.action-btn .el-icon) {
  margin-right: 4px;
  font-size: 14px;
}

/* ==================== 分页 ==================== */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid #ebeef5;
}

:deep(.el-pagination.is-background .el-pager li.is-active) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

/* ==================== 响应式适配 ==================== */
@media (max-width: 1024px) {
  .page-header {
    flex-direction: column;
    gap: 20px;
  }

  .header-stats {
    width: 100%;
    justify-content: space-around;
  }
}

@media (max-width: 768px) {
  .risk-management-page {
    padding: 16px;
  }

  .page-header {
    padding: 20px;
    border-radius: 12px;
  }

  .page-title {
    font-size: 20px;
  }

  .filter-section {
    padding: 16px;
  }

  .filter-row {
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
  }

  .filter-item {
    width: 100%;
  }

  .search-item {
    min-width: auto;
  }

  .filter-select {
    width: 100%;
  }

  .stat-item {
    padding: 10px 16px;
    min-width: auto;
    flex: 1;
  }

  .stat-value {
    font-size: 22px;
  }
}
</style>
