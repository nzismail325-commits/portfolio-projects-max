<template>
  <div class="personal-stats-container" v-loading="loading">
    <!-- 页面标题区 -->
    <div class="stats-header">
      <div class="header-content">
        <h1 class="page-title">
          <el-icon :size="28" color="#ffffff"><DataAnalysis /></el-icon>
          <span>我的数据统计</span>
        </h1>
        <div class="header-subtitle">
          <span>近7天数据分析</span>
        </div>
      </div>
    </div>

    <div class="stats-content">
      <!-- 统计卡片 -->
      <el-row :gutter="20" class="stats-summary-row">
        <el-col :xs="24" :sm="12" :lg="8" class="mb-4">
          <div class="summary-item summary-item-checkin">
            <div class="summary-accent-bar"></div>
            <div class="summary-icon-wrapper">
              <div class="summary-icon">
                <span>📊</span>
              </div>
            </div>
            <div class="summary-info">
              <div class="summary-value summary-value-checkin">{{ totalCheckins }}</div>
              <div class="summary-label">总打卡次数</div>
            </div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12" :lg="8" class="mb-4">
          <div class="summary-item summary-item-carbon">
            <div class="summary-accent-bar"></div>
            <div class="summary-icon-wrapper">
              <div class="summary-icon">
                <span>🌱</span>
              </div>
            </div>
            <div class="summary-info">
              <div class="summary-value summary-value-carbon">{{ carbonStats.totalCarbonReduction.toFixed(1) }}</div>
              <div class="summary-label">累计减碳(kg)</div>
            </div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12" :lg="8" class="mb-4">
          <div class="summary-item summary-item-points">
            <div class="summary-accent-bar"></div>
            <div class="summary-icon-wrapper">
              <div class="summary-icon">
                <span>⭐</span>
              </div>
            </div>
            <div class="summary-info">
              <div class="summary-value summary-value-points">{{ pointsTrend.totalPoints }}</div>
              <div class="summary-label">总积分</div>
            </div>
          </div>
        </el-col>
      </el-row>

      <!-- 图表区域 -->
      <el-row :gutter="20" class="charts-section-row">
        <!-- 打卡趋势图 -->
        <el-col :xs="24" :md="12" :lg="8" class="mb-4">
          <el-card class="chart-card" shadow="hover">
            <template #header>
              <div class="chart-title">
                <div class="chart-title-accent"></div>
                <el-icon><TrendCharts /></el-icon>
                <span>打卡趋势</span>
              </div>
            </template>
            <div class="chart-container" ref="checkinTrendChartRef"></div>
          </el-card>
        </el-col>

        <!-- 场景分布图 -->
        <el-col :xs="24" :md="12" :lg="8" class="mb-4">
          <el-card class="chart-card" shadow="hover">
            <template #header>
              <div class="chart-title">
                <div class="chart-title-accent"></div>
                <el-icon><PieChart /></el-icon>
                <span>场景分布</span>
              </div>
            </template>
            <div class="chart-container" ref="sceneDistributionChartRef"></div>
          </el-card>
        </el-col>

        <!-- 积分获取趋势图 -->
        <el-col :xs="24" :md="12" :lg="8" class="mb-4">
          <el-card class="chart-card" shadow="hover">
            <template #header>
              <div class="chart-title">
                <div class="chart-title-accent"></div>
                <el-icon><Coin /></el-icon>
                <span>积分获取趋势</span>
              </div>
            </template>
            <div class="chart-container" ref="pointsTrendChartRef"></div>
          </el-card>
        </el-col>
      </el-row>

      <!-- AI分析结果 -->
      <el-card class="analysis-section" shadow="hover" v-if="analysisResult || aiAnalysisLoading">
        <template #header>
          <div class="analysis-header">
            <span class="analysis-header-icon">✨</span>
            <span class="analysis-header-title">🎓 低碳行为诊断书</span>
            <el-tag 
              v-if="analysisResult && !aiAnalysisLoading"
              :type="analysisResult.source === 'ai' ? 'success' : 'info'" 
              size="small"
              effect="plain"
            >
              {{ analysisResult.source === 'ai' ? 'AI增强分析' : '规则兜底分析' }}
            </el-tag>
            <el-button
              v-if="analysisResult && analysisResult.source !== 'ai'"
              class="ai-enhance-btn"
              type="success"
              size="small"
              round
              :loading="aiAnalysisLoading"
              @click="handleGenerateAIAnalysis"
            >
              {{ aiAnalysisLoading ? 'AI生成中...' : '生成AI增强分析' }}
            </el-button>
          </div>
        </template>
        <div class="ai-enhance-tip" v-if="analysisResult && analysisResult.source !== 'ai' && !aiAnalysisLoading">
          当前先展示规则兜底报告，点击“生成AI增强分析”可基于统计结果生成更完整、更自然的个性化行为报告。
        </div>
        
        <!-- 骨架屏 -->
        <el-skeleton :rows="4" animated v-if="aiAnalysisLoading && !analysisResult" />
        
        <!-- 打字机效果内容 -->
        <div class="analysis-content-wrapper" v-else-if="analysisResult">
          <div class="analysis-content">
            <div class="analysis-text" :class="{ typing: isTyping }" ref="typewriterTextRef">{{ displayedText }}</div>
            <div class="analysis-insights" v-if="analysisResult.insights && analysisResult.insights.length > 0">
              <div class="insights-title">关键洞察</div>
              <ul class="insights-list">
                <li v-for="(insight, index) in analysisResult.insights" :key="index">{{ insight }}</li>
              </ul>
            </div>
            <div class="analysis-recommendations" v-if="analysisResult.recommendations && analysisResult.recommendations.length > 0">
              <div class="recommendations-title">改进建议</div>
              <ul class="recommendations-list">
                <li v-for="(rec, index) in analysisResult.recommendations" :key="index">{{ rec }}</li>
              </ul>
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, TrendCharts, PieChart, Coin, MagicStick } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getPersonalStats, getPersonalAnalysis, analyzePersonalData } from '@/api/dashboard'
import { getAllSceneConfigs } from '@/api/sceneConfig'

