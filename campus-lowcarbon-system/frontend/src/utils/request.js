import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import router from '@/router'

// 全局变量，用于防止报错刷屏和重复跳转
export const isRelogin = { show: false }

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api', // API 基础路径
  timeout: 5000 // 请求超时时间
})

// 请求拦截器
request.interceptors.request.use(
  config => {
    // 从 localStorage 获取 token 并添加到请求头
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  response => {
    const res = response.data
    
    // 根据业务约定的状态码进行处理
    if (res.code !== 200) {
      // 业务错误：标记为业务错误，但不在这里显示（由具体页面处理）
      // 封禁错误会在登录页面特殊处理，次数限制错误由打卡页面处理，其他错误使用默认的ElMessage显示
      const error = new Error(res.message || '请求失败')
      error.isBusinessError = true // 标记为业务错误
      error.code = res.code // 保存错误码
      
      // 特殊处理 401 未授权情况 (后端可能返回 code=401)
      if (res.code === 401) {
        // 检查是否是封禁错误
        const isBanError = res.message && (
          res.message.includes('账号已被封禁') || 
          res.message.includes('被封禁') ||
          res.message.includes('封禁原因')
        )
        
        if (isBanError) {
          // 封禁错误：显示封禁提示并跳转登录页
          if (!isRelogin.show) {
            isRelogin.show = true
            const banReasonMatch = res.message.match(/封禁原因[：:]([^。]+)/)
            const banReason = banReasonMatch ? banReasonMatch[1].trim() : ''
            
            let message = '账号已被封禁'
            if (banReason) {
              message = `账号已被封禁\n\n封禁原因：\n${banReason}\n\n请联系管理员处理。`
            } else {
              message = '账号已被封禁，请联系管理员'
            }
            
            ElMessageBox.alert(message, '账号封禁提示', {
              type: 'error',
              confirmButtonText: '我知道了',
              showClose: true,
              closeOnClickModal: false,
              closeOnPressEscape: true
            }).then(() => {
              isRelogin.show = false
              localStorage.clear()
              router.push('/login')
            }).catch(() => {
              isRelogin.show = false
              localStorage.clear()
              router.push('/login')
            })
          }
        } else {
          // Token过期：显示重新登录提示
          if (!isRelogin.show) {
            isRelogin.show = true
            ElMessageBox.confirm('登录状态已失效，请重新登录', '系统提示', {
              confirmButtonText: '重新登录',
              cancelButtonText: '取消',
              type: 'warning'
            }).then(() => {
              isRelogin.show = false
              localStorage.clear()
              router.push('/login')
            }).catch(() => {
              isRelogin.show = false
            })
          }
        }
        return Promise.reject(error)
      }

      // 封禁错误不在拦截器中显示，由登录页面特殊处理
      // 次数限制错误（403）不在拦截器中显示，由打卡页面处理
      // 检查是否包含封禁相关关键词
      const isBanError = res.message && (
        res.message.includes('账号已被封禁') || 
        res.message.includes('被封禁') ||
        res.message.includes('封禁原因')
      )
      // 检查是否是次数限制错误（403）
      const isLimitError = res.code === 403 || (res.message && (
        res.message.includes('次数已达上限') ||
        res.message.includes('打卡次数已达上限')
      ))
      
      if (!isBanError && !isLimitError) {
        ElMessage.error(res.message || '请求失败')
      }
      
      return Promise.reject(error)
    }
    
    return res
  },
  error => {
    console.error('响应错误:', error)
    
    // 如果是业务错误（已经在响应拦截器中处理过），不再显示错误消息
    if (error.isBusinessError) {
      return Promise.reject(error)
    }
    
    // 处理 401 未授权 (HTTP状态码)
    if (error.response && error.response.status === 401) {
      // 检查是否是封禁错误
      const errorMessage = error.response.data?.message || ''
      const isBanError = errorMessage && (
        errorMessage.includes('账号已被封禁') || 
        errorMessage.includes('被封禁') ||
        errorMessage.includes('封禁原因')
      )
      
      if (isBanError) {
        // 封禁错误：显示封禁提示并跳转登录页
        if (!isRelogin.show) {
          isRelogin.show = true
          const banReasonMatch = errorMessage.match(/封禁原因[：:]([^。]+)/)
          const banReason = banReasonMatch ? banReasonMatch[1].trim() : ''
          
          let message = '账号已被封禁'
          if (banReason) {
            message = `账号已被封禁\n\n封禁原因：\n${banReason}\n\n请联系管理员处理。`
          } else {
            message = '账号已被封禁，请联系管理员'
          }
          
          ElMessageBox.alert(message, '账号封禁提示', {
            type: 'error',
            confirmButtonText: '我知道了',
            showClose: true,
            closeOnClickModal: false,
            closeOnPressEscape: true
          }).then(() => {
            isRelogin.show = false
            localStorage.clear()
            router.push('/login')
          }).catch(() => {
            isRelogin.show = false
            localStorage.clear()
            router.push('/login')
          })
        }
      } else {
        // Token过期：显示重新登录提示
        if (!isRelogin.show) {
          isRelogin.show = true
          ElMessageBox.confirm('登录状态已失效，请重新登录', '系统提示', {
            confirmButtonText: '重新登录',
            cancelButtonText: '取消',
            type: 'warning'
          }).then(() => {
            isRelogin.show = false
            localStorage.clear()
            router.push('/login')
          }).catch(() => {
            isRelogin.show = false
          })
        }
      }
      return Promise.reject(error)
    }
    
    // 网络错误或其他错误：显示错误消息
    let errorMessage = '网络请求失败'
    if (error.response) {
      // 服务器返回了错误响应
      if (error.response.data && error.response.data.message) {
        errorMessage = error.response.data.message
        // 封禁错误不在错误拦截器中显示，由登录页面特殊处理
        const isBanError = errorMessage && (
          errorMessage.includes('账号已被封禁') || 
          errorMessage.includes('被封禁') ||
          errorMessage.includes('封禁原因')
        )
        if (isBanError) {
          // 如果是401造成的封禁提示，也走登出逻辑
          if (error.response.status === 401) {
             // 已经在上面 401 block 处理了，这里不需要重复
             return Promise.reject(error)
          }
          return Promise.reject(error)
        }
      } else if (error.response.status === 404) {
        errorMessage = '请求的资源不存在（404）'
      } else if (error.response.status === 500) {
        errorMessage = '服务器内部错误（500）'
      } else {
        errorMessage = `请求失败（${error.response.status}）`
      }
    } else if (error.request) {
      // 请求已发出但没有收到响应
      errorMessage = '网络连接失败，请检查网络'
    } else if (error.message) {
      errorMessage = error.message
      // 封禁错误不在错误拦截器中显示
      const isBanError = errorMessage && (
        errorMessage.includes('账号已被封禁') || 
        errorMessage.includes('被封禁') ||
        errorMessage.includes('封禁原因')
      )
      if (isBanError) {
        return Promise.reject(error)
      }
    }
    
    ElMessage.error(errorMessage)
    return Promise.reject(error)
  }
)

export default request
