import { ref } from 'vue'

// 登录页"正在进入"状态：进入登录页时重置
export const justLoggedIn = ref(true)
export const lastLoggedInUser = ref(null)

export const resetLoginState = () => {
  justLoggedIn.value = true
  lastLoggedInUser.value = null
}
