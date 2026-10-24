/**
 * 打卡相关工具函数
 */

/**
 * 根据场景配置动态生成详细的打卡提示信息
 * @param {Object} config - 场景配置对象
 * @param {string} sceneType - 场景类型：walk/ride/plate/transit
 * @returns {string} 生成的提示信息
 */
export function generateCheckinRequirementText(config, sceneType) {
  if (!config) {
    return '请按照要求上传打卡凭证。'
  }

  const parts = []
  
  // 基础要求部分
  if (sceneType === 'walk') {
    // 健步走
    const minValue = config.minValue || 5000
    const unit = config.unit || '步'
    parts.push(`请上传微信运动或手环APP的今日步数截图，步数需超过 ${minValue}${unit}。`)
    
    // 关键词提示
    if (config.keywords && config.keywords.length > 0) {
      parts.push(`截图应包含以下关键词之一：${config.keywords.join('、')}。`)
    }
    
    // 积分规则说明（健步走支持动态积分）
    const basePoints = config.rewardPoints || 10
    parts.push(`完成打卡可获得基础积分 ${basePoints} 分。`)
    
    // 动态积分规则提示
    if (config.bonusStep && config.bonusPercentage) {
      const bonusStep = config.bonusStep
      const bonusPercentage = config.bonusPercentage
      parts.push(`本场景支持动态积分：每多走 ${bonusStep}${unit}（超出最低要求部分），基础积分将增加 ${bonusPercentage}%，步数越多积分越高！`)
    } else {
      // 即使没有配置，也说明支持动态积分（如果系统支持）
      parts.push(`本场景支持动态积分，步数越多积分越高！`)
    }
  } else if (sceneType === 'ride') {
    // 绿色骑行
    const minValue = config.minValue || 1.5
    const unit = config.unit || 'km'
    parts.push(`请上传共享单车行程结束截图，骑行距离需大于 ${minValue}${unit}。`)
    
    // 关键词提示
    if (config.keywords && config.keywords.length > 0) {
      parts.push(`截图应包含以下关键词之一：${config.keywords.join('、')}。`)
    }
    
    // 积分规则说明（骑行支持动态积分）
    const basePoints = config.rewardPoints || 10
    parts.push(`完成打卡可获得基础积分 ${basePoints} 分。`)
    
    // 动态积分规则提示
    if (config.bonusStep && config.bonusPercentage) {
      const bonusStep = config.bonusStep
      const bonusPercentage = config.bonusPercentage
      parts.push(`本场景支持动态积分：每多骑 ${bonusStep}${unit}（超出最低要求部分），基础积分将增加 ${bonusPercentage}%，距离越远积分越高！`)
    } else {
      // 即使没有配置，也说明支持动态积分（如果系统支持）
      parts.push(`本场景支持动态积分，距离越远积分越高！`)
    }
  } else if (sceneType === 'plate') {
    // 光盘行动
    parts.push('请上传空盘照片，系统将通过AI识别进行验证。')
    
    // 关键词提示
    if (config.keywords && config.keywords.length > 0) {
      parts.push(`照片应包含以下关键词之一：${config.keywords.join('、')}。`)
    }
    
    // 排除关键词提示
    if (config.excludeKeywords && config.excludeKeywords.length > 0) {
      parts.push(`注意：照片不应包含以下关键词：${config.excludeKeywords.join('、')}。`)
    }
  } else if (sceneType === 'transit') {
    // 公共交通
    parts.push('请上传乘车扣费记录或电子车票，日期需为今日。')
    
    // 关键词提示
    if (config.keywords && config.keywords.length > 0) {
      parts.push(`凭证应包含以下关键词之一：${config.keywords.join('、')}。`)
    }
  }
  
  // 每日打卡次数限制提示
  if (config.dailyLimit && config.dailyLimit > 0) {
    parts.push(`每日最多可打卡 ${config.dailyLimit} 次。`)
  }
  
  // 基础积分提示（仅对不支持动态积分的场景显示）
  if (sceneType !== 'walk' && sceneType !== 'ride' && config.rewardPoints) {
    parts.push(`完成打卡可获得基础积分 ${config.rewardPoints} 分。`)
  }
  
  // 如果有自定义的requirementText，优先使用（但会补充其他信息）
  if (config.requirementText && parts.length === 0) {
    return config.requirementText
  }
  
  return parts.join(' ')
}

