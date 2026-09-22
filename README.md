# Trellis Harness Overlay

> Development Distribution：此副本用于准备团队内部共享。真实业务开发继续使用独立的 `0.3.0` Stable Distribution。

版本 `0.3.1` 是面向已包含 `.trellis/.version` 项目的增量式 Harness Core。它不会初始化或升级 Trellis。

## 支持的平台

| 平台 | 支持情况 | 命令启动器 |
| --- | --- | --- |
| Windows | 支持 | `harness.cmd` |
| macOS 13+ | 支持 Intel 和 Apple Silicon | `harness` |
| Linux | 当前不支持 | 无 |

## 前置条件

- Git
- Python 3.9 或更高版本；Harness 只使用 Python 标准库
- 单独安装 Trellis CLI
- 已经通过 `.trellis/.version` 完成初始化的 Trellis 项目
- 默认质量门禁 profile 当前支持 npm 项目；其他包管理器需要项目自定义 profile
- 安装后在 Codex 中重新打开项目，使其能够发现 `.agents/skills/dev-*`

Harness 不会安装或初始化 Trellis。请先按照项目所需的官方 Trellis 流程完成设置，然后验证：

```powershell
Test-Path .trellis/.version
trellis --version
```

在 macOS 上，请在 Terminal 中执行对应检查：

```sh
test -f .trellis/.version
trellis --version
```

当前已测试的项目版本为 Trellis `0.6.12` 和 `0.6.15`；当前已测试的 CLI 版本为 `0.6.15`。

## Windows：克隆并注册命令

克隆本仓库后，在克隆目录中执行：

```powershell
$harnessRoot = (Get-Location).Path

# 仅对当前 PowerShell 会话生效。
$env:Path = "$harnessRoot;$env:Path"

# 可选：将目录持久化到当前用户的 PATH。
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ }
if ($userPath -notcontains $harnessRoot) {
  [Environment]::SetEnvironmentVariable('Path', (($userPath + $harnessRoot) -join ';'), 'User')
}
```

完成持久化注册后，请打开新的 PowerShell 窗口并验证：

```powershell
Get-Command harness
where.exe harness
```

如需从当前用户的 PATH 中移除该克隆目录：

```powershell
$harnessRoot = 'C:\path\to\trellis-harness'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ -and $_ -ne $harnessRoot }
[Environment]::SetEnvironmentVariable('Path', ($userPath -join ';'), 'User')
```

Windows wrapper 会先尝试 `python`，再尝试 `py`。如果两者都不可用，它会输出明确的前置条件错误并退出。它不会自动修改 PATH。

## macOS：克隆并注册命令

在克隆目录中执行：

```sh
chmod +x ./harness

# 仅对当前 Terminal 会话生效。
export PATH="$(pwd):$PATH"

command -v python3
command -v harness
```

如果找不到 `python3`，请使用适用于 Mac 的受信任 Python 安装程序或包管理器安装 Python 3.9 或更高版本，然后重新打开 Terminal。启动器会先尝试 `python3`，再尝试 `python`。

如需在 zsh 中持久化该命令，请使用克隆目录的绝对路径，将其加入 `~/.zshrc`：

```sh
echo 'export PATH="/absolute/path/to/trellis-harness:$PATH"' >> ~/.zshrc
source ~/.zshrc
command -v harness
```

如需移除，请从 `~/.zshrc` 中删除对应的 export 行，然后再次执行 `source ~/.zshrc`。系统不会自动修改 Shell 配置。

也可以不注册 PATH，直接运行启动器：

```sh
./harness status --project /absolute/path/to/project
```

## 日常使用

```text
dev-grill "<new requirement>"
dev-grill resume <intake-path>
dev-start <requirement>
dev-verify fast
dev-checkpoint
dev-resume <task-path>
dev-review <task-path>
dev-verify full
```

`dev-grill` 每次只询问一个重要的产品决策，并写入 requirement intake。它在恢复或更新 intake 后停止；不会创建 Task，也不会执行实现。当 intake 状态为 `READY` 时，请显式将它传给 `dev-start <intake-path>`，以创建正式 Task。

第一次执行 `dev-verify fast` 前，Skill 会要求从当前 Task 的实际实现中确认 repo-relative 文件清单，并通过 `quality_gate.py scope` 写入 `verification-scope.json`；不会把工作区全部 dirty 文件猜成当前 Task。Full Gate 的 Acceptance Criteria 继续由 Trellis Check/finish-work 负责，未授权的 optional build readiness 会保留为 blocked，但不会单独阻断 Gate。

## Distribution 命令

请使用已经注册的命令，或者直接从本目录调用对应平台的启动器。该工具没有第三方依赖。

```text
harness status --project <project>
harness install --project <project> --profile nextjs
harness sync --project <project>
harness status-all <workspace-root>
harness sync-all <workspace-root>
```

`install` 要求项目已经完成 Trellis 初始化，并且 Trellis 项目版本受支持。只有在显式选择 profile，且项目不存在 `.trellis/harness/quality-gates.json` 时，才会复制 profile。Profiles 用于选择确定性的质量门禁，以及 `dev-review` 和 `dev-grill` 的技术栈 profile。`sync` 和 `sync-all` 只更新 `manifest.json` 中列出的 Core 路径；它们会保留 profiles、Tasks、handoffs、intake/verification/review artifacts、Journal、runtime、业务规格文件以及 `.trellis/.template-hashes.json`。已有但缺少 `review.profile` 或 `grill.profile` 的自定义 profile 不会被修改；需要时，Skills 会从 `package.json` 检测受支持的技术栈。

如果 Core 文件存在本地修改，`install`/`sync` 会在写入前停止。只有在需要替换由 manifest 管理的 Core 文件时才使用 `--force`；它永远不会覆盖 profile 或项目数据。

安装后，如果六个 `dev-*` Skills 没有立即显示，请在 Codex 中重新打开项目。`harness status --project <project>` 会报告已安装的 Harness 版本、Trellis 项目版本、profile、兼容性状态以及受管理的 Core 状态。

## 独立的生命周期

官方 Trellis 与本 Overlay 使用独立的版本和命令：

```text
trellis upgrade             # global official CLI
trellis update              # official files in one project
trellis update --migrate    # only when official Trellis requires migration
harness sync                # custom Harness Core only
```

不要将 Harness 版本当作 Trellis 版本。Harness 命令不会调用 `trellis upgrade`、`trellis update` 或 `trellis update --migrate`。
