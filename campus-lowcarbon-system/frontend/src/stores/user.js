import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  // State
  const token = ref(localStorage.getItem('token') || '')
  const userInfo = ref({
    name: localStorage.getItem('userName') || '',
    studentId: localStorage.getItem('studentId') || '',
    avatar: localStorage.getItem('avatar') || ''
  })
  const role = ref(localStorage.getItem('role') || '') // 'student' 或 'admin'

  // 登录
  const login = async (form) => {
    try {
      // 调用后端登录接口
      const response = await loginApi(form)
      
      // 从响应中获取数据
      const { token: responseToken, role: responseRole, userInfo: responseUserInfo } = response.data

      // 更新 state
      token.value = responseToken
      role.value = responseRole
      userInfo.value = {
        name: responseUserInfo.name,
        studentId: responseUserInfo.studentId,
        avatar: responseUserInfo.avatar || ''
      }

      // 持久化到 localStorage
      localStorage.setItem('token', responseToken)
      localStorage.setItem('role', responseRole)
      localStorage.setItem('studentId', responseUserInfo.studentId)
      localStorage.setItem('userName', responseUserInfo.name)
      if (responseUserInfo.avatar) {
        localStorage.setItem('avatar', responseUserInfo.avatar)
      }

      return {
        token: responseToken,
        role: responseRole,
        userInfo: userInfo.value
      }
    } catch (error) {
      // 如果请求失败，抛出错误
      throw error
    }
  }

  // 退出登录
  const logout = () => {
    token.value = ''
    role.value = ''
    userInfo.value = {
      name: '',
      studentId: '',
      avatar: ''
    }
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('studentId')
    localStorage.removeItem('userName')
    localStorage.removeItem('avatar')
  }

  // 判断是否是管理员
  const isAdmin = () => {
    return role.value === 'admin'
  }

  // 判断是否是学生
  const isStudent = () => {
    return role.value === 'student'
  }

  return {
    token,
    userInfo,
    role,
    login,
    logout,
    isAdmin,
    isStudent
  }
})

