<template>
  <div id="app">
    <router-view />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'

// 阻止非输入元素获得焦点，防止显示编辑光标
const handleFocus = (e) => {
  const target = e.target
  
  // 检查是否是真正的输入元素
  const isInputElement = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
  const isContentEditable = target.getAttribute('contenteditable') === 'true'
  
  // 检查是否在输入元素内部（包括 Element Plus 组件）
  const isInsideInput = target.closest('input, textarea, [contenteditable="true"]')
  // Element Plus 输入框相关的所有元素
  const isInsideElInput = target.closest('.el-input, .el-textarea, .el-input__wrapper, .el-input__inner, .el-textarea__inner, .el-form-item')
  
  // 如果是输入相关元素，允许获得焦点
  if (isInputElement || isContentEditable || isInsideInput || isInsideElInput) {
    return
  }
  
  // 否则移除焦点
  target.blur()
  // 如果焦点被移到了body上，也移除
  if (document.activeElement === target || document.activeElement === document.body) {
    document.activeElement?.blur()
  }
}

onMounted(() => {
  // 监听焦点事件
  document.addEventListener('focusin', handleFocus, true)
})

onUnmounted(() => {
  // 清理事件监听
  document.removeEventListener('focusin', handleFocus, true)
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  width: 100%;
  height: 100vh;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Arial, sans-serif;
}

/* 禁止非输入元素显示编辑光标 */
*:not(input):not(textarea):not([contenteditable="true"]) {
  caret-color: transparent;
}

/* 禁止非输入元素获得焦点时显示光标 */
*:not(input):not(textarea):not([contenteditable="true"]):focus {
  outline: none;
  caret-color: transparent;
}

/* 确保所有输入框内的光标正常显示 */
input,
textarea,
[contenteditable="true"] {
  caret-color: auto !important;
}

/* Element Plus 输入框内的真正输入元素 */
.el-input input,
.el-textarea textarea {
  caret-color: auto !important;
}

/* 允许文本选择，但禁止编辑光标 */
body {
  -webkit-user-select: text;
  -moz-user-select: text;
  -ms-user-select: text;
  user-select: text;
}
</style>
