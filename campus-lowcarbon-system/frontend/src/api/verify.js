import axios from 'axios'
import { ElMessage } from 'element-plus'

// 创建普通请求实例（用于非文件上传的请求）
const normalRequest = axios.create({
  baseURL: '/api',
  timeout: 5000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 普通请求拦截器
normalRequest.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 普通响应拦截器
normalRequest.interceptors.response.use(
  response => {
    const res = response.data
    if (res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res
  },
  error => {
    const message = error.response?.data?.message || error.message || '网络请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

// 创建专门用于AI服务文件上传的 axios 实例（直接调用AI服务，不通过Spring中转）
const aiServiceRequest = axios.create({
  baseURL: 'http://localhost:5000',  // Python Flask AI服务地址
  timeout: 60000, // AI验证可能需要更长时间，设置为60秒
  headers: {
    'Content-Type': 'multipart/form-data'
  }
})

// AI服务响应拦截器
aiServiceRequest.interceptors.response.use(
  response => {
    const res = response.data
    
    // AI服务返回格式: { code: 200, data: {...} }
    if (res.code !== 200) {
      return Promise.reject(new Error(res.message || '验证失败'))
    }
    
    return res
  },
  error => {
    // 网络层错误处理（AI服务断链）
    if (error.code === 'ECONNREFUSED' || error.message.includes('Network Error')) {
      return Promise.reject({
        code: 'AI_SERVICE_DOWN',
        message: 'AI服务断链，将转入人工审核'
      })
    }
    
    if (error.code === 'ECONNABORTED') {
      return Promise.reject({
        code: 'AI_SERVICE_TIMEOUT',
        message: 'AI服务响应超时，将转入人工审核'
      })
    }
    
    // 其他错误
    const message = error.response?.data?.message || error.message || 'AI验证失败'
    return Promise.reject({
      code: 'AI_SERVICE_ERROR',
      message: message
    })
  }
)

/**
 * 图片验证接口（直接调用AI服务）
 * @param {File} imageFile - 图片文件对象
 * @param {string} sceneType - 场景类型: 'walk' | 'ride' | 'transit' | 'plate'
 * @param {Function} onProgress - 进度回调函数 (可选)
 * @returns {Promise}
 */
export function verifyImage(imageFile, sceneType, onProgress) {
  const formData = new FormData()
  formData.append('image', imageFile)
  formData.append('scene_type', sceneType)

  const config = {}
  
  // 如果提供了进度回调，添加进度监听
  if (onProgress && typeof onProgress === 'function') {
    config.onUploadProgress = (progressEvent) => {
      const percentCompleted = Math.round(
        (progressEvent.loaded * 100) / progressEvent.total
      )
      onProgress(percentCompleted)
    }
  }

  return aiServiceRequest.post('/verify', formData, config)
}

/**
 * 清除验证哈希数据（测试接口）
 * @param {string} sceneType - 场景类型，如果指定则只清除该项目的；如果不指定则清除所有
 * @returns {Promise}
 */
export function clearVerifyData(sceneType = null) {
  const data = sceneType ? { scene_type: sceneType } : {}
  return normalRequest.post('/verify/clear', data)
}