// 时间范围固定为7天
const timeRange = 'week'

// 加载状态
const loading = ref(false)

// 统计数据
const statsData = reactive({
  checkinTrend: [],
  sceneDistribution: [],
  carbonStats: {
    totalCarbonReduction: 0,
    monthlyCarbonReduction: 0,
    weeklyCarbonReduction: 0
  },
  pointsTrend: {
    totalPoints: 0,
    monthlyPoints: 0,
    weeklyPoints: 0,
    dailyPoints: []
  }
})

// 计算属性
const totalCheckins = ref(0)
const carbonStats = reactive({
  totalCarbonReduction: 0,
  monthlyCarbonReduction: 0,
  weeklyCarbonReduction: 0
})
const pointsTrend = reactive({
  totalPoints: 0,
  monthlyPoints: 0,
  weeklyPoints: 0
})

// 分析结果
const analysisResult = ref(null)

// 计算分析结果（后端计算）
const calculationResult = ref(null)

// AI分析相关状态
const aiAnalysisLoading = ref(false)
const displayedText = ref('')
const typewriterTextRef = ref(null)
const isTyping = ref(false)
const checkinDailyLimitTotal = ref(12)

// 图表引用
const checkinTrendChartRef = ref(null)
const sceneDistributionChartRef = ref(null)
const pointsTrendChartRef = ref(null)

// ECharts 实例
let checkinTrendChart = null
let sceneDistributionChart = null
let pointsTrendChart = null

