declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

export {}

declare module '@vue/runtime-core' {
  export interface GlobalProperties {
    // 全局属性类型声明
  }
}
