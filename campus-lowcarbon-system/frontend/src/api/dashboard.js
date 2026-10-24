import request from '../utils/request'
import axios from 'axios'

// 创建独立的 axios 实例（AI 服务专用）
const aiService = axios.create({
  baseURL: 'http://localhost:5000',  // Python Flask 服务地址
  timeout: 60000,  // 60秒超时
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * 获取首页数据
 * @returns {Promise}
 */
export function getDashboardData() {
  return request({
    url: '/dashboard/data',
    method: 'get'
  })
}

/**
 * 获取每日低碳贴士（AI生成）
 * @returns {Promise}
 */
export function getDailyTip() {
  return aiService.get('/daily-tip').catch(error => {
    // 如果AI服务不可用，返回错误信息
    if (error.code === 'ECONNREFUSED' || error.message.includes('Network Error')) {
      return {
        data: {
          code: 500,
          data: {
            tip: '人工智能断线中，等待管理员维护……',
            source: 'error'
          }
        }
      }
    }
    
    if (error.code === 'ECONNABORTED') {
      return {
        data: {
          code: 500,
          data: {
            tip: '人工智能思考超时，请稍后再试...',
            source: 'error'
          }
        }
      }
    }
    
    // 其他错误
    console.error('[AI Service] 获取每日贴士失败:', error)
    return {
      data: {
        code: 500,
        data: {
          tip: '人工智能断线中，等待管理员维护……',
          source: 'error'
        }
      }
    }
  })
}

/**
 * 获取管理员看板数据
 * @returns {Promise}
 */
export function getAdminDashboardData() {
  return request({
    url: '/dashboard/admin/data',
    method: 'get'
  })
}

/**
 * 获取场景参与占比数据（用于饼图）
 * @param {string} timeRange - 时间范围：today/week/month
 * @returns {Promise}
 */
export function getSceneParticipation(timeRange = 'today') {
  return request({
    url: '/dashboard/admin/scene-participation',
    method: 'get',
    params: { timeRange }
  })
}

/**
 * 获取近七日活跃度数据（用于折线图）
 * @returns {Promise}
 */
export function getActivityData() {
  return request({
    url: '/dashboard/admin/activity',
    method: 'get'
  })
}

/**
 * AI分析场景参与占比数据
 * @param {Array} data - 场景参与占比数据
 * @param {string} timeRange - 时间范围：today/week/month
 * @returns {Promise}
 */
export function analyzeSceneParticipation(data, timeRange = 'today') {
  return aiService.post('/dashboard/analyze-scene-participation', {
    data,
    timeRange
  }).catch(error => {
    console.error('[AI Service] 分析场景参与占比失败:', error)
    return {
      data: {
        code: 500,
        message: 'AI分析服务暂时不可用'
      }
    }
  })
}

/**
 * AI分析活跃度趋势数据
 * @param {Array} data - 活跃度数据
 * @returns {Promise}
 */
export function analyzeActivityTrend(data) {
  return aiService.post('/dashboard/analyze-activity-trend', {
    data
  }).catch(error => {
    console.error('[AI Service] 分析活跃度趋势失败:', error)
    return {
      data: {
        code: 500,
        message: 'AI分析服务暂时不可用'
      }
    }
  })
}

/**
 * 后端计算场景参与占比分析（AI断联时的备用方案）
 * @param {string} timeRange - 时间范围：today/week/month
 * @returns {Promise}
 */
export function calculateSceneParticipationAnalysis(timeRange = 'today') {
  return request({
    url: '/dashboard/admin/scene-participation/analyze',
    method: 'get',
    params: { timeRange }
  })
}

/**
 * 后端计算活跃度趋势分析（AI断联时的备用方案）
 * @returns {Promise}
 */
export function calculateActivityTrendAnalysis() {
  return request({
    url: '/dashboard/admin/activity/analyze',
    method: 'get'
  })
}

/**
 * 获取个人统计数据
 * @param {string} timeRange - 时间范围：week/month
 * @returns {Promise}
 */
export function getPersonalStats(timeRange = 'week') {
  return request({
    url: '/dashboard/personal/stats',
    method: 'get',
    params: { timeRange }
  })
}

/**
 * 获取个人数据详细分析（后端计算）
 * @param {string} timeRange - 时间范围：week/month
 * @returns {Promise}
 */
export function getPersonalAnalysis(timeRange = 'week') {
  return request({
    url: '/dashboard/personal/analysis',
    method: 'get',
    params: { timeRange }
  })
}

/**
 * AI分析个人数据（接收后端计算结果）
 * @param {Object} calculation - 后端计算的分析结果
 * @param {Object} rawData - 原始统计数据
 * @returns {Promise}
 */
export function analyzePersonalData(calculation, rawData) {
  return aiService.post('/dashboard/analyze-personal-data', {
    calculation,
    rawData
  }).catch(error => {
    console.error('[AI Service] 分析个人数据失败:', error)
    return {
      data: {
        code: 500,
        message: 'AI分析服务暂时不可用'
      }
    }
  })
}