// 加载个人统计数据
const loadPersonalStats = async () => {
  loading.value = true
  try {
    // 并行加载统计数据和计算分析（固定7天）
    const [statsRes, analysisRes, sceneConfigRes] = await Promise.all([
      getPersonalStats('week'),
      getPersonalAnalysis('week'),
      getAllSceneConfigs()
    ])

    updateCheckinDailyLimitTotal(sceneConfigRes?.data)
    
    if (statsRes.code === 200 && statsRes.data) {
      const data = statsRes.data
      
      // 更新统计数据
      statsData.checkinTrend = data.checkinTrend || []
      statsData.sceneDistribution = data.sceneDistribution || []
      statsData.carbonStats = data.carbonStats || {}
      statsData.pointsTrend = data.pointsTrend || {}
      
      // 更新计算属性
      totalCheckins.value = statsData.checkinTrend.reduce((sum, item) => sum + item.count, 0)
      Object.assign(carbonStats, statsData.carbonStats)
      Object.assign(pointsTrend, statsData.pointsTrend)
      
      // 更新图表（延迟确保DOM已渲染且容器有尺寸）
      await nextTick()
      // 使用setTimeout确保容器已经渲染完成
      setTimeout(() => {
        updateCharts()
      }, 100)
    }
    
    // 保存计算分析结果
    if (analysisRes.code === 200 && analysisRes.data) {
      calculationResult.value = analysisRes.data
      
      showFallbackAnalysis()
    } else {
      showFallbackAnalysis()
    }
  } catch (error) {
    console.error('加载个人统计数据失败:', error)
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

const updateCheckinDailyLimitTotal = (sceneConfigs = []) => {
  if (!Array.isArray(sceneConfigs) || sceneConfigs.length === 0) {
    checkinDailyLimitTotal.value = 12
    return
  }

  const limitTotal = sceneConfigs.reduce((sum, config) => {
    const limit = Number(config.dailyLimit)
    return sum + (Number.isFinite(limit) && limit > 0 ? limit : 0)
  }, 0)

  checkinDailyLimitTotal.value = limitTotal > 0 ? limitTotal : 12
}

const buildFallbackAnalysis = () => {
  const total = statsData.checkinTrend.reduce((sum, item) => sum + Number(item.count || 0), 0)
  const activeDays = statsData.checkinTrend.filter(item => Number(item.count || 0) > 0).length
  const avgDaily = total / 7
  const totalPoints = Number(statsData.pointsTrend.totalPoints || pointsTrend.totalPoints || 0)
  const carbonReduction = Number(statsData.carbonStats.totalCarbonReduction || carbonStats.totalCarbonReduction || 0)
  const scenes = Array.isArray(statsData.sceneDistribution) ? statsData.sceneDistribution : []
  const sortedScenes = [...scenes].sort((a, b) => Number(b.value || 0) - Number(a.value || 0))
  const topScene = sortedScenes.find(scene => Number(scene.value || 0) > 0)
  const weakScene = [...scenes].reverse().find(scene => Number(scene.value || 0) === 0) || sortedScenes[sortedScenes.length - 1]
  const activityLevel = total >= 14 ? '活跃' : total >= 7 ? '稳定' : total > 0 ? '起步' : '待提升'
  const sceneName = topScene?.name || '暂无突出场景'
  const weakSceneName = weakScene?.name || '低碳场景'

  const insights = [
    `近7天累计打卡${total}次，活跃天数${activeDays}天，日均${avgDaily.toFixed(1)}次。`,
    topScene ? `当前参与最多的场景是${sceneName}，说明该类低碳行为已形成一定习惯。` : '当前暂无明显高频场景，可先从任意一个低碳场景开始。',
    `累计获得${totalPoints}积分，估算减碳${carbonReduction.toFixed(1)}kg。`
  ]

  const recommendations = [
    activeDays < 5 ? '建议提高打卡连续性，优先保持每天至少一次低碳行为记录。' : '建议继续保持当前打卡节奏，巩固稳定低碳习惯。',
    weakSceneName ? `可以适当补充${weakSceneName}相关打卡，让低碳行为结构更加均衡。` : '可以尝试覆盖更多场景，提升数据统计的丰富度。',
    'AI增强分析生成完成后，可进一步结合行为特征给出更自然的个性化建议。'
  ]

  return {
    analysis: `基于规则统计，系统判断你近7天低碳行为处于“${activityLevel}”水平。${insights.join('')} 该报告先由规则计算即时生成，保证页面不受AI响应速度影响；AI返回后会自动升级为增强分析。`,
    insights,
    recommendations,
    source: 'backend'
  }
}

const showFallbackAnalysis = () => {
  const fallback = calculationResult.value && calculationResult.value.analysis
    ? { ...calculationResult.value, source: 'backend' }
    : buildFallbackAnalysis()

  analysisResult.value = fallback
  displayedText.value = fallback.analysis || ''
  aiAnalysisLoading.value = false
  isTyping.value = false
}

// 加载AI分析
const loadAIAnalysis = async () => {
  aiAnalysisLoading.value = true
  
  try {
    // 如果有计算结果，使用计算结果；否则使用原始数据
    const res = await analyzePersonalData(
      calculationResult.value || null,
      {
        checkinTrend: statsData.checkinTrend,
        sceneDistribution: statsData.sceneDistribution,
        carbonStats: statsData.carbonStats,
        pointsTrend: statsData.pointsTrend
      }
    )
    
    if (res.data && res.data.code === 200 && res.data.data) {
      analysisResult.value = {
        ...res.data.data,
        source: 'ai'
      }
      const analysisText = analysisResult.value.analysis || ''
      if (analysisText) {
        startTypewriter(analysisText)
      } else {
        aiAnalysisLoading.value = false
      }
    } else {
      showFallbackAnalysis()
    }
  } catch (error) {
    console.error('AI分析失败:', error)
    showFallbackAnalysis()
  }
}

const handleGenerateAIAnalysis = () => {
  if (aiAnalysisLoading.value) return
  ElMessage.info('正在生成AI增强分析，完成后会自动替换当前规则报告')
  loadAIAnalysis()
}

// 打字机效果
const startTypewriter = (text) => {
  if (!text) return
  
  aiAnalysisLoading.value = false
  displayedText.value = ''
  isTyping.value = false
  
  setTimeout(() => {
    isTyping.value = true
    
    // 开始打字机效果
    let index = 0
    const typeInterval = setInterval(() => {
      if (index < text.length) {
        displayedText.value = text.substring(0, index + 1)
        index++
      } else {
        clearInterval(typeInterval)
        isTyping.value = false
      }
    }, 50) // 每50ms显示一个字符
  }, 200)
}

// 更新图表
const updateCharts = () => {
  updateCheckinTrendChart()
  updateSceneDistributionChart()
  updatePointsTrendChart()
}

// 更新打卡趋势图
const updateCheckinTrendChart = () => {
  if (!checkinTrendChartRef.value) return
  
  // 确保容器有尺寸
  const container = checkinTrendChartRef.value
  if (container.offsetWidth === 0 || container.offsetHeight === 0) {
    console.warn('打卡趋势图容器尺寸为0，延迟初始化')
    setTimeout(() => updateCheckinTrendChart(), 100)
    return
  }
  
  if (!checkinTrendChart) {
    checkinTrendChart = echarts.init(checkinTrendChartRef.value)
  }
  
  const dates = statsData.checkinTrend.map(item => item.date) || []
  const counts = statsData.checkinTrend.map(item => item.count) || []
  const mobile = isMobile()
  
  // 如果没有数据，显示空状态
  if (dates.length === 0 || counts.length === 0) {
    dates.push('暂无数据')
    counts.push(0)
  }
  
  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: {
        color: '#303133',
        fontSize: mobile ? 12 : 14
      }
    },
    grid: {
      left: mobile ? '8%' : '5%',
      right: mobile ? '5%' : '4%',
      bottom: mobile ? '15%' : '3%',
      top: mobile ? '15%' : '10%',
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
        fontSize: mobile ? 10 : 12,
        rotate: mobile ? 45 : 0,
        interval: mobile ? 'auto' : 0
      }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: checkinDailyLimitTotal.value,
      interval: Math.max(1, Math.ceil(checkinDailyLimitTotal.value / 6)),
      axisLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#909399',
        fontSize: mobile ? 10 : 12
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
        name: '打卡次数',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: mobile ? 4 : 6,
        showSymbol: false,
        lineStyle: {
          color: '#26a69a',
          width: mobile ? 2 : 3
        },
        itemStyle: {
          color: '#26a69a',
          borderColor: '#fff',
          borderWidth: 2
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(38, 166, 154, 0.3)' },
            { offset: 1, color: 'rgba(38, 166, 154, 0.05)' }
          ])
        },
        data: counts
      }
    ]
  }
  
  checkinTrendChart.setOption(option)
  // 强制resize确保图表正确渲染
  setTimeout(() => {
    checkinTrendChart?.resize()
  }, 50)
}

