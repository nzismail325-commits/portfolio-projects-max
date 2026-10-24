/*
 * panel/vendor/vue.mjs —— Vue 全局构建的 ESM 转发层
 *
 * index.html 用 <script> 加载 UMD 版（window.Vue / window.ElementPlus），业务
 * 代码用 ESM 写。这里把全局对象转成模块导出，两边都不需要打包器。
 */
const Vue = window.Vue;
const ElementPlus = window.ElementPlus;

if (!Vue) {
  throw new Error("Vue 未加载：请检查 /vendor/vue.global.prod.js");
}

export const {
  createApp, reactive, readonly, ref, computed, watch, watchEffect,
  onMounted, onUnmounted, onBeforeUnmount, nextTick, h, defineComponent,
  toRefs, toRef, markRaw, shallowRef, provide, inject,
} = Vue;

export default Vue;

export const ElPlus = ElementPlus;
export const ElMessage = ElementPlus?.ElMessage;
export const ElMessageBox = ElementPlus?.ElMessageBox;
export const ElNotification = ElementPlus?.ElNotification;
