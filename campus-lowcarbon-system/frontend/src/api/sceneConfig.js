import request from '../utils/request'
import axios from 'axios'

/**
 * 获取所有场景配置
 * @returns {Promise}
 */
export function getAllSceneConfigs() {
  return request({
    url: '/scene-config',
    method: 'get',
    params: { _t: new Date().getTime() } // 添加时间戳防止缓存
  })
}

/**
 * 根据场景类型获取配置
 * @param {string} sceneType - 场景类型：walk/ride/plate/transit
 * @returns {Promise}
 */
export function getSceneConfig(sceneType) {
  return request({
    url: `/scene-config/${sceneType}`,
    method: 'get',
    params: { _t: new Date().getTime() } // 添加时间戳防止缓存
  })
}

/**
 * 更新场景配置（仅管理员）
 * @param {string} sceneType - 场景类型
 * @param {Object} data - 配置数据
 * @returns {Promise}
 */
export function updateSceneConfig(sceneType, data) {
  return request({
    url: `/scene-config/${sceneType}`,
    method: 'put',
    data
  })
}

/**
 * 刷新AI服务配置缓存（管理员修改配置后调用）
 * @returns {Promise}
 */
export function refreshAIConfig() {
  // 直接调用AI服务（端口5000），不使用request工具（避免代理）
  return axios.post('http://localhost:5000/config/refresh', {}, {
    timeout: 5000
  }).catch(error => {
    // 如果AI服务未启动，静默失败（不影响主流程）
    console.warn('刷新AI配置缓存失败（AI服务可能未启动）:', error.message)
    return { code: 200, message: 'AI服务未启动，跳过缓存刷新' }
  })
}
