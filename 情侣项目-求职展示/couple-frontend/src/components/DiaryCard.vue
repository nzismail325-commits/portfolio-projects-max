<template>
  <article :class="['diary-card', { deleting: diary._deleting, updating: diary._updating }]">
    <header class="card-header">
      <div class="author-info">
        <img :src="avatarUrl(diary.author.avatar)" :alt="diary.author.name" class="avatar" loading="lazy" decoding="async" />
        <span class="author-name">{{ diary.author.name }}</span>
      </div>
      <div class="card-meta">
        <span class="date">{{ formattedDate }}</span>
        <component :is="weatherIcon" :size="18" class="weather-icon" />
      </div>
    </header>
    <div class="card-body">
      <h2 class="card-title">{{ diary.title }}</h2>
      <p class="card-excerpt">{{ diary.content }}</p>
    </div>
    <footer class="card-footer">
      <div class="tags">
        <span v-for="tag in diary.tags" :key="tag" class="tag">{{ tag }}</span>
      </div>
      <div class="card-actions">
        <template v-if="diary.author.id === currentUserId && !diary._deleting && !diary._updating">
          <button @click="$emit('edit', diary)" class="card-action-btn">
            <Pencil :size="16" /> 编辑
          </button>
          <button @click="$emit('delete', diary.id)" class="card-action-btn delete">
            <Trash2 :size="16" /> 删除
          </button>
        </template>
      </div>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { Sun, Cloud, CloudRain, CloudSnow, Pencil, Trash2 } from 'lucide-vue-next'

const props = defineProps({
  diary: { type: Object, required: true },
  currentUserId: { type: Number, required: true }
})

defineEmits(['delete', 'edit'])

const formattedDate = computed(() =>
  props.diary.timestamp
    ? new Date(props.diary.timestamp).toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
    : ''
)

const weatherIcon = computed(
  () =>
    ({
      sun: Sun,
      cloud: Cloud,
      rain: CloudRain,
      snow: CloudSnow
    })[props.diary.weather] || Sun
)

const avatarUrl = (url) =>
  !url || url.startsWith('http') || url.startsWith('blob:') || url.startsWith('/') ? url : `/${url}`
</script>

<style scoped>
.diary-card {
  background-color: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 2rem;
  transition:
    transform 0.3s ease,
    border-color 0.3s ease,
    box-shadow 0.3s ease;
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
}
.diary-card:hover {
  border-color: rgba(255, 255, 255, 0.6);
  transform: translateY(-5px);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
}
.diary-card.deleting {
  opacity: 0;
  transform: translate3d(0, 18px, 0);
  pointer-events: none;
}
.diary-card.updating {
  border-color: var(--color-accent-primary);
  box-shadow: 0 0 25px rgba(209, 163, 164, 0.5);
  animation: card-update 1.5s ease;
  pointer-events: none;
}
@keyframes card-update {
  0% { transform: scale(1); }
  50% { transform: scale(1.01); }
  100% { transform: scale(1); }
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.author-info {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}
.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid var(--color-accent-primary);
  object-fit: cover;
}
.author-name {
  font-weight: 600;
  color: #fff;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.6);
}
.card-body {
  margin-bottom: 1.5rem;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 0.5rem;
}
.card-title {
  font-size: 1.5rem;
  font-family: 'Lora', serif;
  margin: 0 0 0.8rem;
  color: var(--color-accent-secondary);
}
.card-excerpt {
  color: rgba(255, 255, 255, 0.8);
  line-height: 1.7;
}
.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tags {
  display: flex;
  gap: 0.5rem;
}
.card-actions {
  display: flex;
  gap: 0.8rem;
}
.tag {
  background-color: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  font-size: 0.8rem;
}
.card-action-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: rgba(255, 255, 255, 0.7);
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.3s ease;
}
.card-action-btn:hover {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.card-action-btn.delete:hover {
  background-color: rgba(255, 82, 82, 0.2);
  border-color: rgba(255, 82, 82, 0.5);
  color: #ff8a8a;
}
@media (max-width: 768px) {
  .diary-card {
    padding: 1rem;
    transition:
      transform 0.25s ease,
      border-color 0.25s ease;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  .diary-card:hover {
    transform: none;
    box-shadow: none;
  }
  .diary-card.deleting {
    transform: translate3d(0, 14px, 0);
  }
  .diary-card.updating {
    box-shadow: none;
  }
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.8rem;
  }
  .card-title {
    font-size: 1.3rem;
  }
  .card-excerpt {
    font-size: 0.95rem;
  }
  .card-footer {
    align-items: center;
  }
}
</style>
