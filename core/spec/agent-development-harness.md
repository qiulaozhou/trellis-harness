# Agent Development Harness：Session Checkpoint / Resume

## 适用范围与事实来源

本规范用于同一 Trellis Task 的跨 Codex Session 交接。当前项目为 Trellis 0.6.12 模板、0.6.15 CLI 和本地定制的组合；以实际脚本为准，不升级或修改内置行为。

| 层 | 职责 |
| --- | --- |
| Task State | `task.json`、PRD、Design、Implement、Research 保存需求、验收条件、设计决策、执行计划与研究事实 |
| Session State | Task 根目录 `handoff.md` 只保存最新可恢复状态；替换前读旧记录，保留仍有效的失败条件、阻塞与约束 |
| Journal | 现有 Workspace Journal 只保存 checkpoint 时间线和索引；固定 `[OK]` / `Completed` 不是任务完成或验证通过的证据 |
| Raw Memory | Task/handoff 有重要缺口时才使用 `trellis mem search` → `context` → 必要时 `extract`，不默认恢复完整聊天 |
| Git State | 当前 Git/source 是实现事实；handoff 的 Verification 绑定记录时的 Workspace、Branch、HEAD 和 Diff Fingerprint |

Session End：checkpoint 不等于 task finish、archive 或 finish-work。checkpoint 不调用这些入口，不清除 pointer，不提交、不推送、不改业务代码。Task 状态保持原值。

Task Done：只有 Acceptance Criteria、必要验证、Check 以及用户/现有流程要求的完成条件均满足后，才进入原有 finish-work/archive。handoff 不能授权原任务范围之外的新工作。

## 本机 Python 与只读 Helper

Harness 只依赖 Python 3.9+ 标准库，不安装第三方依赖。PowerShell 中先解析当前机器可用的 Python：

```powershell
$harnessPython = (Get-Command python -ErrorAction Stop).Source
Test-Path -LiteralPath $harnessPython
& $harnessPython -B -X utf8 .trellis/scripts/harness/session_handoff.py snapshot
```

若 `python` 不在 PATH，请将 `$harnessPython` 替换为本机 Python 3.9+ 可执行文件路径；不要复制其他机器的绝对路径、修改 PATH 或安装第三方依赖。下文所有 `task.py` / `add_session.py` / helper 命令均以 `& $harnessPython -B -X utf8` 调用。`-B` 避免写入 Python 缓存。

Helper 四个子命令均可带 `--workspace <当前工作区路径>`，默认 cwd：

| 命令 | 结果 |
| --- | --- |
| `snapshot` | JSON：repository_root、workspace_path、branch、head、dirty、staged/unstaged/untracked 文件、diff_fingerprint、checkpoint_at、source_session |
| `validate <handoff.md>` | 校验 section、字段、四态验证、Task 位置与状态；无效时列出具体问题并以非零退出 |
| `compare <handoff.md>` | 输出 same_code_state 及 head/diff/branch/workspace_changed；变化时明确提示 `Previous verification may be stale.`，比较成功仍退出 0 |
| `candidates` | 仅列出有效的未归档 Task handoff；workspace、branch、时间依次排序；多份同身份候选输出 ambiguous，不修改 pointer |

只有唯一 workspace 与 branch 同时匹配的候选可自动采用。时间只改善展示顺序，不能用于在多个同等候选中猜任务；唯一但 workspace/branch 不匹配也不能自动采用。无有效候选时要求明确已有 Task 路径，不创建任务。

指纹使用 staged/unstaged diff 与排序后的未跟踪文件路径及 lstat 元数据（size、mtime_ns）。Git diff 仅在内存计算摘要，不输出正文；不额外读取未跟踪文件正文。Git 关闭 optional locks、external diff 和 textconv。

限制：ignored 文件、外部依赖/环境变化不在指纹范围；未跟踪内容变化但 size/mtime_ns 被保留时可能漏检。它是工作区变化探测，不是安全证明。同指纹也不能让未执行的测试变成 pass；进行 snapshot/compare 时避免并行修改工作区。无提交的临时仓库 HEAD 为 `UNBORN`，分离 HEAD 的 branch 使用 helper 实际返回值。

## handoff.md Schema

使用下列精确二级标题及单行 `Key: value` 字段。保留全部 section；没有决策/失败/阻塞时明确写“无新增”或“无”。不要把完整 handoff 包在代码块里。Next Action 只有一个 `Action`，其细节可引用 Implement。

