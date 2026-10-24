<template>
  <div class="admin-panel" v-loading="loading">
    <!-- 顶部数据卡片 -->
    <div class="stats-grid">
      <div 
        class="stat-card" 
        v-for="stat in statsData" 
        :key="stat.title"
        :class="{ clickable: stat.clickable }"
        @click="handleStatClick(stat)"
      >
        <div class="stat-icon" :style="{ background: stat.bgColor }">
          <el-icon :size="28" :color="stat.iconColor">
            <component :is="stat.icon" />
          </el-icon>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ stat.value }}</span>
          <span class="stat-title">{{ stat.title }}</span>
        </div>
        <div class="stat-trend" :class="stat.trendUp ? 'up' : 'down'">
          <el-icon><component :is="stat.trendUp ? 'Top' : 'Bottom'" /></el-icon>
          <span>{{ stat.trend }}</span>
        </div>
      </div>
    </div>

    <!-- 中部图表区域 -->
    <div class="chart-section">
      <!-- 环形饼图：五大场景参与占比 -->
      <div class="chart-card">
        <div class="chart-header">
          <h3 class="chart-title">
            <el-icon><PieChart /></el-icon>
            五大场景参与占比
            <span v-if="sceneAnalysisLoading" class="analysis-badge loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>AI增强中...</span>
            </span>
            <span v-else-if="sceneAnalysisResult" class="analysis-badge" :class="sceneAnalysisResult.source === 'ai' ? 'ai' : 'backend'">
              <el-icon v-if="sceneAnalysisResult.source === 'ai'"><Check /></el-icon>
              <el-icon v-else><InfoFilled /></el-icon>
              <span>{{ sceneAnalysisResult.source === 'ai' ? 'AI增强分析' : '规则兜底分析' }}</span>
            </span>
          </h3>
          <div class="chart-actions">
            <el-button
              v-if="sceneAnalysisResult && sceneAnalysisResult.source !== 'ai'"
              type="success"
              size="small"
              round
              :loading="sceneAnalysisLoading"
              @click="handleGenerateSceneAIAnalysis"
            >
              {{ sceneAnalysisLoading ? 'AI生成中...' : '生成AI增强分析' }}
            </el-button>
            <el-radio-group v-model="chartTimeRange" size="small">
              <el-radio-button label="today">今日</el-radio-button>
              <el-radio-button label="week">本周</el-radio-button>
              <el-radio-button label="month">本月</el-radio-button>
            </el-radio-group>
          </div>
        </div>
        <div class="chart-container" ref="pieChartRef"></div>
        <div class="ai-enhance-tip" v-if="sceneAnalysisResult && sceneAnalysisResult.source !== 'ai' && !sceneAnalysisLoading">
          当前展示规则兜底分析，点击“生成AI增强分析”可生成更完整的场景参与解释和管理建议。
        </div>
        <!-- 分析结果展示 -->
        <div v-if="sceneAnalysisResult && sceneAnalysisResult.insights && sceneAnalysisResult.insights.length > 0" class="analysis-section">
          <div class="analysis-title">关键洞察</div>
          <ul class="analysis-list">
            <li v-for="(insight, index) in sceneAnalysisResult.insights" :key="index">{{ insight }}</li>
          </ul>
          <div v-if="sceneAnalysisResult.recommendations && sceneAnalysisResult.recommendations.length > 0" class="analysis-title" style="margin-top: 12px;">改进建议</div>
          <ul v-if="sceneAnalysisResult.recommendations && sceneAnalysisResult.recommendations.length > 0" class="analysis-list">
            <li v-for="(rec, index) in sceneAnalysisResult.recommendations" :key="index">{{ rec }}</li>
          </ul>
        </div>
      </div>

      <!-- 平滑折线图：近七日活跃度 -->
      <div class="chart-card">
        <div class="chart-header">
          <h3 class="chart-title">
            <el-icon><TrendCharts /></el-icon>
            近七日系统活跃度
            <span v-if="activityAnalysisLoading" class="analysis-badge loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>AI增强中...</span>
            </span>
            <span v-else-if="activityAnalysisResult" class="analysis-badge" :class="activityAnalysisResult.source === 'ai' ? 'ai' : 'backend'">
              <el-icon v-if="activityAnalysisResult.source === 'ai'"><Check /></el-icon>
              <el-icon v-else><InfoFilled /></el-icon>
              <span>{{ activityAnalysisResult.source === 'ai' ? 'AI增强分析' : '规则兜底分析' }}</span>
            </span>
          </h3>
          <el-button
            v-if="activityAnalysisResult && activityAnalysisResult.source !== 'ai'"
            type="success"
            size="small"
            round
            :loading="activityAnalysisLoading"
            @click="handleGenerateActivityAIAnalysis"
          >
            {{ activityAnalysisLoading ? 'AI生成中...' : '生成AI增强分析' }}
          </el-button>
        </div>
        <div class="chart-container" ref="lineChartRef"></div>
        <div class="ai-enhance-tip" v-if="activityAnalysisResult && activityAnalysisResult.source !== 'ai' && !activityAnalysisLoading">
          当前展示规则兜底分析，点击“生成AI增强分析”可生成更完整的活跃度波动解释和运营建议。
        </div>
        <!-- 分析结果展示 -->
        <div v-if="activityAnalysisResult && activityAnalysisResult.insights && activityAnalysisResult.insights.length > 0" class="analysis-section">
          <div class="analysis-title">
            趋势分析：<el-tag :type="activityAnalysisResult.trend === '上升' ? 'success' : activityAnalysisResult.trend === '下降' ? 'danger' : 'info'" size="small">
              {{ activityAnalysisResult.trend }}
            </el-tag>
            <span v-if="activityAnalysisResult.peakDay" style="margin-left: 12px; color: #909399; font-size: 12px;">
              峰值日期：{{ activityAnalysisResult.peakDay }}
            </span>
          </div>
          <ul class="analysis-list">
            <li v-for="(insight, index) in activityAnalysisResult.insights" :key="index">{{ insight }}</li>
          </ul>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, watch, markRaw } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElNotification } from 'element-plus'
