import request from '../utils/request'

/**
 * 获取用户风控列表
 * @param {Object} params - 查询参数 { keyword, status }
 * @returns {Promise}
 */
export function getUserRiskList(params = {}) {
  return request({
    url: '/risk-control/users',
    method: 'get',
    params
  })
}

/**
 * 封禁用户
 * @param {Object} data - 封禁信息 { userId, reason }
 * @returns {Promise}
 */
export function banUser(data) {
  return request({
    url: '/risk-control/ban',
    method: 'post',
    data
  })
}

/**
 * 解封用户
 * @param {Object} data - 解封信息 { userId }
 * @returns {Promise}
 */
export function unbanUser(data) {
  return request({
    url: '/risk-control/unban',
    method: 'post',
    data
  })
}

/**
 * 清除所有用户的Token（强制所有用户退出登录）
 * @returns {Promise}
 */
export function clearAllUserTokens() {
  return request({
    url: '/risk-control/clear-all-tokens',
    method: 'post'
  })
}

