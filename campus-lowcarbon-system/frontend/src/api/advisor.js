/**
 * 智能顾问 API 封装
 * 
 * 对接 Python Flask AI 服务 (RAG 问答系统)
 * 服务地址: http://localhost:5000
 */

import axios from 'axios'

// 创建独立的 axios 实例（AI 服务专用）
// 不复用 request.js，因为 AI 服务运行在不同端口
const aiService = axios.create({
  baseURL: 'http://localhost:5000',  // Python Flask 服务地址
  timeout: 180000,  // LLM 响应较慢，超时设为 180 秒
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * 发送问题到智能顾问
 * 
 * @param {string} question - 用户输入的问题
 * @returns {Promise<object>} - 返回 AI 回答结果
 * 
 * 成功响应格式:
 * {
 *   answer: "AI 回答内容",
 *   source: "knowledge_base" | "llm_fallback",
 *   similarity: 0.85  // 仅 knowledge_base 时存在
 * }
 */
export const sendQuestion = async (question) => {
  try {
    const response = await aiService.post('/chat', { question })
    
    // 后端返回格式: { code: 200, data: { answer, source, similarity } }
    if (response.data && response.data.code === 200) {
      return response.data.data
    }
    
    // 业务层错误（如参数校验失败）
    throw new Error(response.data?.message || '请求失败')
    
  } catch (error) {
    // 网络层错误处理
    if (error.code === 'ECONNREFUSED' || error.message.includes('Network Error')) {
      // 后端服务未启动
      return {
        answer: '智能大脑正在休眠，请联系管理员启动服务 (Connection Refused) 💤',
        source: 'error'
      }
    }
    
    if (error.code === 'ECONNABORTED') {
      // 请求超时
      return {
        answer: '智能大脑思考超时了，请稍后再试... ⏳',
        source: 'error'
      }
    }
    
    // 其他未知错误
    console.error('[AI Service Error]', error)
    return {
      answer: '网络异常，请检查网络连接后重试 🔌',
      source: 'error'
    }
  }
}

/**
 * 健康检查接口
 * 
 * @returns {Promise<boolean>} - 服务是否可用
 */
export const checkHealth = async () => {
  try {
    const response = await aiService.get('/health')
    return response.data?.status === 'healthy'
  } catch {
    return false
  }
}

/**
 * 获取快捷提问列表
 * 
 * @param {number} count - 返回的问题数量，默认 5
 * @returns {Promise<string[]>} - 快捷提问列表
 */
export const getQuickQuestions = async (count = 5) => {
  try {
    const response = await aiService.get('/quick-questions', {
      params: { count }
    })
    
    if (response.data && response.data.code === 200) {
      return response.data.data
    }
    
    return []
  } catch (error) {
    console.error('[AI Service] 获取快捷提问失败:', error)
    // 返回空数组，前端可以隐藏快捷提问区域
    return []
  }
}

