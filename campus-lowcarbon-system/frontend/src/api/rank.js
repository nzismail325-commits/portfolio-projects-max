import request from '../utils/request'

/**
 * 获取积分排行榜
 * @returns {Promise}
 */
export function getPointsRank() {
  return request({
    url: '/rank/points',
    method: 'get'
  })
}

/**
 * 获取勋章排行榜
 * @returns {Promise}
 */
export function getBadgesRank() {
  return request({
    url: '/rank/badges',
    method: 'get'
  })
}

/**
 * 获取称号排行榜
 * @returns {Promise}
 */
export function getTitlesRank() {
  return request({
    url: '/rank/titles',
    method: 'get'
  })
}

/**
 * 获取打卡排行榜
 * @returns {Promise}
 */
export function getCheckinsRank() {
  return request({
    url: '/rank/checkins',
    method: 'get'
  })
}

/**
 * 设置排行榜展示
 * @param {Object} data - { type: 'badge' | 'title', itemId: 勋章ID或称号ID }
 * @returns {Promise}
 */
export function setDisplay(data) {
  return request({
    url: '/rank/display',
    method: 'post',
    data
  })
}