// 更新场景分布图
const updateSceneDistributionChart = () => {
  if (!sceneDistributionChartRef.value) return
  
  // 确保容器有尺寸
  const container = sceneDistributionChartRef.value
  if (container.offsetWidth === 0 || container.offsetHeight === 0) {
    console.warn('场景分布图容器尺寸为0，延迟初始化')
    setTimeout(() => updateSceneDistributionChart(), 100)
    return
  }
  
  if (!sceneDistributionChart) {
    sceneDistributionChart = echarts.init(sceneDistributionChartRef.value)
  }
  
  const data = statsData.sceneDistribution.map(item => ({
    name: item.sceneName,
    value: item.count
  })) || []
  const mobile = isMobile()
  
  // 如果没有数据，显示空状态
  if (data.length === 0) {
    data.push({ name: '暂无数据', value: 0 })
  }
  
  const option = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}次 ({d}%)',
      textStyle: {
        fontSize: mobile ? 12 : 14
      }
    },
    legend: {
      orient: 'horizontal',
      left: 'center',
      top: 'bottom',
      bottom: '2%',
      textStyle: {
        color: '#606266',
        fontSize: mobile ? 10 : 12
      },
      itemWidth: mobile ? 12 : 14,
      itemHeight: mobile ? 8 : 10,
      itemGap: mobile ? 8 : 16
    },
    series: [
      {
        name: '场景分布',
        type: 'pie',
        radius: mobile ? ['32%', '58%'] : ['35%', '62%'],
        center: ['50%', mobile ? '42%' : '45%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 8,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: !mobile,
          formatter: '{b}\n{d}%',
          fontSize: mobile ? 10 : 12
        },
        labelLine: {
          show: !mobile
        },
        emphasis: {
          label: {
            show: true,
            fontSize: mobile ? 12 : 14,
            fontWeight: 'bold'
          }
        },
        data: data
      }
    ]
  }
  
  sceneDistributionChart.setOption(option)
  // 强制resize确保图表正确渲染
  setTimeout(() => {
    sceneDistributionChart?.resize()
  }, 50)
}

