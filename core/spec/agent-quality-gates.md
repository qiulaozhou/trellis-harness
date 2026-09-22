# Agent Quality Gates

本规范定义可被机器执行、可由 checkpoint/resume 继承的 Task 质量门禁。它是通用
Harness Core，不记录某一个业务项目的 package scripts、build 行为或测试能力。

## 事实来源

- `.trellis/scripts/harness/quality_gate.py` 是唯一 runner，复用 `session_handoff.py` 的 Workspace Snapshot 和 diff fingerprint。
- `.trellis/harness/quality-gates.json` 是检查策略的唯一配置来源；Python 不复制项目检查清单。
- 项目实际 `package.json`、本地 `node_modules/.bin` 和 Task artifacts 决定命令是否可运行，不从模板假设某个项目一定有 lint、typecheck、test 或 build。
- 验证状态只能是 `pass`、`fail`、`blocked`、`skipped`。
- 每次正式 `dev-verify` 只覆盖当前 Task 的 `verification.json`，不维护第二套数据库。

## Verification Scope

Workspace Snapshot 表示整个工作区真实状态，保留 branch、HEAD、dirty、staged、
unstaged、untracked 和 workspace diff fingerprint。Verification Scope 表示本次 Task
Gate 实际负责的 repo-relative 文件。

首次 Gate 前，从 Task Implement/handoff 和本次实际实现核对文件归属，再显式写入：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py scope `
  --task <task-path> `
  --include <repo-relative-file> `
  --include <another-file>
```

`include` 至少一项；重复参数会去重。`exclude` 只记录明确排除项，不能与 include
重叠。路径必须在当前 repository 内。没有可靠显式 scope 时状态为 `ambiguous`，
targeted plan/run 均为 `blocked`；不得使用 mtime、文件名、打开顺序或全部 dirty 文件猜归属。

Scope fingerprint 对 scope 文件保存内容 SHA-256、deleted 状态和 Git 状态，并将
include/exclude 一并稳定序列化后计算 SHA-256；不使用 mtime+size 作为唯一依据。

## Runner 能力

- `git diff --check` 直接调用 Git。
- targeted ESLint、Prettier、TypeScript 和 full TypeScript 只调用当前项目已有的 `node_modules/.bin`；工具缺失为 `blocked`，不得通过 `npm exec` 下载。
- full lint、tests 和 build 调用项目配置的 npm script。当前公开 profile 只保证 npm；其他包管理器需要项目自定义 profile。
- 没有正式 `test` script 时 tests 为 `skipped`，原因是 `no configured test suite`。
- Acceptance Criteria 属于 Trellis Check/finish-work 的 Task 证据。旧 profile 中的 `acceptance-criteria` runner 会 `skipped` 并明确委托关系，不伪造 pass。

## Gate 规则

### Fast Gate

Fast Gate 包含 staged/unstaged `git diff --check`、Verification Scope 内 targeted
ESLint、Prettier 和条件式 TypeScript 检查。没有适用文件的检查为 `skipped`；scope
ambiguous 时 targeted 检查为 `blocked`。

条件式 TypeScript 检查由 scope 内 `.ts`/`.tsx` 文件触发，但执行项目完整
`tsc --noEmit --incremental false --pretty false`；它不是单文件 typecheck，失败范围按
repository 解释。

### Full Gate

Full Gate 包含 Fast Gate，再执行配置启用的完整 lint、完整 TypeScript 和 tests。
Build readiness 默认 optional，且只有显式 `--allow-side-effects` 才执行；未授权时为
`blocked` 并保留 `Build requires explicit side-effect authorization.`，但 optional blocked
不单独阻断 Gate。项目 profile 将 build 标记为 required 时仍会阻断。

### Workspace Stability

runner 在所有检查结束后重新获取 Workspace Snapshot。若 branch、HEAD、workspace 或
diff fingerprint 在 Gate 执行期间变化，自动追加 required `workspace-stability: fail`；
已有检查结果不能绑定到另一个代码状态。`verification.json` 始终保存最终 snapshot，
并另存 `started_snapshot` 供诊断。生成的 Task `verification.json` 本身不属于代码状态，
因此不进入 Workspace Snapshot；否则 artifact 会在写入时令自身立即过期。

## 副作用与结果

`side_effect_level` 只能是 `none`、`repo_write`、`external` 或 `destructive`。Runner 默认
只执行 `none`；其余级别只有显式 `--allow-side-effects` 才可运行。声明为 `none` 的检查
如果改变了工作区，Workspace Stability 会使 Gate 失败。

Overall Gate 规则：任一 check `fail` 则整体 `fail`；没有 fail 但 required check
`blocked` 则整体 `blocked`；否则整体 `pass`。`skipped` 只表示未适用或已明确委托，
不等于该检查已经通过。

## 结果继承

`verification.json` 同时保存最终 workspace snapshot/fingerprint 与 Verification Scope
fingerprint。`quality_gate.py check-current` 分别输出 `workspace_current/workspace_changed`
和 `scope_current/scope_changed`：workspace 仅发生 scope 外变化时，scope 仍可 current；
scope 变化或 ambiguous 时旧验证为 stale。

质量 runner 不安装依赖、不升级 Trellis、不调用外部服务补证据、不提交、不推送、不归档，也不修改业务代码。
