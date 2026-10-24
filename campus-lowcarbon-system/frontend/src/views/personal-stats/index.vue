<template>
  <div class="personal-stats-page">
    <PersonalStats />
  </div>
</template>

<script setup>
import PersonalStats from '@/views/dashboard/components/PersonalStats.vue'
</script>

<style scoped>
.personal-stats-page {
  padding: 24px;
  background: linear-gradient(180deg, #f0f9f8 0%, #f5f7fa 100%);
  min-height: calc(100vh - 60px);
}
</style>

