# Trellis Harness Overlay

![version](https://img.shields.io/badge/version-0.3.4-blue)
![python](https://img.shields.io/badge/python-3.9%2B-green)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey)

在已初始化的 Trellis 项目上叠加一套 Agent 开发工作流：需求澄清、任务启动、断点续作、质量门禁和代码 Review。

> Harness 不会安装、初始化或升级 Trellis，只管理自己的 Core 文件。

## 特性

- **六个 `dev-*` Skills**：覆盖从需求到 Review 的完整开发循环
- **质量门禁**：按 profile 执行 lint / typecheck / test 等确定性检查
- **技术栈 Review**：内置 Next.js、React、Vue 2、Vue 3 规范
- **安全同步**：`sync` 只更新受管 Core 文件，不碰项目数据和本地配置
- **零依赖**：仅使用 Python 标准库

## 环境要求

- Git、Python 3.9+
- Windows 或 macOS 13+（暂不支持 Linux）
- 已初始化的 Trellis 项目（存在 `.trellis/.version`），已测试版本 `0.6.12` / `0.6.15` / `0.6.17`
- 默认质量门禁 profile 面向 npm 项目

## 安装

克隆仓库并将目录加入 `PATH`。

**Windows（PowerShell）**

```powershell
git clone <repo-url> trellis-harness
cd trellis-harness
$env:Path = "$(Get-Location);$env:Path"   # 当前会话生效；持久化请加入用户 PATH
Get-Command harness
```

**macOS（zsh）**

```sh
git clone <repo-url> trellis-harness
cd trellis-harness
chmod +x ./harness
echo "export PATH=\"$(pwd):\$PATH\"" >> ~/.zshrc && source ~/.zshrc
command -v harness
```

## 快速开始

```sh
# 安装到项目（可选 profile：nextjs / react / vue2 / vue3）
harness install --project <project> --profile nextjs

# 查看状态
harness status --project <project>

# Harness 更新后同步
harness sync --project <project>

# 批量管理工作区下的多个项目
harness status-all <workspace-root>
harness sync-all <workspace-root>
```

安装后在 Codex 中重新打开项目，即可使用 `dev-*` Skills。

## 工作流

| 命令 | 作用 |
| --- | --- |
| `dev-grill "<需求>"` | 逐个追问关键产品决策，生成 requirement intake |
| `dev-start <intake 或需求>` | 创建正式 Task 并开始实现 |
| `dev-verify fast` / `full` | 运行快速 / 完整质量门禁 |
| `dev-checkpoint` | 保存当前进度与交接信息 |
| `dev-resume <task-path>` | 从断点恢复任务 |
| `dev-review <task-path>` | 只读语义 Review |

典型流程：

```text
dev-grill → dev-start → dev-verify fast → dev-checkpoint → dev-review → dev-verify full
```

## 注意事项

- 本地修改过的 Core 文件会让 `install` / `sync` 中止；确认要覆盖时使用 `--force`（不会覆盖 profile 和项目数据）。
- profile 中标记为 `authorization: explicit` 的检查默认被阻断，需用户明确授权后传入 `--allow-explicit-checks`。
- Harness 与 Trellis 版本独立：升级 Trellis 用 `trellis upgrade` / `trellis update`，更新 Harness 用 `harness sync`。

## 更新日志

见 [CHANGELOG.md](./CHANGELOG.md)。
