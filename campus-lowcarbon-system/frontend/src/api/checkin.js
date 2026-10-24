import request from '../utils/request'
import axios from 'axios'

/**
 * 检查每日打卡次数限制（在用户上传图片或点击开始打卡时调用）
 * @param {string} sceneType - 场景类型: 'walk' | 'ride' | 'transit' | 'plate'
 * @returns {Promise}
 */
export function checkDailyLimit(sceneType) {
  return request({
    url: '/checkin/check-limit',
    method: 'get',
    params: {
      sceneType
    }
  })
}

/**
 * 保存打卡记录到后端
 * @param {File} imageFile - 图片文件对象
 * @param {string} sceneType - 场景类型: 'walk' | 'ride' | 'transit' | 'plate'
 * @param {string} status - 验证状态: 'APPROVED' | 'REJECTED' | 'SUSPICIOUS'
 * @param {string} verifyReason - 验证原因（可选）
 * @param {string} verifySteps - 验证步骤详情JSON字符串（可选）
 * @param {string} imageHash - 图片MD5哈希值（可选）
 * @param {number} rewardPoints - 奖励积分（可选，仅当status=APPROVED时有效）
 * @param {number} locationId - 定位记录ID（可选，如果使用了定位功能）
 * @returns {Promise}
 */
export function saveCheckinRecord(imageFile, sceneType, status, verifyReason, verifySteps, imageHash, rewardPoints, locationId) {
  const formData = new FormData()
  formData.append('image', imageFile)
  formData.append('sceneType', sceneType)
  formData.append('status', status)
  
  if (verifyReason) {
    formData.append('verifyReason', verifyReason)
  }
  if (verifySteps) {
    formData.append('verifySteps', verifySteps)
  }
  if (imageHash) {
    formData.append('imageHash', imageHash)
  }
  if (rewardPoints !== undefined && rewardPoints !== null) {
    formData.append('rewardPoints', rewardPoints.toString())
  }
  if (locationId) {
    formData.append('locationId', locationId.toString())
  }
  
  return request({
    url: '/checkin/submit',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

/**
 * 开始打卡（记录起始位置）
 * @param {string} sceneType - 场景类型: 'walk' | 'ride' | 'transit'
 * @param {number} latitude - 纬度
 * @param {number} longitude - 经度
 * @returns {Promise}
 */
export function startCheckinLocation(sceneType, latitude, longitude) {
  return request({
    url: '/checkin/location/start',
    method: 'post',
    data: {
      sceneType,
      latitude,
      longitude
    }
  })
}

/**
 * 结束打卡（记录结束位置并计算距离）
 * @param {number} locationId - 定位记录ID
 * @param {number} latitude - 纬度
 * @param {number} longitude - 经度
 * @returns {Promise}
 */
export function endCheckinLocation(locationId, latitude, longitude) {
  return request({
    url: '/checkin/location/end',
    method: 'post',
    data: {
      locationId,
      latitude,
      longitude
    }
  })
}

