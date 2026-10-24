import request from '../utils/request'

/**
 * 获取用户资产信息
 * @returns {Promise}
 */
export function getUserAssets() {
  return request({
    url: '/mall/assets',
    method: 'get'
  })
}

/**
 * 获取用户统计数据
 * @returns {Promise}
 */
export function getUserStats() {
  return request({
    url: '/mall/stats',
    method: 'get'
  })
}

/**
 * 获取所有称号列表
 * @returns {Promise}
 */
export function getAllTitles() {
  return request({
    url: '/mall/titles',
    method: 'get'
  })
}

/**
 * 获取所有勋章列表
 * @returns {Promise}
 */
export function getAllBadges() {
  return request({
    url: '/mall/badges',
    method: 'get'
  })
}

/**
 * 解锁/升级称号
 * @param {number} titleId - 称号ID
 * @param {string} paymentPassword - 支付密码（可选）
 * @returns {Promise}
 */
export function upgradeTitle(titleId, paymentPassword) {
  const data = {}
  if (paymentPassword) {
    data.paymentPassword = paymentPassword
  }
  return request({
    url: `/mall/titles/${titleId}/upgrade`,
    method: 'post',
    data
  })
}

/**
 * 佩戴/卸下称号
 * @param {number} titleId - 称号ID
 * @returns {Promise}
 */
export function toggleEquipTitle(titleId) {
  return request({
    url: `/mall/titles/${titleId}/equip`,
    method: 'post'
  })
}

/**
 * 解锁勋章
 * @param {number} badgeId - 勋章ID
 * @returns {Promise}
 */
export function unlockBadge(badgeId) {
  return request({
    url: `/mall/badges/${badgeId}/unlock`,
    method: 'post'
  })
}

/**
 * 佩戴/卸下勋章
 * @param {number} badgeId - 勋章ID
 * @returns {Promise}
 */
export function toggleEquipBadge(badgeId) {
  return request({
    url: `/mall/badges/${badgeId}/equip`,
    method: 'post'
  })
}

