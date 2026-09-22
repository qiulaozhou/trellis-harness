---
name: dev-start
description: 以“dev-start + 真实需求”启动当前项目的 Trellis 开发流程；读取当前状态，复用已有 Task 或为新需求进入原生 planning/task 流程，并建立 Harness 验证与跨 Session 约定。
---

# Dev Start

把用户在 `dev-start` 后提供的正文作为真实需求。这个 Skill 只负责入口和路由，不替代 Trellis 的 PRD、Design、Implement，也不修改内置 workflow。

## 1. 读取状态

读取并遵循 `.agents/skills/trellis-start/SKILL.md`，执行其中的 current state、Phase Index 和 guideline index 加载步骤。以 `.trellis/workflow.md`、当前 Task 状态和项目规范为事实来源。

## 2. 选择 Task 路径

### Requirement Intake 路径

如果 `dev-start` 后的参数解析为 `.trellis/harness/intake/<slug>/requirement-intake.md`，这是已完成澄清的入口，不是普通字符串需求：

1. 只读取该 intake，并按 `.trellis/spec/agent-development-harness.md` 使用 bundled `$harnessPython -B -X utf8` 执行 `.trellis/scripts/harness/intake.py validate <intake-path> --json`。`status` 必须是有效 `READY`；`IN_PROGRESS`、校验失败或缺少关键字段时停止并返回 `dev-grill`，不得猜测或重新做全量需求分析。
2. 使用官方 `.trellis/scripts/task.py create` 创建正式 Task（可先使用 `--no-start` 避免半成品 Task 被激活），把 intake 的 Goal、User-visible Behavior、In Scope、Out of Scope、Resolved Decisions、Assumptions、Dependencies 和 Acceptance Criteria 映射到原生 `prd.md`；只有原生流程需要时才补齐 `design.md`、`implement.md`。保留 intake 原文件和原始请求，不重复询问已解决决策。
3. 原生规划材料写完并准备绑定时，执行官方 `task.py start <task-path>`，再执行：

   ```powershell
   & $harnessPython -B -X utf8 ./.trellis/scripts/harness/intake.py consume <intake-path> --task <task-path>
   ```

   只有 `consume` 成功后才报告 intake 为 `CONSUMED`；本入口不因此自动开始业务编码、验证或 Next Action。

普通 `dev-start <requirement>` 仍使用下面的原有路径；不要自动强制用户先运行 `dev-grill`。

- 请求明确属于当前 active Task：继续该 Task，不创建重复 Task；按当前 phase 加载对应 step。
- 用户给出已有 Task 路径：核实它位于当前项目、未归档且状态允许继续，再使用现有 `task.py start` 绑定；不创建替代 Task。
- 请求是新需求且没有冲突的 active Task：将 `dev-start <需求>` 视为进入 Trellis 原生 planning/task 流程的授权，按 `trellis-start` 的分类路由创建和规划 Task。
- 新需求与 active Task 的归属不明确：停止选择并让用户确认，不覆盖或猜测。

新需求需要澄清时使用 `trellis-brainstorm`；也可以先用 `dev-grill` 生成 `READY` intake。编码前使用 `trellis-before-dev`。Task facts 仍写入原生 PRD、Design、Implement 和 research artifacts。

## 3. 建立 Harness 约定

开始工作时只简短告知：

```text
Development: dev-verify fast
Verification scope: establish the explicit implementation file list before the first Gate
Session handoff: dev-checkpoint
New session: dev-resume <task-path>
Before completion: dev-verify full
```

不要把 Harness 长说明注入后续每轮上下文；需要执行时再读取对应 Skill。不要安装依赖、升级 Trellis、自动完成或归档 Task。
