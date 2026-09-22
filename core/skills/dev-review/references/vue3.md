# Vue 3 Review Profile

结合 context 中真实 Vue 与 vue-router 版本检查：

- ref/reactive 读写、解构导致响应性丢失、模板自动解包假设。
- watch/watchEffect 依赖、flush/immediate、副作用清理、异步乱序和 stale state。
- computed 副作用；composable 生命周期、模块级共享状态污染。
- onMounted/onUnmounted 中 listener、timer、subscription/request 清理。
- props mutation、emits 声明与 payload、组件 `v-model` 参数/事件契约。
- template ref 时机、Pinia/store 数据流、provide/inject 默认值和作用域。
- 是否使用超出项目实际 Vue 3 小版本的 API。

不要把可接受的 ref/reactive 风格差异当成 Finding。
