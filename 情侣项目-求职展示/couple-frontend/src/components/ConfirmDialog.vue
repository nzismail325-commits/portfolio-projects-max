<template>
  <div class="confirm-overlay" @click.self="$emit('cancel')">
    <div class="confirm-content">
      <header class="confirm-header">
        <h2>
          <span class="icon-left">✧</span> {{ title }} <span class="icon-right">✧</span>
        </h2>
      </header>
      <div class="confirm-body">
        <p>{{ message }}</p>
      </div>
      <footer class="confirm-footer">
        <button @click="$emit('cancel')" class="btn-cancel">取消</button>
        <button @click="$emit('confirm')" class="btn-confirm">确认</button>
      </footer>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '确认操作' },
  message: { type: String, required: true }
})

defineEmits(['confirm', 'cancel'])
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  -webkit-backdrop-filter: blur(5px);
  backdrop-filter: blur(5px);
}
.confirm-content {
  background: #2c3e50;
  padding: 1.8rem 2rem;
  border-radius: 12px;
  width: 90%;
  max-width: 360px;
  color: #fff;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
  animation: pop-in 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
}
@keyframes pop-in {
  0% { opacity: 0; transform: scale(0.9); }
  100% { opacity: 1; transform: scale(1); }
}
.confirm-header {
  margin-bottom: 1.2rem;
  padding-bottom: 0.8rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  text-align: center;
}
.confirm-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--color-accent-secondary);
  font-family: KaiTi, 楷体, serif;
  text-shadow: 0 0 10px rgba(227, 197, 152, 0.3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.icon-left,
.icon-right {
  color: var(--color-accent-primary);
  margin: 0 0.8rem;
  opacity: 0.8;
  font-size: 1.2rem;
}
.confirm-body {
  margin-bottom: 1.8rem;
  text-align: center;
}
.confirm-body p {
  margin: 0;
  font-size: 1.1rem;
  line-height: 1.6;
}
.confirm-footer {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.btn-cancel,
.btn-confirm {
  padding: 0.6rem 1.2rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.3s ease;
  font-family: KaiTi, 楷体, serif;
  min-width: 100px;
}
.btn-cancel {
  background-color: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.btn-cancel:hover {
  background-color: rgba(255, 255, 255, 0.2);
}
.btn-confirm {
  background-color: var(--color-accent-primary);
  color: #fff;
}
.btn-confirm:hover {
  background-color: #c19394;
  transform: translateY(-2px);
  box-shadow: 0 5px 15px rgba(209, 163, 164, 0.3);
}
@media (max-width: 768px) {
  .confirm-content {
    padding: 1.5rem;
    max-width: 320px;
  }
  .btn-cancel,
  .btn-confirm {
    flex: 1;
    min-width: 0;
    text-align: center;
  }
}
</style>
