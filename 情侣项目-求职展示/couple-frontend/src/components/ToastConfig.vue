<template></template>

<script setup>
// 全局 Toast 配置组件：挂载后把统一风格的 $toast 挂到 window 上
import { onMounted } from 'vue'
import { useToast } from 'vue-toastification'

onMounted(() => {
  const toast = useToast()
  const DEDUPE_WINDOW = 1800
  const lastShownAt = new Map()

  const show = (level, content, options = {}, extra = {}) => {
    const { dedupe = true, ...rest } = extra
    const key = `${level}:${content}`
    const now = Date.now()
    if (dedupe) {
      const last = lastShownAt.get(key) || 0
      if (now - last < DEDUPE_WINDOW) return null
      lastShownAt.set(key, now)
    }
    return toast[level](content, { ...options, ...rest })
  }

  const success = (content, options) =>
    show('success', content, { timeout: 3000, icon: true, closeButton: false }, options)
  const error = (content, options) =>
    show('error', content, { timeout: 4000, icon: true, closeOnClick: true }, options)
  const warning = (content, options) =>
    show('warning', content, { timeout: 5000, icon: true, closeButton: false }, options)
  const info = (content, options) =>
    show('info', content, { timeout: 3000, icon: true, closeButton: false }, options)

  window.$toast = {
    success,
    error,
    warning,
    info,
    dismiss: toast.dismiss.bind(toast),
    clear: toast.clear.bind(toast),
    update: toast.update.bind(toast)
  }
})
</script>
