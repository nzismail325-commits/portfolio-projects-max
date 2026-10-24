import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'

/**
 * 游戏化资产管理 Store
 * 集中管理积分、称号、勋章等游戏化数据
 */
export const useGameStore = defineStore('game', () => {
  // ==================== State ====================

  // 用户碳积分
  const userPoints = ref(2580)

  // 用户统计数据
  const userStats = reactive({
    walkCheckins: 0,      // 健步走打卡次数
    plateCheckins: 0,     // 光盘行动打卡次数
    rideCheckins: 0,      // 骑行打卡次数
    transitCheckins: 0,   // 公共交通打卡次数
    totalCheckins: 0      // 总打卡次数
  })

  // 称号列表 (含等级系统: level 0=未解锁, 1-5=等级)
  const titles = reactive([
    { id: 1, name: '低碳萌新', icon: '🌱', baseCost: 100, level: 2, isOwned: true, isEquipped: false },
    { id: 2, name: '环保先锋', icon: '🌿', baseCost: 150, level: 1, isOwned: true, isEquipped: false },
    { id: 3, name: '减排达人', icon: '♻️', baseCost: 200, level: 0, isOwned: false, isEquipped: false },
    { id: 4, name: '绿色领主', icon: '🌲', baseCost: 250, level: 4, isOwned: true, isEquipped: true },
    { id: 5, name: '地球卫士', icon: '🌍', baseCost: 300, level: 0, isOwned: false, isEquipped: false },
    { id: 6, name: '碳中和大使', icon: '⚡', baseCost: 400, level: 1, isOwned: true, isEquipped: false },
    { id: 7, name: '自然之子', icon: '🦋', baseCost: 500, level: 0, isOwned: false, isEquipped: false },
    { id: 8, name: '盖亚传说', icon: '👑', baseCost: 800, level: 0, isOwned: false, isEquipped: false }
  ])

  // 勋章列表 (按系列分类，同系列只能佩戴一个)
  const badges = reactive([
    // 光盘系列 - type: 'plate'
    { id: 1, name: '粒粒皆辛苦', icon: '🍚', type: 'plate', target: 1, statKey: 'plateCheckins', desc: '完成首次光盘打卡', isOwned: true, isEquipped: true },
    { id: 2, name: '惜食如金', icon: '🥗', type: 'plate', target: 10, statKey: 'plateCheckins', desc: '累计光盘打卡10次', isOwned: true, isEquipped: false },
    { id: 3, name: '光盘王者', icon: '🍽️', type: 'plate', target: 50, statKey: 'plateCheckins', desc: '累计光盘打卡50次', isOwned: false, isEquipped: false },
    { id: 4, name: '净坛使者', icon: '👑', type: 'plate', target: 100, statKey: 'plateCheckins', desc: '累计光盘打卡100次', isOwned: false, isEquipped: false },

    // 健步系列 - type: 'walk'
    { id: 5, name: '迈出第一步', icon: '👣', type: 'walk', target: 1, statKey: 'walkCheckins', desc: '完成首次健步走打卡', isOwned: true, isEquipped: true },
    { id: 6, name: '日行千里', icon: '🦶', type: 'walk', target: 10, statKey: 'walkCheckins', desc: '累计健步走打卡10次', isOwned: false, isEquipped: false },
    { id: 7, name: '健步如飞', icon: '🏃', type: 'walk', target: 50, statKey: 'walkCheckins', desc: '累计健步走打卡50次', isOwned: false, isEquipped: false },
    { id: 8, name: '马拉松达人', icon: '🏅', type: 'walk', target: 100, statKey: 'walkCheckins', desc: '累计健步走打卡100次', isOwned: false, isEquipped: false },

    // 骑行系列 - type: 'ride'
    { id: 9, name: '骑行初体验', icon: '🚴', type: 'ride', target: 1, statKey: 'rideCheckins', desc: '完成首次骑行打卡', isOwned: true, isEquipped: true },
    { id: 10, name: '风驰电掣', icon: '🚲', type: 'ride', target: 20, statKey: 'rideCheckins', desc: '累计骑行打卡20次', isOwned: false, isEquipped: false },
    { id: 11, name: '绿色骑士', icon: '🏍️', type: 'ride', target: 50, statKey: 'rideCheckins', desc: '累计骑行打卡50次', isOwned: false, isEquipped: false },

    // 综合成就 - type: 'general'
    { id: 12, name: '初出茅庐', icon: '🌟', type: 'general', target: 10, statKey: 'totalCheckins', desc: '累计打卡10次', isOwned: true, isEquipped: false },
    { id: 13, name: '坚持不懈', icon: '💪', type: 'general', target: 30, statKey: 'totalCheckins', desc: '累计打卡30次', isOwned: true, isEquipped: true },
    { id: 14, name: '低碳达人', icon: '🏆', type: 'general', target: 100, statKey: 'totalCheckins', desc: '累计打卡100次', isOwned: false, isEquipped: false },
    { id: 15, name: '环保大师', icon: '🎖️', type: 'general', target: 200, statKey: 'totalCheckins', desc: '累计打卡200次', isOwned: false, isEquipped: false }
  ])

  // 等级名称映射
  const levelNames = ['未解锁', '初级', '进阶', '精通', '大师', '传说']

  // ==================== Getters ====================

  // 所有佩戴中的称号 (数组，支持多选)
  const equippedTitles = computed(() => {
    return titles.filter(t => t.isEquipped)
  })

  // 所有佩戴中的勋章 (数组，跨系列可共存)
  const equippedBadges = computed(() => {
    return badges.filter(b => b.isEquipped)
  })

  // 当前佩戴的称号 (兼容旧逻辑，返回第一个)
  const equippedTitle = computed(() => {
    return titles.find(t => t.isEquipped) || null
  })

  // 当前佩戴的勋章 (兼容旧逻辑，返回第一个用于主展示)
  const equippedBadge = computed(() => {
    return badges.find(b => b.isEquipped) || null
  })

  // 所有已获得的勋章
  const earnedBadges = computed(() => {
    return badges.filter(b => b.isOwned)
  })

  // 当前最高称号等级
  const maxTitleLevel = computed(() => {
    return Math.max(...titles.map(t => t.level), 0)
  })

  // 已解锁称号数量
  const unlockedTitlesCount = computed(() => {
    return titles.filter(t => t.isOwned).length
  })

  // 已拥有勋章数量
  const ownedBadgesCount = computed(() => {
    return badges.filter(b => b.isOwned).length
  })

  // 可升级/解锁的称号数量 (用于全局侧边栏通知)
  // 策略: "Next Step Principle" - 每个称号系列只计一次
  // 即使积分能连升多级，也只算 1 条提示
  const canUpgradeTitlesCount = computed(() => {
    let count = 0
    for (const item of titles) {
      // 已满级 (Lv.5) 跳过
      if (item.level >= 5) continue

      // 计算下一级所需积分:
      // - level === 0: nextCost = baseCost (首次解锁)
      // - level 1~4:   nextCost = baseCost * 2^level
      const nextCost = item.level === 0
        ? item.baseCost
        : item.baseCost * Math.pow(2, item.level)

      // 积分足够 → 该称号系列计为 1
      if (userPoints.value >= nextCost) {
        count++
      }
    }
    return count
  })

  // 可解锁的勋章数量 (用于全局侧边栏通知)
  const canUnlockBadgesCount = computed(() => {
    return badges.filter(b => {
      // 未拥有 && 达成条件
      return !b.isOwned && userStats[b.statKey] >= b.target
    }).length
  })

  // ==================== Actions ====================

  /**
   * 解锁/升级称号
   * @param {number} id - 称号ID
   * @returns {boolean} 是否成功
   */
  const unlockTitle = (id) => {
    const title = titles.find(t => t.id === id)
    if (!title) return false

    // 已满级
    if (title.level >= 5) return false

    // 计算升级费用: baseCost * 2^currentLevel
    const cost = title.baseCost * Math.pow(2, title.level)

    // 积分不足
    if (userPoints.value < cost) return false

    // 扣分、升级
    userPoints.value -= cost
    title.level += 1

    // 首次解锁时标记为已拥有
    if (title.level === 1) {
      title.isOwned = true
    }

    return true
  }

  /**
   * 佩戴/卸下称号 (多选，Toggle 模式)
   * @param {number} id - 称号ID
   */
  const equipTitle = (id) => {
    const target = titles.find(t => t.id === id)
    if (!target || !target.isOwned) return

    // Toggle: 切换当前称号的佩戴状态
    target.isEquipped = !target.isEquipped
  }

  /**
   * 卸下称号
   * @param {number} id - 称号ID
   */
  const unequipTitle = (id) => {
    const target = titles.find(t => t.id === id)
    if (target) {
      target.isEquipped = false
    }
  }

  /**
   * 佩戴勋章 (同系列互斥)
   * @param {number} id - 勋章ID
   */
  const equipBadge = (id) => {
    const target = badges.find(b => b.id === id)
    if (!target || !target.isOwned) return

    // 同系列的其他勋章设为未佩戴
    badges.forEach(b => {
      if (b.type === target.type) {
        b.isEquipped = b.id === id
      }
    })
  }

  /**
   * 卸下勋章
   * @param {number} id - 勋章ID
   */
  const unequipBadge = (id) => {
    const target = badges.find(b => b.id === id)
    if (target) {
      target.isEquipped = false
    }
  }

  /**
   * 解锁勋章
   * @param {number} id - 勋章ID
   * @returns {boolean} 是否成功
   */
  const unlockBadge = (id) => {
    const badge = badges.find(b => b.id === id)
    if (!badge || badge.isOwned) return false

    // 检查是否达成条件
    if (userStats[badge.statKey] < badge.target) return false

    badge.isOwned = true
    return true
  }

  /**
   * 判断勋章是否可解锁
   * @param {object} badge - 勋章对象
   * @returns {boolean}
   */
  const canUnlockBadge = (badge) => {
    return userStats[badge.statKey] >= badge.target
  }

  /**
   * 获取勋章进度百分比
   * @param {object} badge - 勋章对象
   * @returns {number} 0-100
   */
  const getBadgeProgress = (badge) => {
    return Math.min((userStats[badge.statKey] / badge.target) * 100, 100)
  }

  /**
   * 获取称号升级费用
   * @param {object} title - 称号对象
   * @returns {number}
   */
  const getTitleUpgradeCost = (title) => {
    return title.baseCost * Math.pow(2, title.level)
  }

  /**
   * 获取等级名称
   * @param {number} level - 等级数字
   * @returns {string}
   */
  const getLevelName = (level) => {
    return levelNames[level] || '未知'
  }

  /**
   * 按类型获取勋章列表
   * @param {string} type - 勋章类型
   * @returns {array}
   */
  const getBadgesByType = (type) => {
    return badges.filter(b => b.type === type)
  }

  /**
   * 获取指定类型当前佩戴的勋章
   * @param {string} type - 勋章类型
   * @returns {object|null}
   */
  const getEquippedBadgeByType = (type) => {
    return badges.find(b => b.type === type && b.isEquipped) || null
  }

  /**
   * 增加用户积分
   * @param {number} points - 积分数量
   */
  const addPoints = (points) => {
    userPoints.value += points
  }

  /**
   * 增加打卡统计
   * @param {string} statKey - 统计字段名
   * @param {number} count - 增加数量，默认1
   */
  const incrementStat = (statKey, count = 1) => {
    if (userStats[statKey] !== undefined) {
      userStats[statKey] += count
      // 同时增加总打卡次数
      if (statKey !== 'totalCheckins') {
        userStats.totalCheckins += count
      }
    }
  }

  return {
    // State
    userPoints,
    userStats,
    titles,
    badges,
    levelNames,

    // Getters
    equippedTitles,
    equippedBadges,
    equippedTitle,
    equippedBadge,
    earnedBadges,
    maxTitleLevel,
    unlockedTitlesCount,
    ownedBadgesCount,
    canUpgradeTitlesCount,
    canUnlockBadgesCount,

    // Actions
    unlockTitle,
    equipTitle,
    unequipTitle,
    equipBadge,
    unequipBadge,
    unlockBadge,
    canUnlockBadge,
    getBadgeProgress,
    getTitleUpgradeCost,
    getLevelName,
    getBadgesByType,
    getEquippedBadgeByType,
    addPoints,
    incrementStat
  }
})

