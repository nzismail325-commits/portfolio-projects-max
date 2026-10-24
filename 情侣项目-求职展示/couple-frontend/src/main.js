import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import Toast, { POSITION } from 'vue-toastification'
import './assets/styles/main.css'

const app = createApp(App)

app.use(router)

app.use(Toast, {
  position: POSITION.TOP_CENTER,
  timeout: 4000,
  closeOnClick: true,
  pauseOnFocusLoss: true,
  pauseOnHover: true,
  draggable: true,
  draggablePercent: 0.6,
  showCloseButtonOnHover: true,
  hideProgressBar: false,
  closeButton: 'button',
  icon: true,
  rtl: false,
  transition: 'Vue-Toastification__bounce',
  maxToasts: 3,
  newestOnTop: true
})

app.mount('#app')
