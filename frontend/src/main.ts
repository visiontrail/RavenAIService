import { createApp } from 'vue'
import './style.css'
import './styles/markdown.css'
import App from './App.vue'

// 路由
import router from './router'

// 状态管理
import { pinia } from './stores'

// 国际化
import { i18n, getElementLocale } from './i18n'

// Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 官方暗色变量，同样由 html.dark class 驱动
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(router)
app.use(pinia)
app.use(i18n)
// 初始 Element Plus 语言包；切换由 App.vue 的 ElConfigProvider 响应式接管
app.use(ElementPlus, { locale: getElementLocale() })

app.mount('#app')
