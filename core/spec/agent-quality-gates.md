# Agent Quality Gates

本规范定义当前项目可被机器执行、可被 checkpoint/resume 继承的质量门禁。

## 事实来源

- `.trellis/scripts/harness/quality_gate.py` 是唯一 runner，复用 `session_handoff.py` 的 Workspace Snapshot 和 diff fingerprint。
- `.trellis/harness/quality-gates.json` 是检查策略的唯一配置来源；Python 不复制项目检查清单。
- 验证状态只能是 `pass`、`fail`、`blocked`、`skipped`。
- 每次正式 `dev-verify` 只覆盖当前 Task 的 `verification.json`，不维护第二套数据库；Task 目录可用薄的 `verification-scope.json` 明确 targeted verification 归属。

## Workspace Snapshot 与 Verification Scope

Workspace Snapshot 表示整个工作区真实状态，保留 branch、HEAD、dirty、staged、unstaged、untracked 和 workspace diff fingerprint。Verification Scope 表示本次 Task Gate 实际负责的 repo-relative 文件；`include` 必须显式，`exclude` 只能收窄且不能与 include 重叠。现有 Task manifest 无法可靠表达实现文件时，scope 为 `ambiguous`，targeted 检查 blocked，不使用 mtime、打开顺序、文件名或 LLM 猜测归属。

Scope fingerprint 对 scope 文件保存内容 SHA-256、deleted 状态和 Git 状态，并将 include/exclude 一并稳定序列化后计算 SHA-256；不使用 mtime+size 作为唯一依据。

## 当前项目能力

- 包管理器：npm，锁文件为 `package-lock.json`。
- `npm run lint` 调用 `next lint`，其默认目录是 Next.js 配置的项目范围；针对变更文件使用本地 ESLint runner，不能把 targeted lint 宣称为全仓 lint。
- TypeScript 使用根目录 `tsconfig.json`，执行 `tsc --noEmit --incremental false --pretty false`，禁止生成 `tsbuildinfo`。
- Prettier 配置为 `.prettierrc`，只检查受影响且工具支持的文件。
- 当前 `package.json` 没有正式 `test` 脚本，Full Gate 的 tests 必须是 `skipped`，原因是 `no configured test suite`。
- `npm run build` 先运行生产 i18n 脚本，并可能请求外部数据、写语言文件；因此属于 `external`，默认 `blocked`。
- 当前 `.husky/pre-commit` 只有安装脚本和注释，不能把它当作质量门禁；CI 配置也不作为本地已执行证据。

## Gate 规则

### Fast Gate

Fast Gate 包含 staged/unstaged `git diff --check`、Verification Scope 内 targeted ESLint、Verification Scope 内 Prettier 和条件式 TypeScript 检查。没有适用文件的检查为 `skipped`；scope ambiguous 时 targeted 检查为 `blocked`，不能写成 `pass`。

### Full Gate

Full Gate 包含 Fast Gate 的 Git、Verification Scope 内 targeted ESLint、Prettier 和条件式 TypeScript 检查，再执行完整 `npm run lint`、完整 TypeScript 检查、正式 tests、当前 Task 的 Acceptance Criteria 证据检查和 build readiness。没有测试套件时 tests 为 `skipped`；Acceptance Criteria 没有任务级实际证据时为 `blocked`，不能自动通过。Build 需要显式授权，否则必须为 `blocked` 并保留：`Build requires explicit side-effect authorization.`

### 副作用策略

`side_effect_level` 只能是 `none`、`repo_write`、`external` 或 `destructive`。Runner 默认只执行 `none`；其余级别只有显式 `--allow-side-effects` 才可运行。本阶段不授权或执行生产 build。

### 结果继承

`verification.json` 同时保存 `workspace_snapshot/workspace_fingerprint` 与 `verification_scope/scope_fingerprint`。`quality_gate.py check-current` 分别输出 `workspace_current/workspace_changed` 和 `scope_current/scope_changed`：workspace 仅发生 scope 外变化时，workspace 可为 false 但 scope 仍为 true，`previous_verification_may_be_stale` 为 false；scope 变化或 ambiguous 时才标记 stale。旧的 `pass` 不得在 stale 状态下继续作为当前证据。

Overall Gate 规则是：任一 check `fail` 则整体 `fail`；没有 fail 但 required check `blocked` 则整体 `blocked`；否则整体 `pass`。`skipped` 只表示未适用或明确无测试套件，不等于通过。

## 运行限制

质量 runner 不安装依赖、不升级 Trellis、不调用外部服务来补证据，不执行未经授权的 build，不修改业务代码。完整 stdout 只保留有限尾部摘要；详细终端日志不写入 Task Memory。
