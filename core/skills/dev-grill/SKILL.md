---
name: dev-grill
description: 在正式 Trellis Task 之前，以一次一个核心问题的方式澄清需求并持久化 requirement intake；不创建 Task、不改业务代码、不自动进入实现。
---

# Dev Grill

`dev-grill <requirement>` 是需求澄清入口，不是实现入口。它把产品决策、仓库事实和可验证的验收条件写入 `.trellis/harness/intake/<slug>/requirement-intake.md`，然后在本轮停止。

## Hard Boundary

本 Skill 不创建正式 Task，不调用 `dev-start`，不修改业务代码，不启动服务或请求真实 API，不执行 lint、typecheck、build、调试、commit 或 push。即使 intake 里有 Next Action，也只能展示它。用户之后明确说“继续”“执行 Next Action”“继续实现”或“继续调试”时，才离开本 Skill。

`dev-start` 负责正式 Task/PRD/Design/Implement，`dev-review` 负责只读语义审查，`dev-verify` 负责可重复验证；不要把三者混入 Grill。

## Fast Interaction

1. 先读取本 Skill、`.trellis/harness/` 下已存在的 intake（如用户给了路径则只读该文件）和最小仓库入口：`package.json`、相关配置、已有公共约定。仓库事实由你查明，不把可验证的事实问题抛给用户；不要 repo-wide search 或加载业务代码来“重新理解项目”。
2. 新需求没有 intake 时，先按 `.trellis/spec/agent-development-harness.md` 解析 bundled Python 为 `$harnessPython`，再调用标准库 helper 创建一个 slug 目录：

   ```powershell
   & $harnessPython -B -X utf8 ./.trellis/scripts/harness/intake.py init --slug <slug> --request "<original request>" --profile <profile>
   ```

   `profile` 使用已有质量门禁配置中的 `grill.profile`；没有时从 `package.json` 推断 `vue2`、`vue3`、`react` 或 `nextjs`。不要建立第二套 profile 配置。

3. 先把已发现的 Repository Facts 和 Engineering Mappings 写入 intake。每个有影响的用户决策写完后立即更新同一个文件；不要另建聊天笔记。
4. 每轮最多提出一个尚未解决的核心产品/行为问题。问题用产品语言表达，并按需要给出：

   ```text
   Question:
   Options:
   Recommended Answer:
   Recommendation Reason:
   ```

   用户可以选择选项、接受推荐、自定义答案，或标记为 external/unknown；记录 owner、impact、blocking、next step，不要假装已解决。
5. 更新后用 `$harnessPython -B -X utf8` 调用 `intake.py resume` 或 `validate` 检查当前 frontier。决策已解决的分支不得重复提问；未解决的最高影响分支才是下一轮问题。

## Decision Tree

按需求动态取分支，不机械遍历全部问题。通常依次检查 Goal、Target User、Success Outcome、Main User Flow、In Scope、Out of Scope；仅在适用时追问 states（loading/empty/error/success）、API/Data、权限、兼容性、i18n、响应式/设备、可访问性/性能、迁移/rollout、外部依赖、阻塞项、假设和 Acceptance Criteria。

Goal、User-visible Behavior、Scope、Out of Scope、material edge cases、Dependencies、Assumptions 和 Acceptance Criteria 是 Ready 的核心字段。产品决策确认后，再在 Engineering Mappings 中记录其对组件、路由、数据、状态或验证的映射；不要用工程术语替代产品决策。

## Stack Profiles

使用现有 `quality-gates.json` 的 profile：`vue2`、`vue3`、`react`、`nextjs`。Profile 只决定需要检查的仓库事实、风险和追问分支，不要求在 Grill 阶段读取实现代码，也不产生另一套配置。Next.js 继承 React 的事实检查并增加 Next 路由/渲染边界。

## Persistence and Resume

Intake 必须保留原始请求，并包含以下 section：`Current Focus`、`Goal`、`Target User`、`User-visible Behavior`、`In Scope`、`Out of Scope`、`States`、`Edge Cases`、`Resolved Decisions`、`Engineering Mappings`、`Repository Facts`、`Dependencies`、`Blockers`、`Assumptions`、`Acceptance Criteria`、`Unresolved Decisions`。状态只能是 `IN_PROGRESS`、`READY`、`CONSUMED`。

使用 `dev-grill resume <intake-path>` 时只读取该 intake 和完成当前 frontier 所需的最小仓库事实，不重问已解决项。正常情况下不读完整 PRD/Design/Implement、Research、implement.jsonl、check.jsonl、完整 Journal、完整 Git diff、业务代码，也不调用 `trellis mem`。

`READY` 要求目标、用户可见行为、范围、排除项、适用的状态/边界、依赖、假设和 AC 明确，`Unresolved Decisions` 没有 `[open]`，且没有 `[blocking]` 或 `blocking=yes`。未知外部事实只有在记录 owner、影响、是否阻塞和下一步后才允许保留。否则保持 `IN_PROGRESS`。

## Handoff to dev-start

用户明确要求后，可执行：

```text
dev-start .trellis/harness/intake/<slug>/requirement-intake.md
```

`dev-start` 必须先用 `$harnessPython -B -X utf8 .trellis/scripts/harness/intake.py validate`，只接受有效 `READY` intake；再调用官方 `task.py create` 建立正式 Task，使用 intake 的 Goal、Scope、Decisions、Assumptions、Acceptance Criteria、Dependencies 填充原生 PRD/Design/Implement，保留 intake 原文件；不得重新提问已解决决策。创建并写入 Task 路径后调用：

```powershell
& $harnessPython -B -X utf8 ./.trellis/scripts/harness/intake.py consume <intake-path> --task <task-path>
```

消费成功后只报告 Task 已创建和 intake 已 `CONSUMED`，仍不得开始业务实现。`dev-start <普通需求>` 的原有简单路径继续有效，不自动强制 Grill。

## Memory and Fallback

默认 `trellis mem = NOT USED`。只有关键决策既不在 intake 又不在 Task artifact，且确实影响用户决策，或用户明确要求历史回溯时，才按 `mem search` → 必要时 `mem context` → 最后 `mem extract` 使用；不得恢复完整旧 Session。

只有 intake 不存在、校验失败、Task identity 冲突、Task 不可继续、Current Focus/关键 Next Frontier 缺失，或关键引用事实缺失时进入 Fallback。Fallback 只精准读取对应 artifact/明确 Journal checkpoint，必要时再用 Memory；成功后仍只恢复澄清状态并停止，不自动创建 Task 或执行业务 Next Action。

## Completion Output

每轮结束输出短状态：intake 路径、Status、Profile、Repository Facts、已解决决策、当前唯一 frontier 问题（如有）、`Ready For dev-start: YES|NO`、`Memory Used: NO|YES`。完成 READY 后停止，并等待用户明确进入 `dev-start`。
