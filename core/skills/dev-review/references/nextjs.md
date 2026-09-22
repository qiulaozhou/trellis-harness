# Next.js Review Profile

本 profile 必须与 `react.md` 一起使用。结合 context 中真实 Next.js/React 版本和
`app`、`pages` 或混合 router 形态检查：

- Server/Client Component 边界、`"use client"`、server component 中 browser API。
- hydration mismatch，以及 server/client 初始数据、时区、随机值和持久化状态不一致。
- fetch cache、revalidate、dynamic/static rendering 是否符合数据新鲜度要求。
- route handler 方法、状态码、缓存、鉴权和序列化语义。
- Server Actions 的输入验证、授权、错误处理与版本可用性。
- 私有环境变量是否泄露到 client bundle。
- metadata/SEO、navigation/redirect 行为、loading/error/not-found boundary。
- 是否把 App Router 规则误用于 Pages Router，或使用超出实际 Next.js 版本的行为。

不要仅因文件位于 client component 就建议迁移到 server；必须有具体边界错误或可证明影响。