Identity 的 Task 使用 `.trellis/tasks/<task-dir>` 相对路径，handoff 必须位于该 Task 根目录。不得指向 archive、completed 或仓库外路径；不接受任何 symlink/junction 别名，包括指向仓库内的别名。Workspace 使用 snapshot 的绝对 workspace_path；过去工作区不同由 compare 报告，不是 handoff 结构错误。

```markdown
# Session Handoff

## Identity
Task: .trellis/tasks/<task-dir>
Checkpoint At: <snapshot.checkpoint_at，带时区的 ISO8601>
Source Session: <snapshot.source_session；null 时明确写 unknown>
Workspace: <snapshot.workspace_path>

## Current Position
Phase: <现有工作流阶段或步骤>
Current Focus: <当前正在解决的具体问题>

## Progress Since Previous Checkpoint
- <本轮完成项；引用 Implement 条目，避免复制计划>

## Decisions
- Decision: <新增或仍影响后续的决定，已有完整记录则链接>
  Reason: <原因>
  Scope: <适用范围>

## Rejected Approaches
- Approach: <已尝试方案>
  Failure Evidence: <失败证据或任务内链接>
  Do Not Retry Unless: <只有哪个前提变化才值得重试>

## Known Issues / Blockers
- <问题、影响与解除条件，或无>

## Verification
### <验证项目>
Status: skipped
Command / Method: <实际命令或操作方法，不填写凭据>
Scope: <覆盖范围>
Evidence: <实际输出摘要或证据引用；未执行则明确原因>
Notes: <限制、环境或旧证据绑定>

## Workspace Snapshot
Branch: <snapshot.branch>
HEAD: <snapshot.head>
Dirty: <snapshot.dirty，true 或 false>
Diff Fingerprint: <snapshot.diff_fingerprint>

## Uncommitted Work Ownership
<哪些未提交工作属于本 Task，以及必须保留的他人修改；实时文件清单从 Git 查询>

## Next Action
Action: <唯一、具体、可以直接执行的下一动作>
Expected Result: <执行后应看到的结果>

## Resume Constraints
- <仍有效的业务/权限限制、不能破坏的条件；引用 PRD，不复制长段>
```

Verification 至少保留一项；即使未进行验证，也写明 skipped 和原因。合法 Status 仅为 `pass / fail / blocked / skipped`，不能使用 Completed、OK 或 stale 作为 Status。

## 验证证据的继承

首次记录只填写确实执行过的检查及对应范围。更新旧 handoff 前先 compare 旧记录：

- 状态相同且环境仍适用，可保留原有验证证据，并说明来源。
- 状态变化后，未在新状态重跑的旧检查标为 skipped；Evidence 保留原结果及原 HEAD/指纹，Notes 写 `potentially stale`，不能把旧 pass 重新绑定到新 snapshot。
- resume 不覆盖 handoff 中的历史事实；compare 不一致时，将其验证视为 potentially stale，列出下一动作依赖的待复验项。
- 代码差异不等于 handoff 无效；继续保留其需求、决策、失败条件和约束，并与当前源码核对。

## Journal 与任务绑定

checkpoint 的 Journal 索引使用 `add_session.py --no-commit`，提供必填 `--title`，明确包含 Task 路径、checkpoint 时间、Current Focus、Next Action、handoff 路径和“仅记录交接，Task 未完成”。不使用 `--test`，真实 Verification 只在 handoff 中维护。日志写入失败时报告“handoff 已保存，Journal 索引未完成”，不能宣称整个 checkpoint 成功。

resume 通过现有 `task.py start <task-path>` 绑定，随后 `task.py current --json` 核验同一个 Task 且 `source` 为当前 Session 的 `session:` 来源。`session-fallback:`、未持久化的 degraded 成功或其他 Task 都不算绑定成功；停止并报告环境问题，不手写 runtime、不伪造 Session ID。

## 最低检查

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/test_session_handoff.py
git --no-optional-locks diff --check
```

自测只写临时 fixture，覆盖指纹、非法/缺失字段、archive/completed 拒绝、stale 和候选歧义。新增文件是独立本地扩展；不修改 managed hashes，不为发现 Skill 改写 AGENTS.md。当前工作区忽略 Harness 目录，跨机器或新 clone 的同步另行处理。