import * as echarts from 'echarts'
import { 
  User, 
  Coin, 
  Document, 
  Warning,
  Top,
  Bottom,
  PieChart,
  TrendCharts,
  Bell,
  Check,
  Close,
  WarningFilled,
  Loading,
  InfoFilled
} from '@element-plus/icons-vue'
import {
  getAdminDashboardData,
  getSceneParticipation,
  getActivityData,
  analyzeSceneParticipation,
  analyzeActivityTrend,
  calculateSceneParticipationAnalysis,
  calculateActivityTrendAnalysis
} from '@/api/dashboard'

const router = useRouter()

// 加载状态
const loading = ref(false)

// AI服务状态
const aiServiceAvailable = ref(true)
const aiServiceWarningShown = ref(false)
const aiWarningNotificationId = ref(null) // 存储通知ID，用于防止重复显示

// AI分析加载状态
const sceneAnalysisLoading = ref(false)
const activityAnalysisLoading = ref(false)

// 分析结果存储
const sceneAnalysisResult = ref(null)
const activityAnalysisResult = ref(null)

// 统计数据
const statsData = reactive([
  {
    title: '今日活跃人数',
    value: '0',
    icon: markRaw(User),
    bgColor: 'rgba(38, 166, 154, 0.1)',
    iconColor: '#26a69a',
    trend: '0%',
    trendUp: true,
    clickable: false
  },
  {
    title: '累计减碳量(kg)',
    value: '0',
    icon: markRaw(Coin),
    bgColor: 'rgba(64, 158, 255, 0.1)',
    iconColor: '#409eff',
    trend: '0%',
    trendUp: true,
    clickable: false
  },
  {
    title: '今日打卡次数',
    value: '0',
    icon: markRaw(Document),
    bgColor: 'rgba(230, 162, 60, 0.1)',
    iconColor: '#e6a23c',
    trend: '0%',
    trendUp: true,
    clickable: false
  },
  {
    title: '异常报警',
    value: '0',
    icon: markRaw(Warning),
    bgColor: 'rgba(245, 108, 108, 0.1)',
    iconColor: '#f56c6c',
    trend: '0',
    trendUp: true,
    clickable: false
  }
])

// 图表时间范围
const chartTimeRange = ref('today')

// 图表 DOM 引用
const pieChartRef = ref(null)
const lineChartRef = ref(null)

// ECharts 实例
let pieChartInstance = null
let lineChartInstance = null

// 场景参与占比数据
const sceneParticipationData = ref([])

// 活跃度数据
const activityData = ref([])

// 卡片点击处理
const handleStatClick = (stat) => {
  if (stat.clickable && stat.route) {
    router.push(stat.route)
  }
}

