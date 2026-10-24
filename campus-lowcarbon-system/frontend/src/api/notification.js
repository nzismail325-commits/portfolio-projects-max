import request from '../utils/request'

/**
 * 获取未读消息数量
 * @returns {Promise}
 */
export function getUnreadNotificationCount() {
  return request({
    url: '/notification/unread-count',
    method: 'get',
    params: { _t: new Date().getTime() } // Prevent caching
  })
}

/**
 * 获取消息列表
 * @param {Object} params - 查询参数
 * @param {number} params.page - 页码
 * @param {number} params.pageSize - 每页数量
 * @param {string} params.type - 消息类型筛选（可选）
 * @param {number} params.isRead - 是否已读筛选（0-未读，1-已读，不传则全部）
 * @returns {Promise}
 */
export function getNotificationList(params) {
  // Create a new params object to avoid modifying the original one
  const queryParams = { ...params, _t: new Date().getTime() } // Prevent caching
  return request({
    url: '/notification/list',
    method: 'get',
    params: queryParams
  })
}

/**
 * 标记消息为已读
 * @param {number} notificationId - 消息ID
 * @returns {Promise}
 */
export function markAsRead(notificationId) {
  return request({
    url: `/notification/${notificationId}/read`,
    method: 'put'
  })
}

/**
 * 标记所有消息为已读
 * @returns {Promise}
 */
export function markAllAsRead() {
  return request({
    url: '/notification/read-all',
    method: 'put'
  })
}

/**
 * 删除消息
 * @param {number} notificationId - 消息ID
 * @returns {Promise}
 */
export function deleteNotification(notificationId) {
  return request({
    url: `/notification/${notificationId}`,
    method: 'delete'
  })
}

/**
 * 发送邮件（管理员给学生）
 * @param {Object} data - 邮件数据
 * @param {Array<number>} data.receiverIds - 收件人ID列表（单个或多个）
 * @param {string} data.title - 邮件主题
 * @param {string} data.content - 邮件内容
 * @param {string} data.sendType - 发送类型：SINGLE-单个，BATCH-批量，CLASS-按班级，GRADE-按年级
 * @param {string} data.filterValue - 筛选值（班级名或年级，如"2021"）
 * @returns {Promise}
 */
export function sendMail(data) {
  return request({
    url: '/notification/send',
    method: 'post',
    data
  })
}

/**
 * 获取学生列表（用于选择收件人）
 * @param {Object} params - 查询参数
 * @param {string} params.keyword - 搜索关键词（姓名或学号）
 * @param {string} params.grade - 年级筛选（如"2021"）
 * @param {string} params.className - 班级筛选
 * @returns {Promise}
 */
export function getStudentList(params = {}) {
  return request({
    url: '/notification/students',
    method: 'get',
    params
  })
}

/**
 * 获取年级列表
 * @returns {Promise}
 */
export function getGradeList() {
  return request({
    url: '/notification/grades',
    method: 'get'
  })
}

/**
 * 获取班级列表（包含年级信息）
 * @param {Object} params - 查询参数
 * @param {string} params.keyword - 搜索关键词（可选，用于搜索班级名称）
 * @returns {Promise}
 */
export function getClassList(params = {}) {
  return request({
    url: '/notification/classes',
    method: 'get',
    params
  })
}
