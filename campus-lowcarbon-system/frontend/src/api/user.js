import request from '../utils/request'
import axios from 'axios'

/**
 * 获取当前用户信息
 * @returns {Promise}
 */
export function getUserInfo() {
  return request({
    url: '/user/info',
    method: 'get'
  })
}

/**
 * 上传头像
 * @param {File} file - 头像文件
 * @returns {Promise}
 */
export function uploadAvatar(file) {
  const formData = new FormData()
  formData.append('file', file)
  
  // 使用 axios 直接调用，因为需要 multipart/form-data
  return axios({
    url: '/api/file/avatar',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data',
      'Authorization': `Bearer ${localStorage.getItem('token')}`
    }
  }).then(response => {
    // axios 响应结构：response.data 是后端返回的 Result 对象
    // 统一返回格式，与 request 工具保持一致
    return response.data
  })
}

/**
 * 更新个人信息
 * @param {Object} data - 个人信息 { nickname, avatar, signature }
 * @returns {Promise}
 */
export function updateProfile(data) {
  return request({
    url: '/user/profile',
    method: 'put',
    data
  })
}

/**
 * 修改登录密码
 * @param {Object} data - 密码信息 { oldPassword, newPassword, confirmPassword }
 * @returns {Promise}
 */
export function changePassword(data) {
  return request({
    url: '/user/password',
    method: 'put',
    data
  })
}

/**
 * 设置支付密码
 * @param {Object} data - 支付密码信息 { oldPassword, newPassword, confirmPassword }
 * @returns {Promise}
 */
export function setPaymentPassword(data) {
  return request({
    url: '/user/payment-password',
    method: 'put',
    data
  })
}

/**
 * 关闭安全密码（删除支付密码）
 * @param {Object} data - 支付密码信息 { paymentPassword }
 * @returns {Promise}
 */
export function removePaymentPassword(data) {
  return request({
    url: '/user/payment-password',
    method: 'delete',
    data
  })
}

