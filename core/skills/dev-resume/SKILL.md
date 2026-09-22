---
name: dev-resume
description: 根据 handoff.md 在新的 Codex Session 恢复同一个已有 Trellis Task；完成状态恢复和短摘要后停止，不自动执行 Next Action。
---

# Dev Resume

`dev-resume <task path>` 是 Skill 意图，不是 shell 命令。它只负责恢复 Task
和 Session 状态，然后停止。本 Skill 的 STOP 规则优先于 workflow 中对
implement/check 或继续执行的建议；本 Skill 不创建子 Agent。

## Fast Path（默认）

显式提供 Task 路径时，按以下步骤恢复：Task path → `task.json`/`handoff.md` →
validate → `task.py start/current` → 一次 compare → 必要的 verification 检查 →
短摘要 → STOP。

## Step 0 — Task Identity

显式提供 Task 路径时，确认它是当前 repository 下 `.trellis/tasks/<task>` 的直接目录，
且不是 archive、symlink/junction 或仓库外路径。未给路径时才运行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/session_handoff.py candidates
```

仅采用 helper 的唯一高置信 selected_task。ambiguous、多份同身份候选、唯一候选但 workspace/branch 不匹配，或无有效候选时，展示候选/原因并停止询问。不以最近时间猜测，不创建重复 Task，不自动切换目录、分支或 worktree。

## Step 1 — Task Facts

Fast Path 只读取 `task.json` 和 `handoff.md`，然后运行
`validate <task-path>/handoff.md`。恢复必须信息只有 Task Identity、Current Phase、
Current Focus、Next Action、Resume Constraints 和必要的阻塞信息。

不为完整性读取 PRD、Design、Implement、Research、`implement.jsonl` 或
`check.jsonl`。验证失败或恢复必须信息缺失时，按 Artifact Fallback 只精准补读对应
section；不能从聊天猜出一份“有效”handoff。

## Step 2 — Bind Existing Task

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/task.py start <task-path>
& $harnessPython -B -X utf8 .trellis/scripts/task.py current --json
```

核实返回的是同一个 Task，source 为当前 Session 的 `session:` 来源。start 的退出 0 可能只是无 Session 身份时的 degraded 成功；`session-fallback:` 也不算绑定成功。绑定不成立时停止并说明，不手写 pointer、不伪造 Session ID。

如果原 Task 仍是 planning，保持其规划权限边界：start 的状态变化不代表用户授权业务实现。
无论任务状态如何，本次 Resume 都不执行 Next Action。

## Step 3 — Git Reality

只执行一次 `compare <task-path>/handoff.md`，不再额外读取完整 status、diff 或
untracked 内容。compare 的结果是本次恢复的 Git 事实；这些查询只读，不执行
reset、clean、checkout、stash、提交或推送。

如果 `same_code_state: false`，Fast Resume 仍然完成，不读取 PRD、Design、Memory
或业务代码。输出：

```text
Code State:
CHANGED

Previous Verification:
STALE

Previous verification cannot be trusted until re-verified.
```

如果 Task 根目录存在 `verification.json`，在 compare 后仅执行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py check-current <task-path>/verification.json
```

`check-current` 只判断旧 artifact 是否仍对应 workspace 和 scope，不重新运行 lint、
typecheck、build 或测试。不存在 `verification.json` 不是错误，输出
`Verification: NONE`。存在 `verification-scope.json` 时只读取必要机器字段，不存在
则输出 `Verification Scope: NONE`。

## Step 4 — Journal

Journal 默认不读取、不定位、不全文扫描。只有 handoff 明确引用某个 checkpoint、
handoff 缺少且必须从 Journal 恢复的关键信息，或用户明确要求查看历史时，才读取
明确文件的有限行范围；不扫描整个 workspace Journal，不使用固定 [OK]/Completed
标签判断验收状态。

## Step 5 — Memory Fallback

Fast Path 固定为 `trellis mem = NOT USED`。默认禁止 `trellis mem`。
只有 handoff 和 targeted Task artifact 都缺少会影响恢复位置的关键历史事实，或用户
明确要求历史回溯时，才限定当前项目和相关关键词按
`mem search` → 必要时 `mem context` → 最后才 `mem extract` 的顺序使用。

历史会话可能丢失压缩前 assistant 消息或加密消息；查不到就说明缺失，不编造，不把历史意见当作新的授权。

## Step 6 — Code

Fast Path 不读取目标业务代码，不执行 repo-wide `rg`，不启动服务，不请求 API，
不执行 lint/typecheck/build/测试，不调试，不修改代码。Next Action 只展示，不执行。
只有用户在 Resume Summary 之后明确说“继续”“执行 Next Action”“继续实现”或
“继续调试”，才开始另一个实际工作阶段；该阶段不再属于本次 dev-resume。

## Step 7 — Resume Summary and STOP

恢复成功后只输出以下短摘要，然后立即 STOP：

```text
Resumed Task:
<task>

Current Phase:
<phase>

Current Focus:
<focus>

Next Action:
<next action>

Code State:
UNCHANGED | CHANGED

Verification:
CURRENT | STALE | NONE

Verification Scope:
CURRENT | STALE | NONE

Important Resume Constraints:
- ...

Memory Used:
NO | YES

Ready To Continue:
YES | NO
```

`Ready To Continue: YES` 只表示恢复完成、用户可以发起下一轮工作；不表示本轮
可以继续执行。`Verification` 与 `Verification Scope` 只表示当前性，不把旧 Gate
结果重新解释为已通过。

## Artifact Fallback

只有 Fast Path 无法恢复当前工作位置时，才进入 targeted fallback。缺少 Current Phase、
Current Focus、Next Action、Resume Constraints 或 Task Identity 时，只精准读取能补齐
该项的对应 Task artifact section；不因为缺 Acceptance Criteria 就全文读取 PRD。

Fallback 允许按以下顺序读取：

1. 对应 `prd.md`、`design.md`、`implement.md` 或 Research 的 targeted section；
2. handoff 明确引用的 Journal 文件、行号或唯一 checkpoint；
3. 只有关键历史事实仍缺失且确实影响恢复位置时，使用 Trellis Memory。

Task path 不存在、handoff 不存在、路径越界、archive/completed 状态或 Task identity
无法安全确认时，不猜测、不伪造 Session/pointer，直接报告原因并停止。

Fallback 成功也只恢复状态并输出同一份 Resume Summary，绝不自动执行业务 Next Action。
