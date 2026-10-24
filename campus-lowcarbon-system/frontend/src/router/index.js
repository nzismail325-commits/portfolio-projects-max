import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layout/index.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/login/index.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: Layout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../views/dashboard/index.vue'),
        meta: { requiresAuth: true, title: '首页' }
      },
      {
        path: 'personal-stats',
        name: 'PersonalStats',
        component: () => import('../views/personal-stats/index.vue'),
        meta: { requiresAuth: true, title: '数据统计' }
      },
      {
        path: 'checkin',
        redirect: '/checkin/walk',
        meta: { requiresAuth: true, title: '低碳打卡' },
        children: [
          {
            path: 'walk',
            name: 'CheckinWalk',
            component: () => import('../views/checkin/walk.vue'),
            meta: { requiresAuth: true, title: '低碳健步走' }
          },
          {
            path: 'ride',
            name: 'CheckinRide',
            component: () => import('../views/checkin/ride.vue'),
            meta: { requiresAuth: true, title: '绿色骑行' }
          },
          {
            path: 'plate',
            name: 'CheckinPlate',
            component: () => import('../views/checkin/plate.vue'),
            meta: { requiresAuth: true, title: '光盘行动' }
          },
          {
            path: 'transit',
            name: 'CheckinTransit',
            component: () => import('../views/checkin/transit.vue'),
            meta: { requiresAuth: true, title: '公共交通' }
          }
        ]
      },
      {
        path: 'mall',
        redirect: '/mall/titles',
        meta: { requiresAuth: true, title: '装扮商城' },
        children: [
          {
            path: 'titles',
            name: 'MallTitles',
            component: () => import('../views/mall/index.vue'),
            meta: { requiresAuth: true, title: '荣誉称号' }
          },
          {
            path: 'badges',
            name: 'MallBadges',
            component: () => import('../views/mall/index.vue'),
            meta: { requiresAuth: true, title: '环保勋章' }
          }
        ]
      },
      {
        path: 'advisor',
        name: 'Advisor',
        component: () => import('../views/advisor/index.vue'),
        meta: { requiresAuth: true, title: '智能顾问' }
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/profile/index.vue'),
        meta: { requiresAuth: true, title: '个人中心' }
      },
      {
        path: 'user/info',
        name: 'UserInfo',
        component: () => import('../views/user/info.vue'),
        meta: { requiresAuth: true, title: '个人信息' }
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('../views/notifications/index.vue'),
        meta: { requiresAuth: true, title: '消息通知' }
      },
      {
        path: 'rules',
        name: 'Rules',
        component: () => import('../views/rules/index.vue'),
        meta: { requiresAuth: true, title: '用户风控', icon: 'WarnTriangleFilled', role: 'admin' }
      },
      {
        path: 'review',
        name: 'Review',
        component: () => import('../views/review/index.vue'),
        meta: { requiresAuth: true, title: '异常审核', role: 'admin' }
      },
      {
        path: 'checkin-manage',
        component: () => import('../views/checkin-manage/index.vue'),
        redirect: '/checkin-manage/walk',
        meta: { requiresAuth: true, title: '打卡管理', role: 'admin' },
        children: [
          {
            path: 'walk',
            name: 'CheckinManageWalk',
            component: () => import('../views/checkin-manage/settings.vue'),
            meta: { requiresAuth: true, title: '低碳健步走', role: 'admin', scene: 'walk' }
          },
          {
            path: 'ride',
            name: 'CheckinManageRide',
            component: () => import('../views/checkin-manage/settings.vue'),
            meta: { requiresAuth: true, title: '绿色骑行', role: 'admin', scene: 'ride' }
          },
          {
            path: 'plate',
            name: 'CheckinManagePlate',
            component: () => import('../views/checkin-manage/settings.vue'),
            meta: { requiresAuth: true, title: '光盘行动', role: 'admin', scene: 'plate' }
          },
          {
            path: 'transit',
            name: 'CheckinManageTransit',
            component: () => import('../views/checkin-manage/settings.vue'),
            meta: { requiresAuth: true, title: '公共交通', role: 'admin', scene: 'transit' }
          }
        ]
      },
      {
        path: 'rank',
        name: 'Rank',
        redirect: '/rank/points',
        meta: { requiresAuth: true, title: '低碳风云榜' },
        children: [
          {
            path: 'points',
            name: 'RankPoints',
            component: () => import('../views/rank/index.vue'),
            meta: { requiresAuth: true, title: '积分总榜' }
          },
          {
            path: 'badges',
            name: 'RankBadges',
            component: () => import('../views/rank/index.vue'),
            meta: { requiresAuth: true, title: '勋章达人榜' }
          },
          {
            path: 'titles',
            name: 'RankTitles',
            component: () => import('../views/rank/index.vue'),
            meta: { requiresAuth: true, title: '称号荣耀榜' }
          },
          {
            path: 'checkins',
            name: 'RankCheckins',
            component: () => import('../views/rank/index.vue'),
            meta: { requiresAuth: true, title: '勤奋打卡榜' }
          }
        ]
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  // 获取 token
  const token = localStorage.getItem('token')
  
  // 如果需要认证但没有 token，跳转到登录页
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    // 如果已登录但访问登录页，跳转到 dashboard
    next('/dashboard')
  } else {
    next()
  }
})

export default router