// 显示AI警告提示（只显示一次，防止重复）
const showAiWarningOnce = () => {
  if (!aiServiceWarningShown.value && !aiWarningNotificationId.value) {
    const notification = ElNotification({
      title: 'AI分析服务暂时不可用',
      message: '已自动切换到后端计算模式，图表数据正常显示。',
      type: 'warning',
      duration: 4500,
      position: 'top-right',
      onClose: () => {
        aiWarningNotificationId.value = null
        // 延迟重置标志，避免短时间内重复显示
        setTimeout(() => {
          aiServiceWarningShown.value = false
        }, 1000)
      }
    })
    aiServiceWarningShown.value = true
    aiWarningNotificationId.value = notification.id || Date.now()
  }
}

// 生成近七日日期
const generateLastSevenDays = () => {
  const dates = []
  const today = new Date()
  for (let i = 6; i >= 0; i--) {
    const date = new Date(today)
    date.setDate(today.getDate() - i)
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    dates.push(`${month}-${day}`)
  }
  return dates
}

// 加载管理员看板数据
const loadDashboardData = async () => {
  loading.value = true
  try {
    const res = await getAdminDashboardData()
    if (res.code === 200 && res.data) {
      // 更新KPI统计数据
      if (res.data.stats && res.data.stats.length > 0) {
        res.data.stats.forEach((stat, index) => {
          if (statsData[index]) {
            statsData[index].value = stat.value
            statsData[index].trend = stat.trend
            statsData[index].trendUp = stat.trendUp
          }
        })
      }
    }
  } catch (error) {
    console.error('加载管理员看板数据失败:', error)
    ElMessage.error('加载数据失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

const setBackendSceneAnalysis = async (participationData = sceneParticipationData.value) => {
  try {
    const backendRes = await calculateSceneParticipationAnalysis(chartTimeRange.value)
    if (backendRes.code === 200 && backendRes.data) {
      sceneAnalysisResult.value = {
        ...backendRes.data,
        source: 'backend'
      }
      return
    }
  } catch (error) {
    console.error('获取场景规则分析失败:', error)
  }

  const data = Array.isArray(participationData) ? participationData : []
  const validData = data.filter(item => Number(item.percentage || 0) > 0)
  const topScene = [...validData].sort((a, b) => Number(b.percentage || 0) - Number(a.percentage || 0))[0]
  sceneAnalysisResult.value = {
    source: 'backend',
    insights: [
      topScene ? `当前参与占比最高的场景是${topScene.sceneName}，占比${Number(topScene.percentage || 0).toFixed(1)}%。` : '当前场景参与数据较少，暂未形成明显参与结构。',
      `当前时间范围为${chartTimeRange.value === 'today' ? '今日' : chartTimeRange.value === 'week' ? '本周' : '本月'}，系统已基于统计数据生成即时分析。`
    ],
    recommendations: [
      '建议重点关注参与占比较低的低碳场景，结合通知或积分激励提升参与度。',
      '如需更自然完整的管理解释，可点击生成AI增强分析。'
    ]
  }
}

const setBackendActivityAnalysis = async (data = activityData.value) => {
  try {
    const backendRes = await calculateActivityTrendAnalysis()
    if (backendRes.code === 200 && backendRes.data) {
      activityAnalysisResult.value = {
        ...backendRes.data,
        source: 'backend'
      }
      return
    }
  } catch (error) {
    console.error('获取活跃度规则分析失败:', error)
  }

  const list = Array.isArray(data) ? data : []
  const peakDay = [...list].sort((a, b) => Number(b.activeUsers || 0) - Number(a.activeUsers || 0))[0]
  const avgActiveUsers = list.length > 0
    ? list.reduce((sum, item) => sum + Number(item.activeUsers || 0), 0) / list.length
    : 0
  activityAnalysisResult.value = {
    source: 'backend',
    trend: '平稳',
    peakDay: peakDay?.date || '',
    insights: [
      `近七日平均活跃用户约${avgActiveUsers.toFixed(0)}人。`,
      peakDay ? `活跃峰值出现在${peakDay.date}，活跃人数${peakDay.activeUsers}人。` : '当前活跃度数据较少，暂未形成明显趋势。',
      '该结果由规则统计即时生成，不依赖AI服务。'
    ]
  }
}

// 加载场景参与占比数据（默认规则分析，AI手动增强）
const loadSceneParticipation = async () => {
  try {
    const res = await getSceneParticipation(chartTimeRange.value)
    if (res.code === 200 && res.data) {
      sceneParticipationData.value = res.data
      updatePieChart()
      await setBackendSceneAnalysis(res.data)
      return
    }
  } catch (error) {
    console.error('获取场景参与占比基础数据失败:', error)
  }

  await setBackendSceneAnalysis()
}

const handleGenerateSceneAIAnalysis = async () => {
  if (sceneAnalysisLoading.value) return
  if (!sceneParticipationData.value || sceneParticipationData.value.length === 0) {
    ElMessage.warning('暂无场景参与数据，无法生成AI增强分析')
    return
  }

  sceneAnalysisLoading.value = true
  try {
    ElMessage.info('正在生成场景参与AI增强分析，完成后会自动替换规则报告')
    const aiRes = await analyzeSceneParticipation(sceneParticipationData.value, chartTimeRange.value)
    if (aiRes.data && aiRes.data.code === 200 && aiRes.data.data) {
      sceneAnalysisResult.value = {
        ...aiRes.data.data,
        source: 'ai'
      }
      aiServiceAvailable.value = true
      return
    }
    throw new Error('AI服务返回错误')
  } catch (error) {
    console.error('场景参与AI增强分析失败:', error)
    aiServiceAvailable.value = false
    ElMessage.warning('AI增强分析暂时不可用，已保留当前规则兜底分析')
  } finally {
    sceneAnalysisLoading.value = false
  }
}

// 加载活跃度数据（默认规则分析，AI手动增强）
const loadActivityData = async () => {
  try {
    const res = await getActivityData()
    if (res.code === 200 && res.data) {
      activityData.value = res.data
      updateLineChart()
      await setBackendActivityAnalysis(res.data)
    }
  } catch (error) {
    console.error('加载活跃度数据失败:', error)
    ElMessage.error('加载活跃度数据失败')
  }
}

const handleGenerateActivityAIAnalysis = async () => {
  if (activityAnalysisLoading.value) return
  if (!activityData.value || activityData.value.length === 0) {
    ElMessage.warning('暂无活跃度数据，无法生成AI增强分析')
    return
  }

  activityAnalysisLoading.value = true
  try {
    ElMessage.info('正在生成活跃度AI增强分析，完成后会自动替换规则报告')
    const aiRes = await analyzeActivityTrend(activityData.value)
    if (aiRes.data && aiRes.data.code === 200 && aiRes.data.data) {
      activityAnalysisResult.value = {
        ...aiRes.data.data,
        source: 'ai'
      }
      aiServiceAvailable.value = true
      return
    }
    throw new Error('AI服务返回错误')
  } catch (error) {
    console.error('活跃度AI增强分析失败:', error)
    aiServiceAvailable.value = false
    ElMessage.warning('AI增强分析暂时不可用，已保留当前规则兜底分析')
  } finally {
    activityAnalysisLoading.value = false
  }
}

// 初始化环形饼图
const initPieChart = () => {
  if (!pieChartRef.value) return
  
  pieChartInstance = echarts.init(pieChartRef.value)
  updatePieChart()
}

// 更新饼图
const updatePieChart = () => {
  if (!pieChartInstance) return
  
  // 使用实际数据
  const pieData = sceneParticipationData.value.map(item => ({
    value: item.percentage,
    name: item.sceneName
  }))
  
  // 如果没有数据，使用空数据
  if (pieData.length === 0) {
    pieData.push({ value: 100, name: '暂无数据' })
  }
  
  // 绿色系渐变配色
  const colorPalette = [
    new echarts.graphic.LinearGradient(0, 0, 1, 1, [
      { offset: 0, color: '#00695c' },
      { offset: 1, color: '#26a69a' }
    ]),
    new echarts.graphic.LinearGradient(0, 0, 1, 1, [
      { offset: 0, color: '#2e7d32' },
      { offset: 1, color: '#66bb6a' }
    ]),
    new echarts.graphic.LinearGradient(0, 0, 1, 1, [
      { offset: 0, color: '#00838f' },
      { offset: 1, color: '#4dd0e1' }
    ]),
    new echarts.graphic.LinearGradient(0, 0, 1, 1, [
      { offset: 0, color: '#558b2f' },
      { offset: 1, color: '#9ccc65' }
    ]),
    new echarts.graphic.LinearGradient(0, 0, 1, 1, [
      { offset: 0, color: '#00796b' },
      { offset: 1, color: '#80cbc4' }
    ])
  ]
  
  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: {
        color: '#303133',
        fontSize: 14
      },
      formatter: (params) => {
        return `<div style="font-weight: 600; margin-bottom: 8px; color: #303133;">${params.name}</div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #009688;"></span>
                  <span style="color: #606266;">参与人次：</span>
                  <span style="font-weight: 600; color: #303133;">${params.value}%</span>
                </div>`
      }
    },
    legend: {
      orient: 'vertical',
      right: '5%',
      top: 'center',
      itemWidth: 12,
      itemHeight: 12,
      itemGap: 16,
      textStyle: {
        color: '#606266',
        fontSize: 13
      },
      formatter: (name) => {
        const item = pieData.find(d => d.name === name)
        return item ? `${name}  ${item.value.toFixed(1)}%` : name
      }
    },
    series: [
      {
        name: '场景分布',
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: '#fff',
          borderWidth: 3
        },
        label: {
          show: true,
          position: 'center',
          fontSize: 18,
          fontWeight: 'bold',
          color: '#303133',
          formatter: (params) => {
            // 计算总占比
            const total = pieData.reduce((sum, item) => sum + item.value, 0)
            if (pieData.length === 1 && pieData[0].name === '暂无数据') {
              return `{value|暂无数据}\n{name|100.0%}`
            }
            // 显示第一个数据项的百分比和名称
            const firstItem = pieData[0]
            return `{value|${firstItem.value.toFixed(1)}%}\n{name|${firstItem.name}}`
          },
          rich: {
            value: {
              fontSize: 26,
              fontWeight: 'bold',
              color: '#009688',
              lineHeight: 36
            },
            name: {
              fontSize: 14,
              color: '#909399',
              lineHeight: 24
            }
          }
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 18,
            fontWeight: 'bold',
            color: '#303133',
            formatter: (params) => {
              // 悬停时显示当前项的百分比和名称
              return `{value|${params.value.toFixed(1)}%}\n{name|${params.name}}`
            },
            rich: {
              value: {
                fontSize: 26,
                fontWeight: 'bold',
                color: '#009688',
                lineHeight: 36
              },
              name: {
                fontSize: 14,
                color: '#909399',
                lineHeight: 24
              }
            }
          },
          itemStyle: {
            shadowBlur: 20,
            shadowOffsetX: 0,
            shadowColor: 'rgba(0, 150, 136, 0.3)'
          }
        },
        labelLine: {
          show: false
        },
        data: pieData.map((item, index) => ({
          ...item,
          itemStyle: {
            color: colorPalette[index]
          }
        }))
      }
    ]
  }
  
  pieChartInstance.setOption(option)
}