// 更新积分获取趋势图
const updatePointsTrendChart = () => {
  if (!pointsTrendChartRef.value) return
  
  // 确保容器有尺寸
  const container = pointsTrendChartRef.value
  if (container.offsetWidth === 0 || container.offsetHeight === 0) {
    console.warn('积分获取趋势图容器尺寸为0，延迟初始化')
    setTimeout(() => updatePointsTrendChart(), 100)
    return
  }
  
  if (!pointsTrendChart) {
    pointsTrendChart = echarts.init(pointsTrendChartRef.value)
  }
  
  const dailyPoints = statsData.pointsTrend.dailyPoints || []
  const dates = dailyPoints.map(item => item.date) || []
  const points = dailyPoints.map(item => item.count) || []
  const mobile = isMobile()
  
  // 如果没有数据，显示空状态
  if (dates.length === 0 || points.length === 0) {
    dates.push('暂无数据')
    points.push(0)
  }
  
  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#e4e7ed',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: {
        color: '#303133',
        fontSize: mobile ? 12 : 14
      }
    },
    grid: {
      left: mobile ? '8%' : '8%',
      right: mobile ? '5%' : '4%',
      bottom: mobile ? '15%' : '3%',
      top: mobile ? '15%' : '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: true,
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
        fontSize: mobile ? 10 : 12,
        rotate: mobile ? 45 : 0,
        interval: mobile ? 'auto' : 0
      }
    },
    yAxis: {
      type: 'value',
      axisLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#909399',
        fontSize: mobile ? 10 : 12
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
        name: '积分',
        type: 'bar',
        barWidth: mobile ? '50%' : '60%',
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#e6a23c' },
            { offset: 1, color: '#ff9800' }
          ]),
          borderRadius: [4, 4, 0, 0]
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(230, 162, 60, 0.5)'
          }
        },
        data: points
      }
    ]
  }
  
  pointsTrendChart.setOption(option)
  // 强制resize确保图表正确渲染
  setTimeout(() => {
    pointsTrendChart?.resize()
  }, 50)
}


// 判断是否为移动端
const isMobile = () => {
  return window.innerWidth < 768
}

