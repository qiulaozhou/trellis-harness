# Vue 2 Review Profile

结合 context 中真实 Vue 与 vue-router 版本检查：

- 新增对象属性是否需要 `Vue.set` / `this.$set`；数组索引或 length 直接修改是否丢失响应。
- direct prop mutation；computed 是否有副作用；watch/deep/immediate 是否造成重复或意外执行。
- beforeDestroy/destroyed 中 timer、DOM listener、Event Bus、subscription 清理。
- mixin 名称冲突和隐式依赖；Vuex mutation/action 边界与直接 state mutation。
- `v-for` key 稳定性；slot/scoped-slot 数据契约；`$refs` 生命周期和 `$nextTick` 时机。
- 是否误用 Vue 3-only API，或使用超出项目实际 Vue 2 小版本能力的 API。

不要机械要求所有属性都用 `$set`；只有运行时向已观测对象新增属性且模板/计算依赖它时才报。
