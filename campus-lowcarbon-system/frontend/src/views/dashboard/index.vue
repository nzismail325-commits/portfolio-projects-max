<template>
  <div class="dashboard-page">
    <!-- 根据角色显示不同面板 -->
    <AdminPanel v-if="userStore.role === 'admin'" />
    <StudentPanel v-else />
  </div>
</template>

<script setup>
import { useUserStore } from '@/stores/user'
import AdminPanel from './components/AdminPanel.vue'
import StudentPanel from './components/StudentPanel.vue'

const userStore = useUserStore()
</script>

<style scoped>
.dashboard-page {
  width: 100%;
  min-height: 100%;
}
</style>
