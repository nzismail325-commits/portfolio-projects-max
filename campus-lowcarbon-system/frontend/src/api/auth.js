import request from '../utils/request'

/**
 * 用户登录
 * @param {Object} data - 登录信息 { studentId, password }
 * @returns {Promise}
 */
export function login(data) {
  return request({
    url: '/auth/login',
    method: 'post',
    data
  })
}

/**
 * 用户注册
 * @param {Object} data - 注册信息 { studentId, username, password }
 * @returns {Promise}
 */
export function register(data) {
  return request({
    url: '/auth/register',
    method: 'post',
    data
  })
}
