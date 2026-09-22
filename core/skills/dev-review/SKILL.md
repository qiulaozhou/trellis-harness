---
name: dev-review
description: 对当前已有 Trellis Task Verification Scope 内的 Git 修改执行只读语义 Code Review，按项目真实技术栈加载 Vue2、Vue3、React 或 Next.js 规则，写入 review.json 后停止；不用于 lint、自动修复或继续实现。
---

# Dev Review

`dev-review [task-path]` 是 Skill 意图，不是 shell 命令。它只审查当前 Task 的
Verification Scope 与对应 Git diff，写入 `<task-path>/review.json`，输出结果后 STOP。

## Hard Boundary

- 只读业务代码；唯一允许写入的是当前 Task 的 `review.json`。
- 不修改代码，不自动修 Finding，不运行 lint、Prettier、typecheck、tests、build、
  dev server 或 API 请求，不 commit/push，不执行 handoff 的 Next Action。
- 不做 repo-wide search，不审查 scope 外 dirty/untracked 文件，不默认读取完整 PRD、
  Design、Implement、Research、Journal 或 Trellis Memory。
- formatting 和 trivial style 属于 `dev-verify`；除非格式直接改变语义，否则不报告。

## 1. Resolve Task and Context

显式 task path 必须是当前仓库 `.trellis/tasks/` 下的直接、非 archive Task。未提供时，
只运行 `.trellis/scripts/task.py current --json` 获取当前 Task；没有唯一 active Task 时
返回 BLOCKED，不创建、不 start、不切换 Task。

只读取：

- `<task>/task.json`
- `<task>/handoff.md`
- `<task>/verification-scope.json`

运行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/review_artifact.py context --task <task-path>
```

helper 必须返回 ready 的 profile、真实 package versions、router、scope files、
review files 和 scope fingerprint。缺 task/handoff/scope、scope ambiguous、profile 与实际
stack 冲突或 scope 内没有可审查 Git 修改时返回 BLOCKED；不要扩大到整个仓库补偿。

## 2. Load Rules

始终完整读取 `references/common.md`，再按 context 的 `profile` 读取一个 stack profile：

- `vue2` → `references/vue2.md`
- `vue3` → `references/vue3.md`
- `react` → `references/react.md`
- `nextjs` → 先读 `references/react.md`，再读 `references/nextjs.md`

版本相关判断必须使用 context 返回的真实版本和 router，不假设最新版。profile 优先来自
现有 `.trellis/harness/quality-gates.json` 的 `review.profile`；旧的定制 profile 没有该字段
时，helper 才从 `package.json` 精准推断，不改写项目 profile。

## 3. Inspect Only the Task Diff

仅对 context 的 `review_files` 执行 staged/unstaged Git diff，并读取其中 untracked 文件：

```powershell
git --no-optional-locks diff --cached -- <review-files>
git --no-optional-locks diff -- <review-files>
```

只在某个 Finding 无法判断时，读取修改文件的直接依赖上下文，例如 imported helper、API
type、store 或 parent/child contract。每次 targeted read 都必须能说明与具体判断的关系；
禁止 repo-wide `rg` 或“重新理解项目”。

Requirement Coverage 优先使用 handoff。只有 handoff 缺少会改变 Review 结论的验收信息时，
才精准读取 PRD/Design/Implement 的相关标题或有限行范围；仍不足则 BLOCKED。默认不读
Journal/Memory。

## 4. Findings and Result

Finding 必须有证据并包含：`priority`、`title`、`file`、`line`、`problem`、`impact`、
`evidence`、`suggested_direction`。优先级：P0 严重故障/安全/数据破坏/发布阻塞；P1 高风险
实际 Bug/核心需求错误；P2 中风险边界或明显维护风险；P3 低风险改进。

- `APPROVED`：没有 P0/P1/P2；无 Finding 时 summary 必须为 `No material findings.`
- `CHANGES_REQUESTED`：至少一个 P0/P1/P2。
- `BLOCKED`：缺少完成可靠 Review 所必需的代码、需求或 scope 信息。

不得为了显得有价值而制造 Finding，也不得输出无位置、触发场景或代码证据的泛泛意见。

## 5. Artifact and Freshness

写入 `<task>/review.json`，至少包含：

```json
{
  "schema_version": 1,
  "reviewed_at": "<UTC ISO-8601>",
  "profile": "vue2 | vue3 | react | nextjs",
  "task": ".trellis/tasks/<task>",
  "scope_fingerprint": "<context fingerprint>",
  "code": {"branch": "<branch>", "head": "<head>"},
  "result": "APPROVED | CHANGES_REQUESTED | BLOCKED",
  "summary": "<short result summary>",
  "findings": [],
  "reviewed_files": []
}
```

`reviewed_files` 只能是 context 的 `review_files`。写入后运行：

```powershell
& $harnessPython -B -X utf8 .trellis/scripts/harness/review_artifact.py validate <task-path>/review.json
& $harnessPython -B -X utf8 .trellis/scripts/harness/review_artifact.py check-current <task-path>/review.json
```

Freshness 只比较复用的 Task scope fingerprint；scope 定义、scope 文件内容或其 Git 状态改变
即为 STALE，scope 外变化不影响 CURRENT。

## 6. Output and STOP

输出 profile、Review Scope、reviewed files、result、按优先级排序的 Findings、freshness 和
artifact path。无实质 Finding 时明确输出 `No material findings.`。然后立即 STOP；即使
handoff 有明确 Next Action，也只可展示，不得执行。
