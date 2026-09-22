---
name: dev-verify
description: 对当前已有 Trellis Task 执行可重复的 Fast 或 Full Quality Gate，并保存 machine-readable verification.json；用于实现步骤、调试修复、checkpoint、check 或 finish-work 前的验证。
---

# Dev Verify

先读取 `.trellis/spec/agent-development-harness.md` 和 `.trellis/spec/agent-quality-gates.md`。`dev-verify fast` / `dev-verify full` 是 Skill 意图，不是 shell 命令。不得创建新 Task、切换 workspace、安装依赖或修改业务代码。

## 统一运行时与 Task

依次解析当前环境可用的 `python`、`py`；两者都不可用时，在 Codex 中调用
`load_workspace_dependencies` 读取 bundled Python 路径，不猜测其他机器的绝对路径：

```powershell
$harnessPython = Get-Command python, py -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty Source
```

若仍为空，使用 `load_workspace_dependencies` 返回的 Python executable 设置
`$harnessPython`；不要修改 PATH、安装依赖或复制其他机器的绝对路径。完成解析并确认路径存在后再执行：

```powershell
if (-not $harnessPython -or -not (Test-Path -LiteralPath $harnessPython)) { throw "Python 3.9+ is required." }
& $harnessPython -B -X utf8 .trellis/scripts/task.py current --json
```

确认 `current_task.dir` 是当前用户授权的 active Task，且 `source` 为当前 Session 的 `session:` 来源。没有 active Task 或来源为 `session-fallback:` 时停止，不猜测、不创建任务。

## Fast

适合实现步骤完成、调试修复完成或准备 checkpoint：

1. 获取当前 Task 和 `session_handoff.py snapshot`。
2. 确认 `<task-path>/verification-scope.json` 对应本 Task 当前实现文件。缺失或文件清单已变化时，从 Task Implement/handoff 与本次实际实现中核对 repo-relative 文件清单；不得把 workspace 全部 dirty 文件直接当作 Task 归属。清单明确后执行：

   ```powershell
   & $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py scope `
     --task <task-path> `
     --include <repo-relative-file> `
     --include <another-file>
   ```

   每个 `--include` 只传一个已确认由当前 Task 负责的文件；需要记录明确排除项时重复
   `--exclude <repo-relative-file>`。无法确认归属时停止并报告 `Verification Scope: AMBIGUOUS`，不写 scope。
3. 执行 `quality_gate.py plan fast --task <task-path>`；plan 只展示决策，不执行命令。targeted ESLint、Prettier 和 Fast typecheck 只接受上一步的显式 Verification Scope；scope 不明确时必须 blocked。
4. 执行：

   ```powershell
   & $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py run fast --task <task-path>
   ```

5. runner 将结果写到 `<task-path>/verification.json`，只保留最近一次正式 Gate。
6. 输出 gate、overall status、各 check 状态、最终 snapshot 和 artifact 路径。未执行检查必须是 `skipped` 或 `blocked`，不能声称 `pass`。

## Full

适合实现基本完成、准备 Check 或 finish-work/archive 前：

1. 确认 active Task，不修改任务状态。
2. 执行 `quality_gate.py plan full --task <task-path>`。
3. 执行不带 `--allow-side-effects` 的 Full Gate：

   ```powershell
   & $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py run full --task <task-path>
   ```

4. Acceptance Criteria 由 Trellis Check/finish-work 的任务级证据负责，不在通用 runner 中伪造 pass。旧 profile 中的 `acceptance-criteria` runner 会明确 `skipped` 并说明已委托 Trellis Check。
5. build 或其他非 `none` 检查默认不得运行。默认 profile 的 build readiness 是 optional；未授权时仍输出 `Build requires explicit side-effect authorization.` 并为 `blocked`，但不单独阻断 Full Gate。项目 profile 将 build 标记为 required 时，它仍会阻断。
6. 如果 required check 是 `fail` 或 `blocked`，明确输出 `Full Gate is not complete.`，不得建议 archive 或把结果降级成 pass。

## Workspace Snapshot 与 Verification Scope

`session_handoff.py snapshot` 表示整个工作区真实状态，保留 branch、HEAD、dirty、staged、unstaged、untracked 和 workspace diff fingerprint。Task 的 `verification-scope.json`（repo-relative `include`，可选收窄 `exclude`）表示本次 targeted Gate 负责的文件；没有可靠显式 scope 时为 `verification_scope_status: ambiguous`，不能使用 mtime、排序或自然语言猜测。Scope fingerprint 使用文件内容 SHA-256、deleted 状态和 Git 状态。

## 快照与 stale

需要判断已有 artifact 是否仍可继承时执行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py check-current <task-path>/verification.json
```

输出同时区分 `workspace_current/workspace_changed` 与 `scope_current/scope_changed`。workspace 仅发生 scope 外变化时，Task scope 仍可 current，且 `previous_verification_may_be_stale: false`；scope 变化时必须为 stale。比较使用 `session_handoff.py` 的 workspace snapshot 和 scope 内容 fingerprint，不复制完整 artifact 到 handoff。

## 结果纪律

- 状态只允许 `pass`、`fail`、`blocked`、`skipped`。
- exit code 非零默认是 `fail`；环境、权限、缺依赖或副作用授权不足是 `blocked`。
- 当前项目没有正式测试脚本时，tests 必须为 `skipped`，原因 `no configured test suite`。
- ESLint、Prettier 和 TypeScript 只使用项目已有的 `node_modules/.bin`；缺少工具时为 `blocked`，不得通过 `npm exec` 下载。
- runner 执行结束后重新获取 snapshot；执行期间工作区发生变化时追加 required `workspace-stability` fail，并把 artifact 绑定到最终状态。
- 不因为错误看起来与当前 Task 无关而忽略；只报告，不顺手修复。
- 不运行有副作用 build、不提交、不推送、不归档、不修改内置 Trellis 文件。