// 初始化折线图
const initLineChart = () => {
  if (!lineChartRef.value) return
  
  lineChartInstance = echarts.init(lineChartRef.value)
  updateLineChart()
}

// 更新折线图
const updateLineChart = () => {
  if (!lineChartInstance) return
  
  // 使用实际数据
  const dates = activityData.value.map(item => item.date)
  const activeUsersData = activityData.value.map(item => item.activeUsers)
  
  // 如果没有数据，使用空数据
  if (dates.length === 0) {
    const emptyDates = generateLastSevenDays()
    dates.push(...emptyDates)
    activeUsersData.push(...new Array(7).fill(0))
  }
  
  // 计算Y轴范围
  const maxValue = activeUsersData.length > 0 ? Math.max(...activeUsersData, 100) : 1000
  const minValue = activeUsersData.length > 0 ? Math.max(0, Math.min(...activeUsersData) - 100) : 0
  
  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: {
        color: '#303133',
        fontSize: 14
      },
      axisPointer: {
        type: 'cross',
        crossStyle: {
          color: '#009688'
        },
        lineStyle: {
          color: '#009688',
          type: 'dashed'
        }
      },
      formatter: (params) => {
        const data = params[0]
        return `<div style="font-weight: 600; margin-bottom: 8px; color: #303133;">${data.axisValue}</div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #009688;"></span>
                  <span style="color: #606266;">活跃人数：</span>
                  <span style="font-weight: 600; color: #009688;">${data.value} 人</span>
                </div>`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: {
        lineStyle: {
          color: '#dcdfe6'
        }
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#909399',
        fontSize: 12,
        margin: 12
      }
    },
    yAxis: {
      type: 'value',
      min: minValue,
      max: maxValue,
      splitNumber: 5,
      axisLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#909399',
        fontSize: 12
      },
      splitLine: {
        lineStyle: {
          color: '#f0f2f5',
          type: 'dashed'
        }
      }
    },
    series: [
      {
        name: '活跃人数',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false,
        lineStyle: {
          color: '#009688',
          width: 3,
          shadowColor: 'rgba(0, 150, 136, 0.3)',
          shadowBlur: 10,
          shadowOffsetY: 8
        },
        itemStyle: {
          color: '#009688',
          borderColor: '#fff',
          borderWidth: 2
        },
        emphasis: {
          showSymbol: true,
          symbolSize: 12,
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 150, 136, 0.5)'
          }
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(0, 150, 136, 0.35)' },
            { offset: 0.5, color: 'rgba(0, 150, 136, 0.15)' },
            { offset: 1, color: 'rgba(0, 150, 136, 0.02)' }
          ])
        },
        data: activeUsersData
      }
    ]
  }
  
  lineChartInstance.setOption(option)
}

