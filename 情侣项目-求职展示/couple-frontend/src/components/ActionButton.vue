<template>
  <button
    :class="[
      'action-button',
      {
        disabled: disabled,
        completed: completed,
        'can-perform': !disabled && !completed,
        'has-bonus': hasOnlineBonus && !disabled && !completed,
        compact: compact
      }
    ]"
    :disabled="disabled"
    @click="handleClick"
  >
    <div class="action-icon">{{ icon }}</div>
    <div class="action-content">
      <div class="action-name">{{ name }}</div>
      <div class="action-description">
        {{ description }}
        <span v-if="hasOnlineBonus && !disabled && !completed" class="bonus-indicator">⚡ 1.5x加成</span>
      </div>
    </div>
    <div class="action-status">
      <div v-if="completed" class="status-completed">✓</div>
      <div v-else-if="disabled" class="status-disabled">🔒</div>
      <div v-else class="status-available">→</div>
    </div>
  </button>
</template>

<script setup>
const props = defineProps({
  icon: { type: String, required: true },
  name: { type: String, required: true },
  description: { type: String, required: true },
  disabled: { type: Boolean, default: false },
  completed: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  hasOnlineBonus: { type: Boolean, default: false }
})

const emit = defineEmits(['click'])

const handleClick = () => {
  if (!props.disabled && !props.completed) {
    emit('click')
  }
}
</script>

<style scoped>
.action-button {
  display: flex;
  align-items: center;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  color: #fff;
  cursor: pointer;
  transition: all 0.3s ease;
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  width: 100%;
  text-align: left;
}
.action-button:hover:not(.disabled):not(.completed) {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}
.action-button.can-perform {
  border-color: rgba(74, 222, 128, 0.5);
  background: rgba(74, 222, 128, 0.1);
  animation: actionPulse 2s ease-in-out infinite;
}
.action-button.can-perform:hover {
  background: rgba(74, 222, 128, 0.2);
  box-shadow: 0 4px 15px rgba(74, 222, 128, 0.3);
}
.action-button.has-bonus {
  border-color: rgba(255, 215, 0, 0.6);
  background: rgba(255, 215, 0, 0.1);
  box-shadow: 0 0 15px rgba(255, 215, 0, 0.3);
}
.action-button.has-bonus:hover {
  background: rgba(255, 215, 0, 0.2);
  box-shadow: 0 4px 20px rgba(255, 215, 0, 0.4);
}
.action-button.completed {
  background: rgba(34, 197, 94, 0.2);
  border-color: rgba(34, 197, 94, 0.5);
  cursor: default;
  animation: completedGlow 1s ease-out;
}
.action-button.disabled {
  background: rgba(107, 114, 128, 0.2);
  border-color: rgba(107, 114, 128, 0.3);
  cursor: not-allowed;
  opacity: 0.6;
}
.action-icon {
  font-size: 1.5rem;
  margin-right: 1rem;
  flex-shrink: 0;
}
.action-content {
  flex: 1;
  min-width: 0;
}
.action-name {
  font-weight: 600;
  font-size: 1rem;
  margin-bottom: 0.25rem;
}
.action-description {
  font-size: 0.8rem;
  opacity: 0.8;
  line-height: 1.2;
}
.bonus-indicator {
  display: block;
  color: gold;
  font-size: 0.7rem;
  font-weight: 700;
  margin-top: 0.2rem;
  text-shadow: 0 0 5px rgba(255, 215, 0, 0.5);
}
.action-status {
  margin-left: 1rem;
  flex-shrink: 0;
}
.status-completed {
  color: #22c55e;
  font-size: 1.2rem;
  font-weight: 700;
}
.status-disabled {
  color: #6b7280;
  font-size: 1rem;
}
.status-available {
  color: #4ade80;
  font-size: 1.2rem;
  font-weight: 700;
}
.action-button.compact {
  flex-direction: column;
  padding: 0.8rem 0.5rem;
  text-align: center;
  min-height: 80px;
  position: relative;
}
.action-button.compact .action-icon {
  margin-right: 0;
  margin-bottom: 0.3rem;
  font-size: 1.2rem;
}
.action-button.compact .action-content { flex: none; }
.action-button.compact .action-name {
  font-size: 0.7rem;
  margin-bottom: 0.1rem;
  line-height: 1.1;
}
.action-button.compact .action-description {
  font-size: 0.6rem;
  opacity: 0.7;
  line-height: 1.1;
}
.action-button.compact .action-status {
  margin-left: 0;
  margin-top: 0.2rem;
  position: absolute;
  top: 0.3rem;
  right: 0.3rem;
}
.action-button.compact .status-completed,
.action-button.compact .status-disabled,
.action-button.compact .status-available {
  font-size: 0.8rem;
}
@keyframes actionPulse {
  0%, 100% { box-shadow: 0 0 rgba(74, 222, 128, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
}
@keyframes completedGlow {
  0% { box-shadow: 0 0 rgba(34, 197, 94, 0.6); }
  50% { box-shadow: 0 0 0 10px rgba(34, 197, 94, 0.2); }
  100% { box-shadow: 0 0 rgba(34, 197, 94, 0); }
}
@media (max-width: 768px) {
  .action-button { padding: 0.8rem; }
  .action-icon {
    font-size: 1.3rem;
    margin-right: 0.8rem;
  }
  .action-name { font-size: 0.9rem; }
  .action-description { font-size: 0.75rem; }
}
</style>
