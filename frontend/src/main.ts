import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from '@/router'
import App from '@/App.vue'

// Global styles (order matters!)
import '@/shared/styles/variables.css'
import '@/shared/styles/reset.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
