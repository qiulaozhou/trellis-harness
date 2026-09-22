---
name: dev-checkpoint
description: 为正在进行的已有 Trellis Task 保存最新 handoff 和简短 Journal 索引，供换一个 Codex Session 继续工作；用于用户要求 checkpoint、保存交接或准备换会话，不用于完成或归档任务。
---

# Dev Checkpoint

先读取项目根目录 `.trellis/spec/agent-development-harness.md`，使用其中的 Python 运行时、schema 和验证继承规则。以下路径相对当前项目根目录。

## 1. 确定已有 Task

以规范中的 `$harnessPython` 执行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/task.py current --json
```

核实是用户当前工作 Task。没有 active Task、结果来自 `session-fallback:` 或与用户上下文不符时，不创建任务：优先使用用户明确给出的已有 Task 路径；否则运行 helper `candidates` 展示候选。无法可靠确定时停止并询问，不以最新时间猜测。

确认 Task 是当前 workspace 下未归档且非 completed 的真实任务，再进行写入。不要把其他 Session 的 pointer 当作本次授权。

## 2. 读取必要事实

读取 task.json、PRD、存在的 Design/Implement、旧 handoff、实时 Git status/diff 和本 Session 尚未落盘的重要信息。

只记录当前工作位置、本轮进度、新决策、被否决方案、blocker、实际验证、唯一下一动作、未提交归属和必须保留的约束。已有任务材料以链接引用。保留旧 handoff 中仍有效的失败条件与限制，不因“本轮无新增”将它们丢弃；不记录完整聊天或普通探索过程。

## 3. 绑定验证与代码状态

已有 handoff 时先运行 `compare <handoff.md>`。代码变化且旧检查未重跑时，按规范将该项目记为 skipped，保留原结果和原 HEAD/指纹，并注明 potentially stale；不能给旧 pass 换上新 snapshot。workspace 变化与 Task scope 变化必须分开判断。

调用 helper `snapshot`，用其事实填入 Identity 和 Workspace Snapshot。`source_session` 缺失明确记 unknown，不编造来源。只填写真实验证结果；没有执行检查也至少保留一项 skipped 和原因。

如果 Task 根目录存在 `verification.json`，使用规范中的 bundled Python 执行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/quality_gate.py check-current <task-path>/verification.json
```

handoff 只引用该 artifact 的 `Gate`、`overall_status`、`workspace_current`、`scope_current`、`previous_verification_may_be_stale` 和路径，不复制完整 JSON。workspace 仅有 scope 外变化时，不将 Task verification 标为 stale；scope 变化或 scope ambiguous 时，保留 `Previous verification may be stale.`，不能把旧 `pass` 继承为当前证据。

## 4. 保存并校验

按规范 schema 更新 Task 根目录的 `handoff.md`，只保留最新 checkpoint。覆盖前保留旧内容以便写入/校验无法完成时恢复。避免与业务修改并行进行。

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/session_handoff.py validate <task-path>/handoff.md
& $harnessPython -B -X utf8 .trellis/scripts/harness/session_handoff.py compare <task-path>/handoff.md
```

validate 非零即失败，必须修正后重验。最终 compare 必须反映写完时的实际状态；若期间代码变化，刷新 snapshot 并按验证继承规则重新处理，不能仅替换指纹。无法完成时恢复旧有效内容并报告 checkpoint 失败，不进入 Journal 步骤。

## 5. 写入短 Journal 索引

使用现有 `add_session.py --no-commit`，提供必填 `--title`（如 `Checkpoint: <task-dir>`），用 `--branch` 明确传入实际 branch，不依赖 Task metadata 的默认推断。`--summary` 包含 Task path、checkpoint 时间、Current Focus、handoff 路径和“仅记录交接，Task 未完成”；`--next-step` 写唯一下一动作。可用 `--stdin` 传递结构化短内容，避免拼接不安全的 shell 字符串。

不传 `--test`；Journal 固定的 Completed/[OK] 不是完成或通过证据。日志写入失败就说明 handoff 已保存但索引未完成，不宣称整个 checkpoint 成功。

## 6. 交付

成功后只输出：

```text
Checkpoint saved.
Task: <task path>
Next: <next action>
Resume in a new session with:
dev-resume <task path>
```

这里的 `dev-resume` 是 Skill 调用意图，不是 shell 命令；新会话可以输入 `$dev-resume <task path>` 或“使用 dev-resume 恢复这个任务”。

全程不 archive、不 finish-work、不 task.py finish、不提交/推送/安装、不清除 Task、不修改业务代码。
