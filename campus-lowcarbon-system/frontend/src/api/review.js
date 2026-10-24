import request from '../utils/request'

/**
 * 获取审核列表（分页）
 * @param {Object} params - 查询参数 { page, pageSize, sceneType }
 * @returns {Promise}
 */
export function getReviewList(params = {}) {
  return request({
    url: '/review/list',
    method: 'get',
    params
  })
}

/**
 * 获取审核统计数据
 * @returns {Promise}
 */
export function getReviewStatistics() {
  return request({
    url: '/review/statistics',
    method: 'get'
  })
}

/**
 * 审核操作（通过或驳回）
 * @param {Object} data - 审核信息 { reviewId, action, comment }
 * @returns {Promise}
 */
export function reviewAction(data) {
  return request({
    url: '/review/action',
    method: 'post',
    data
  })
}