// 窗口 resize 处理
const handleResize = () => {
  pieChartInstance?.resize()
  lineChartInstance?.resize()
}

// 监听时间范围变化
watch(chartTimeRange, () => {
  loadSceneParticipation()
})

// 生命周期钩子
onMounted(async () => {
  // 初始化图表
  initPieChart()
  initLineChart()
  
  // 加载数据（先加载基础数据，再并行加载分析数据）
  await loadDashboardData()
  
  // 并行加载图表数据和分析（但分析请求之间错开一点时间，避免并发问题）
  await Promise.all([
    loadSceneParticipation(),
    new Promise(resolve => setTimeout(() => {
      loadActivityData().finally(resolve)
    }, 500)) // 第二个分析延迟500ms启动，避免并发冲突
  ])
  
  // 监听窗口 resize 事件
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  // 移除 resize 监听
  window.removeEventListener('resize', handleResize)
  
  // 销毁图表实例，释放内存
  pieChartInstance?.dispose()
  lineChartInstance?.dispose()
  pieChartInstance = null
  lineChartInstance = null
})
</script>

<style scoped>
.admin-panel {
  padding: 24px;
  background: #f0f2f5;
  min-height: calc(100vh - 60px);
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
  transition: all 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}

.stat-card.clickable {
  cursor: pointer;
}

