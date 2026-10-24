import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getAllSceneConfigs, getSceneConfig as fetchSceneConfig } from '@/api/sceneConfig'

/**
 * 打卡场景配置 Store
 * 管理四大打卡场景的配置信息，管理员修改后同步到学生端显示
 */
export const useCheckinStore = defineStore('checkin', () => {
  // 场景配置数据（从后端加载，初始为空对象）
  const sceneConfigs = ref({})

  // 获取场景配置
  const getSceneConfig = (sceneType) => {
    return sceneConfigs.value[sceneType] || {}
  }

  // 更新场景配置（管理员调用）
  const updateSceneConfig = (sceneType, config) => {
    // 直接替换整个对象，确保响应式更新
    sceneConfigs.value[sceneType] = { ...config }
  }

  // 批量更新配置（从后端加载时使用）
  const setAllConfigs = (configs) => {
    sceneConfigs.value = {
      ...sceneConfigs.value,
      ...configs
    }
  }

  // 从后端加载所有场景配置
  const loadAllConfigs = async () => {
    try {
      const response = await getAllSceneConfigs()
      const configs = response.data || []
      
      // 将后端数据转换为前端格式
      const formattedConfigs = {}
      configs.forEach(config => {
        formattedConfigs[config.sceneType] = {
          icon: config.icon || '',
          title: config.title || '',
          tag: config.tag || '',
          tagType: config.tagType || 'primary',
          rewardPoints: config.rewardPoints || 10,
          requirementText: config.requirementText || '',
          minValue: config.minValue ? Number(config.minValue) : null,
          unit: config.unit || '',
          keywords: config.keywords || [],
          excludeKeywords: config.excludeKeywords || [],
          dailyLimit: config.dailyLimit !== undefined ? config.dailyLimit : 3,
          bonusStep: config.bonusStep ? Number(config.bonusStep) : null,
          bonusPercentage: config.bonusPercentage ? Number(config.bonusPercentage) : null
        }
      })
      
      // 更新store
      setAllConfigs(formattedConfigs)
      return formattedConfigs
    } catch (error) {
      console.error('加载场景配置失败:', error)
      // 如果加载失败，使用默认配置
      return sceneConfigs.value
    }
  }

  // 从后端加载单个场景配置
  const loadSceneConfig = async (sceneType) => {
    try {
      const response = await fetchSceneConfig(sceneType)
      const config = response.data
      
      if (config) {
        const formattedConfig = {
          icon: config.icon || '',
          title: config.title || '',
          tag: config.tag || '',
          tagType: config.tagType || 'primary',
          rewardPoints: config.rewardPoints || 10,
          requirementText: config.requirementText || '',
          minValue: config.minValue ? Number(config.minValue) : null,
          unit: config.unit || '',
          keywords: config.keywords || [],
          excludeKeywords: config.excludeKeywords || [],
          dailyLimit: config.dailyLimit !== undefined ? config.dailyLimit : 3,
          bonusStep: config.bonusStep ? Number(config.bonusStep) : null,
          bonusPercentage: config.bonusPercentage ? Number(config.bonusPercentage) : null
        }
        
        // 更新store
        updateSceneConfig(sceneType, formattedConfig)
        return formattedConfig
      }
    } catch (error) {
      console.error(`加载场景配置失败 (${sceneType}):`, error)
      // 如果加载失败，返回store中的配置
      return getSceneConfig(sceneType)
    }
  }

  // 重置为默认配置（从后端重新加载）
  const resetToDefault = async (sceneType) => {
    try {
      if (sceneType) {
        await loadSceneConfig(sceneType)
      } else {
        await loadAllConfigs()
      }
    } catch (error) {
      console.error('重置配置失败:', error)
    }
  }

  return {
    sceneConfigs,
    getSceneConfig,
    updateSceneConfig,
    setAllConfigs,
    resetToDefault,
    loadAllConfigs,
    loadSceneConfig
  }
})