// 窗口resize处理（使用防抖优化性能）
let resizeTimer = null
const handleResize = () => {
  if (resizeTimer) {
    clearTimeout(resizeTimer)
  }
  resizeTimer = setTimeout(() => {
    // 只调整图表大小，不重新设置配置
    // 重新设置配置会导致图表闪烁，而且可能因为容器尺寸问题导致渲染失败
    checkinTrendChart?.resize()
    sceneDistributionChart?.resize()
    pointsTrendChart?.resize()
  }, 200)
}

// 生命周期
onMounted(() => {
  loadPersonalStats()
  window.addEventListener('resize', handleResize)
  // 监听屏幕方向变化（移动端）
  window.addEventListener('orientationchange', () => {
    setTimeout(() => {
      handleResize()
    }, 300)
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('orientationchange', handleResize)
  if (resizeTimer) {
    clearTimeout(resizeTimer)
  }
  checkinTrendChart?.dispose()
  sceneDistributionChart?.dispose()
  pointsTrendChart?.dispose()
  checkinTrendChart = null
  sceneDistributionChart = null
  pointsTrendChart = null
})
</script>

<style scoped>
.personal-stats-container {
  width: 100%;
  min-height: 100%;
}

/* 页面标题区 */
.stats-header {
  position: relative;
  padding: 48px 24px 32px;
  text-align: center;
  overflow: hidden;
  margin-bottom: 24px;
}

.stats-header::before {
  content: '';
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
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 32px;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  letter-spacing: 2px;
}

.header-subtitle {
  display: flex;
  justify-content: center;
  align-items: center;
  margin-top: 8px;
}

.header-subtitle span {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 400;
  letter-spacing: 1px;
}

.stats-content {
  padding: 0 24px 24px;
}

/* 统计摘要行 */
.stats-summary-row {
  margin-top: -20px;
  margin-bottom: 24px;
}

/* Element Plus 间距类 */
.mb-4 {
  margin-bottom: 16px;
}

.summary-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px 20px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transition: all 0.3s;
  overflow: hidden;
}

.summary-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  opacity: 0;
  transition: opacity 0.3s;
  pointer-events: none;
}

.summary-item-checkin::before {
  background: linear-gradient(135deg, rgba(38, 166, 154, 0.05) 0%, rgba(38, 166, 154, 0.02) 100%);
}

.summary-item-carbon::before {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.05) 0%, rgba(76, 175, 80, 0.02) 100%);
}

.summary-item-points::before {
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.05) 0%, rgba(255, 152, 0, 0.02) 100%);
}

.summary-item:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.summary-item:hover::before {
  opacity: 1;
}

/* 左侧强调色条 */
.summary-accent-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 16px 0 0 16px;
}

.summary-item-checkin .summary-accent-bar {
  background: linear-gradient(180deg, #26a69a 0%, #00897b 100%);
}

.summary-item-carbon .summary-accent-bar {
  background: linear-gradient(180deg, #4caf50 0%, #388e3c 100%);
}

.summary-item-points .summary-accent-bar {
  background: linear-gradient(180deg, #ff9800 0%, #f57c00 100%);
}

/* 图标容器 */
.summary-icon-wrapper {
  flex-shrink: 0;
}

.summary-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  position: relative;
  z-index: 1;
}

.summary-item-checkin .summary-icon {
  background: linear-gradient(135deg, rgba(38, 166, 154, 0.15) 0%, rgba(38, 166, 154, 0.08) 100%);
}

.summary-item-carbon .summary-icon {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.08) 100%);
}

.summary-item-points .summary-icon {
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.15) 0%, rgba(255, 152, 0, 0.08) 100%);
}

.summary-info {
  flex: 1;
  position: relative;
  z-index: 1;
}

.summary-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 4px;
}

.summary-value-checkin {
  color: #26a69a;
}

.summary-value-carbon {
  color: #4caf50;
}

.summary-value-points {
  color: #ff9800;
}

.summary-label {
  font-size: 13px;
  color: #909399;
  font-weight: 500;
}

/* 图表区域行 */
.charts-section-row {
  margin-bottom: 24px;
}

.chart-card {
  border-radius: 16px;
  border: none;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 360px; /* 确保卡片有最小高度：header(60px) + padding(40px) + chart(280px) */
}

.chart-card :deep(.el-card__body) {
  padding: 20px;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.chart-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  position: relative;
  padding-left: 16px;
}

