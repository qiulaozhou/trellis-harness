# React Review Profile

结合 context 中真实 React 与 router 版本检查：

- Rules of Hooks、条件调用和稳定调用顺序。
- useEffect 依赖、stale closure、清理、异步竞态和请求取消。
- state mutation、derived/duplicated state、更新时序或批处理假设。
- controlled/uncontrolled 转换、列表 key 与组件 remount 假设。
- useMemo/useCallback 语义正确性；无收益或破坏依赖正确性的 memoization。
- Context value 稳定性和明显的大范围重渲染。
- render-time side effect；event listener、timer、subscription/request 清理。
- 是否使用超出项目实际 React 版本的 API。

不要仅因为函数未 memoize 就报告性能问题；必须有真实高频路径或身份稳定性契约证据。