.stat-card.clickable:hover {
  border: 1px solid #e6a23c;
  box-shadow: 0 8px 24px rgba(230, 162, 60, 0.15);
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-info {
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

.stat-title {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}

.stat-trend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  font-weight: 500;
}

.stat-trend.up {
  color: #67c23a;
}

.stat-trend.down {
  color: #f56c6c;
}

/* 图表区域 */
.chart-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.chart-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  flex-wrap: wrap;
}

.chart-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.chart-container {
  height: 350px;
  width: 100%;
}

/* 响应式 */
@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .chart-section {
    grid-template-columns: 1fr;
  }
  
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

/* 分析结果区域 */
.analysis-section {
  margin-top: 20px;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
  border-left: 3px solid #009688;
}

.ai-enhance-tip {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  color: #2e7d32;
  font-size: 12px;
  line-height: 1.7;
  background: rgba(76, 175, 80, 0.09);
  border: 1px solid rgba(76, 175, 80, 0.18);
}

.analysis-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.analysis-list {
  margin: 0;
  padding-left: 20px;
  list-style-type: disc;
}

.analysis-list li {
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
  margin-bottom: 4px;
}

/* AI分析加载动画 */
.analysis-badge .is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

/* 分析标签样式优化 */
.analysis-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 12px;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.analysis-badge.loading {
  background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
  color: #856404;
  border: 1px solid #ffc107;
  box-shadow: 0 2px 4px rgba(255, 193, 7, 0.2);
}

.analysis-badge.ai {
  background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
  color: #155724;
  border: 1px solid #28a745;
  box-shadow: 0 2px 4px rgba(40, 167, 69, 0.2);
}

.analysis-badge.backend {
  background: linear-gradient(135deg, #d1ecf1 0%, #bee5eb 100%);
  color: #0c5460;
  border: 1px solid #17a2b8;
  box-shadow: 0 2px 4px rgba(23, 162, 184, 0.2);
}

.analysis-badge .el-icon {
  font-size: 14px;
}

.analysis-badge span {
  line-height: 1;
}
</style>