/* 左侧竖线装饰 */
.chart-title-accent {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 20px;
  background: linear-gradient(180deg, #26a69a 0%, #00897b 100%);
  border-radius: 2px;
}

.chart-title .el-icon {
  color: #26a69a;
  font-size: 20px;
}

.chart-container {
  width: 100%;
  height: 280px !important; /* 强制固定高度，防止高度塌陷 */
  min-height: 280px;
  flex-shrink: 0; /* 防止被压缩 */
}

/* 平板和手机端保持300px */
@media (max-width: 1199px) {
  .chart-container {
    height: 300px !important;
    min-height: 300px;
  }
  
  .chart-card {
    min-height: 380px; /* 手机端：header(60px) + padding(40px) + chart(300px) */
  }
}

/* AI分析区域 */
.analysis-section {
  margin-top: 24px;
  border-radius: 16px;
  border: none;
  background: linear-gradient(135deg, #f0f9eb 0%, #ffffff 100%);
  overflow: hidden;
}

.analysis-section :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%);
  border-bottom: 2px solid rgba(76, 175, 80, 0.2);
  padding: 20px 24px;
}

.analysis-section :deep(.el-card__body) {
  padding: 24px;
  max-height: 500px;
  overflow-y: auto;
}

.analysis-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.analysis-header-icon {
  font-size: 24px;
  animation: sparkle 2s ease-in-out infinite;
}

@keyframes sparkle {
  0%, 100% { 
    transform: scale(1);
    opacity: 1;
  }
  50% { 
    transform: scale(1.1);
    opacity: 0.8;
  }
}

.analysis-header-title {
  font-size: 18px;
  font-weight: 700;
  color: #2e7d32;
  letter-spacing: 1px;
}

.ai-enhance-btn {
  margin-left: auto;
  border: none;
  background: linear-gradient(135deg, #43a047 0%, #26a69a 100%);
  box-shadow: 0 4px 12px rgba(38, 166, 154, 0.22);
}

.ai-enhance-tip {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  color: #2e7d32;
  font-size: 13px;
  line-height: 1.7;
  background: rgba(76, 175, 80, 0.09);
  border: 1px solid rgba(76, 175, 80, 0.18);
}

.analysis-content-wrapper {
  min-height: 0;
}

.analysis-content {
  color: #424242;
  line-height: 2;
}

.analysis-text {
  font-size: 15px;
  margin-bottom: 20px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #2e7d32;
  font-weight: 500;
  padding: 16px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  border-left: 4px solid #4caf50;
  position: relative;
}

.analysis-text.typing::after {
  content: '|';
  animation: blink 1s infinite;
  color: #4caf50;
  font-weight: 700;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 自定义滚动条样式 */
.analysis-content-wrapper::-webkit-scrollbar {
  width: 6px;
}

.analysis-content-wrapper::-webkit-scrollbar-track {
  background: #f5f5f5;
  border-radius: 3px;
}

.analysis-content-wrapper::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 3px;
  transition: background 0.2s;
}

.analysis-content-wrapper::-webkit-scrollbar-thumb:hover {
  background: #909399;
}

.analysis-insights,
.analysis-recommendations {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e4e7ed;
}

.insights-title,
.recommendations-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.insights-list,
.recommendations-list {
  margin: 0;
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
}

.insights-list li,
.recommendations-list li {
  margin-bottom: 6px;
  line-height: 1.6;
}

/* 响应式 */
@media (max-width: 768px) {
  .stats-header {
    padding: 32px 16px 24px;
  }
  
  .page-title {
    font-size: 24px;
  }
  
  .stats-content {
    padding: 0 16px 16px;
  }
  
  .stats-summary-row {
    margin-top: -10px;
  }
  
  
  .chart-card :deep(.el-card__body) {
    padding: 15px;
  }
  
  .chart-container {
    height: 300px;
  }
  
  .analysis-section {
    max-height: 400px;
  }
  
  .analysis-section :deep(.el-card__body) {
    padding: 15px;
  }
}

@media (max-width: 480px) {
  .summary-item {
    padding: 20px 16px;
  }
  
  .summary-icon {
    width: 56px;
    height: 56px;
    font-size: 24px;
  }
  
  .summary-value {
    font-size: 28px;
  }
  
  .chart-container {
    height: 280px;
  }
}
</style>
