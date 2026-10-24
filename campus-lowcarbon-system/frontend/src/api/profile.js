import request from '../utils/request'

/**
 * 获取我的荣誉页面数据
 * @returns {Promise}
 */
export function getProfileData() {
  return request({
    url: '/profile/data',
    method: 'get'
  })
}

