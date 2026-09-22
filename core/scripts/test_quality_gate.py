"""Quality Gate 的标准库隔离自测；不修改真实仓库或 Task。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import quality_gate


class QualityGateTests(unittest.TestCase):
    """覆盖配置、状态汇总、artifact 快照和输出截断。"""

    def make_workspace(self, checks: dict[str, list[dict]]) -> Path:
        """创建包含最小 Git 与质量配置的临时工作区。"""
        root = Path(tempfile.mkdtemp(prefix="quality-gate-"))
        (root / ".trellis" / "harness").mkdir(parents=True)
        (root / "package.json").write_text(json.dumps({"scripts": {}}), encoding="utf-8")
        (root / ".trellis" / "harness" / "quality-gates.json").write_text(
            json.dumps(checks), encoding="utf-8"
        )
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True, capture_output=True)
        return root

    @staticmethod
    def fake_snapshot(workspace: Path) -> dict:
        """构造与 session_handoff.snapshot 相同关键字段的测试快照。"""
        return {
            "repository_root": str(workspace),
            "workspace_path": str(workspace),
            "branch": "main",
            "head": "UNBORN",
            "dirty": False,
            "staged_changed_files": [],
            "unstaged_changed_files": [],
            "untracked_files": [],
            "diff_fingerprint": "a" * 64,
            "checkpoint_at": "2026-09-04T00:00:00+00:00",
            "source_session": "test-session",
        }

    @staticmethod
    def create_scope(workspace: Path, include: list[str]) -> Path:
        """为 fixture 创建显式 Task scope，不依赖自然语言 ownership。"""
        task = workspace / ".trellis" / "tasks" / "task"
        task.mkdir(parents=True, exist_ok=True)
        (task / "task.json").write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
        (task / "verification-scope.json").write_text(
            json.dumps(
                {
                    "task": ".trellis/tasks/task",
                    "include": include,
                    "exclude": [],
                    "source": "explicit",
                    "updated_at": "2026-09-04T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        return task

    @staticmethod
    def write_artifact(task: Path, snapshot: dict, scope: dict) -> Path:
        """保存最小 task-aware artifact，供 check-current 测试读取。"""
        artifact = task / "verification.json"
        artifact.write_text(
            json.dumps(
                {
                    "Task": ".trellis/tasks/task",
                    "Gate": "fast",
                    "timestamp": "2026-09-04T00:00:00+00:00",
                    "snapshot": snapshot,
                    "workspace_snapshot": snapshot,
                    "workspace_fingerprint": snapshot["diff_fingerprint"],
                    "verification_scope": scope,
                    "scope_fingerprint": scope["fingerprint"],
                    "overall_status": "pass",
                    "checks": [],
                }
            ),
            encoding="utf-8",
        )
        return artifact

    @staticmethod
    def command(exit_code: int) -> list[str]:
        """生成跨平台的最小成功/失败 Python 命令。"""
        return [sys.executable, "-c", f"raise SystemExit({exit_code})"]

    def test_config_parse_and_plan(self) -> None:
        """plan 只产生 run/blocked/skipped 决策，不执行检查。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "safe",
                        "description": "safe",
                        "enabled": True,
                        "required": True,
                        "command": self.command(0),
                        "scope": "fixture",
                        "side_effect_level": "none",
                    },
                    {
                        "id": "build",
                        "description": "build",
                        "enabled": True,
                        "required": True,
                        "runner": "build",
                        "scope": "fixture build",
                        "side_effect_level": "external",
                    },
                    {
                        "id": "off",
                        "description": "off",
                        "enabled": False,
                        "required": False,
                        "command": self.command(0),
                        "scope": "fixture",
                        "side_effect_level": "none",
                    },
                ],
                "full": [],
            }
        )
        config = quality_gate.load_config(workspace)
        plan = quality_gate.plan_gate("fast", config, self.fake_snapshot(workspace))
        self.assertEqual(plan["checks"][0]["action"], "run")
        self.assertEqual(plan["checks"][1]["status"], "blocked")
        self.assertEqual(plan["checks"][2]["status"], "skipped")

    def test_config_rejects_unknown_runner(self) -> None:
        """未知 runner 不能静默变成 skipped 后让 required gate 通过。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "unknown",
                        "description": "unknown",
                        "enabled": True,
                        "required": True,
                        "runner": "not-configured",
                        "scope": "fixture",
                        "side_effect_level": "none",
                    }
                ],
                "full": [],
            }
        )
        with self.assertRaisesRegex(ValueError, "runner must be one of"):
            quality_gate.load_config(workspace)

    def test_write_scope_creates_and_updates_explicit_scope(self) -> None:
        """显式文件清单可创建并覆盖同一 Task 的 Verification Scope。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        task = self.create_scope(workspace, ["src/old.ts"])

        created = quality_gate.write_scope(
            workspace,
            task,
            ["src/a.ts", "src/a.ts", "src/b.ts"],
            ["docs/note.md"],
        )

        self.assertEqual(created["task"], ".trellis/tasks/task")
        self.assertEqual(created["source"], "explicit")
        self.assertEqual(created["include"], ["src/a.ts", "src/b.ts"])
        self.assertEqual(created["exclude"], ["docs/note.md"])
        self.assertRegex(created["updated_at"], r"^\d{4}-\d{2}-\d{2}T")
        saved = json.loads((task / "verification-scope.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, created)

    def test_write_scope_rejects_empty_and_escaping_paths(self) -> None:
        """空 scope 与仓库外路径不得留下 artifact。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        task = workspace / ".trellis" / "tasks" / "task"
        task.mkdir(parents=True)
        (workspace / "src").mkdir()
        (task / "task.json").write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "at least one include"):
            quality_gate.write_scope(workspace, task, [], [])
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            quality_gate.write_scope(workspace, task, ["../outside.ts"], [])
        for invalid in (".", "src/..", "src"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "regular file path"):
                quality_gate.write_scope(workspace, task, [invalid], [])
        self.assertFalse((task / "verification-scope.json").exists())

    def test_run_statuses_and_overall(self) -> None:
        """验证 pass、fail、blocked 与 required 汇总优先级。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "pass",
                        "description": "pass",
                        "enabled": True,
                        "required": True,
                        "command": self.command(0),
                        "scope": "fixture",
                        "side_effect_level": "none",
                    },
                    {
                        "id": "fail",
                        "description": "fail",
                        "enabled": True,
                        "required": False,
                        "command": self.command(1),
                        "scope": "fixture",
                        "side_effect_level": "none",
                    },
                    {
                        "id": "blocked",
                        "description": "blocked",
                        "enabled": True,
                        "required": True,
                        "command": self.command(0),
                        "scope": "fixture",
                        "side_effect_level": "repo_write",
                    },
                    {
                        "id": "skip",
                        "description": "skip",
                        "enabled": False,
                        "required": False,
                        "command": self.command(0),
                        "scope": "fixture",
                        "side_effect_level": "none",
                    },
                ],
                "full": [],
            }
        )
        snapshot = quality_gate.session_handoff.snapshot(workspace)
        result = quality_gate.run_gate("fast", quality_gate.load_config(workspace), snapshot, False)
        self.assertEqual([item["status"] for item in result["checks"]], ["pass", "fail", "blocked", "skipped"])
        self.assertEqual(result["overall_status"], "fail")

    def test_overall_rejects_unknown_status(self) -> None:
        """未知状态不能进入 verification.json。"""
        with self.assertRaisesRegex(ValueError, "check status must be one of"):
            quality_gate.overall_status([{"status": "unknown"}])

    def test_tests_skip_and_build_block(self) -> None:
        """缺少正式 test 脚本时 skipped，build 未授权时 blocked。"""
        workspace = self.make_workspace(
            {
                "fast": [],
                "full": [
                    {
                        "id": "tests",
                        "description": "tests",
                        "enabled": True,
                        "required": True,
                        "runner": "tests",
                        "scope": "package",
                        "side_effect_level": "none",
                    },
                    {
                        "id": "build-readiness",
                        "description": "build",
                        "enabled": True,
                        "required": False,
                        "runner": "build",
                        "scope": "production",
                        "side_effect_level": "external",
                    },
                ],
            }
        )
        snapshot = quality_gate.session_handoff.snapshot(workspace)
        result = quality_gate.run_gate("full", quality_gate.load_config(workspace), snapshot, False)
        self.assertEqual(result["checks"][0]["status"], "skipped")
        self.assertEqual(result["checks"][0]["evidence"], "no configured test suite")
        self.assertEqual(result["checks"][1]["status"], "blocked")
        self.assertIn("Build requires explicit side-effect authorization.", result["checks"][1]["evidence"])
        self.assertEqual(result["overall_status"], "pass")

    def test_legacy_acceptance_runner_delegates_without_blocking(self) -> None:
        """旧 profile 的 Acceptance runner 交回 Trellis Check，不永久阻塞 Full Gate。"""
        workspace = self.make_workspace(
            {
                "fast": [],
                "full": [
                    {
                        "id": "acceptance-criteria",
                        "description": "acceptance",
                        "enabled": True,
                        "required": True,
                        "runner": "acceptance-criteria",
                        "scope": "fixture",
                        "side_effect_level": "none",
                    }
                ],
            }
        )
        snapshot = quality_gate.session_handoff.snapshot(workspace)
        result = quality_gate.run_gate("full", quality_gate.load_config(workspace), snapshot, False)
        self.assertEqual(result["checks"][0]["status"], "skipped")
        self.assertIn("Trellis Check", result["checks"][0]["evidence"])
        self.assertEqual(result["overall_status"], "pass")

    def test_targeted_tools_resolve_only_from_local_node_modules(self) -> None:
        """Targeted checks 不得通过 npm exec 隐式下载缺失工具。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        snapshot = self.fake_snapshot(workspace)
        scope = {"status": "ready", "files": ["src/a.ts"]}
        command = quality_gate.resolve_runner(
            {"runner": "targeted-eslint"}, snapshot, "fast", scope
        )
        expected = workspace / "node_modules" / ".bin" / ("eslint.cmd" if sys.platform == "win32" else "eslint")
        self.assertEqual(command[0], str(expected))

    def test_scope_triggered_typecheck_reports_repository_failure_scope(self) -> None:
        """TypeScript 由 Task scope 触发但检查全项目，失败范围不能标成 task。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "typecheck",
                        "description": "typecheck",
                        "enabled": True,
                        "required": True,
                        "runner": "typecheck",
                        "scope": "project TypeScript graph",
                        "side_effect_level": "none",
                    }
                ],
                "full": [],
            }
        )
        snapshot = quality_gate.session_handoff.snapshot(workspace)
        scope = {"status": "ready", "files": ["src/a.ts"]}

        result = quality_gate.run_gate("fast", quality_gate.load_config(workspace), snapshot, False, scope)

        self.assertEqual(result["checks"][0]["failure_scope"], "repository")

    def test_run_detects_workspace_mutation_and_records_final_snapshot(self) -> None:
        """声明为无副作用的命令改动工作区时 Gate 失败，artifact 绑定最终状态。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "mutating-check",
                        "description": "must stay read-only",
                        "enabled": True,
                        "required": True,
                        "command": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('generated.txt').write_text('changed', encoding='utf-8')",
                        ],
                        "scope": "fixture",
                        "side_effect_level": "none",
                    }
                ],
                "full": [],
            }
        )
        before = quality_gate.session_handoff.snapshot(workspace)

        result = quality_gate.run_gate("fast", quality_gate.load_config(workspace), before, False)

        self.assertEqual(result["checks"][-1]["id"], "workspace-stability")
        self.assertEqual(result["checks"][-1]["status"], "fail")
        self.assertEqual(result["overall_status"], "fail")
        self.assertTrue(result["workspace_changed_during_gate"])
        self.assertIn("generated.txt", result["workspace_snapshot"]["untracked_files"])
        self.assertEqual(result["workspace_fingerprint"], result["workspace_snapshot"]["diff_fingerprint"])

    def test_written_verification_artifact_is_immediately_current(self) -> None:
        """正式 run 写入自己的 runtime artifact 后仍绑定同一代码状态。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        (workspace / "src").mkdir()
        (workspace / "src/a.ts").write_text("export const a = 1\n", encoding="utf-8")
        task = self.create_scope(workspace, ["src/a.ts"])
        script = Path(quality_gate.__file__)

        run = subprocess.run(
            [
                sys.executable,
                str(script),
                "--workspace",
                str(workspace),
                "run",
                "fast",
                "--task",
                str(task),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        artifact = Path(json.loads(run.stdout)["verification_artifact"])
        saved = json.loads(artifact.read_text(encoding="utf-8"))
        current = subprocess.run(
            [
                sys.executable,
                str(script),
                "--workspace",
                str(workspace),
                "check-current",
                str(artifact),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("started_snapshot", saved)
        self.assertTrue(json.loads(current.stdout)["workspace_current"])

    def test_unrelated_workspace_change_keeps_scope_current(self) -> None:
        """workspace 有无关文档变化时，Task scope 仍可继承。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        (workspace / "src").mkdir()
        task = self.create_scope(workspace, ["src/a.ts"])
        (workspace / "src/a.ts").write_text("export const a = 1\n", encoding="utf-8")
        before = quality_gate.session_handoff.snapshot(workspace)
        scope = quality_gate.resolve_scope(workspace, task, before)
        artifact = self.write_artifact(task, before, scope)
        (workspace / "docs").mkdir()
        (workspace / "docs/unrelated.md").write_text("unrelated\n", encoding="utf-8")
        result = quality_gate.check_current(artifact, workspace)
        self.assertFalse(result["workspace_current"])
        self.assertTrue(result["workspace_changed"])
        self.assertTrue(result["scope_current"])
        self.assertFalse(result["scope_changed"])
        self.assertFalse(result["previous_verification_may_be_stale"])

    def test_task_file_same_size_content_change_is_stale(self) -> None:
        """scope fingerprint 使用内容 hash，可检测相同 size 的内容替换。"""
        workspace = self.make_workspace({"fast": [], "full": []})
        (workspace / "src").mkdir()
        task = self.create_scope(workspace, ["src/a.ts"])
        file_path = workspace / "src/a.ts"
        file_path.write_text("export const a = 1\n", encoding="utf-8")
        before = quality_gate.session_handoff.snapshot(workspace)
        scope = quality_gate.resolve_scope(workspace, task, before)
        artifact = self.write_artifact(task, before, scope)
        file_path.write_text("export const b = 2\n", encoding="utf-8")
        result = quality_gate.check_current(artifact, workspace)
        self.assertFalse(result["scope_current"])
        self.assertTrue(result["scope_changed"])
        self.assertTrue(result["previous_verification_may_be_stale"])

    def test_ambiguous_scope_blocks_targeted_check(self) -> None:
        """没有可靠 scope 时 targeted verification 不猜测 workspace 文件归属。"""
        workspace = self.make_workspace(
            {
                "fast": [
                    {
                        "id": "targeted-eslint",
                        "description": "targeted",
                        "enabled": True,
                        "required": True,
                        "runner": "targeted-eslint",
                        "scope": "fixture",
                        "side_effect_level": "none",
                    }
                ],
                "full": [],
            }
        )
        (workspace / "src").mkdir()
        (workspace / "src/a.ts").write_text("export const a = 1\n", encoding="utf-8")
        (workspace / "docs").mkdir()
        (workspace / "docs/unrelated.md").write_text("unrelated\n", encoding="utf-8")
        snapshot = quality_gate.session_handoff.snapshot(workspace)
        scope = quality_gate.infer_scope(workspace, workspace / ".trellis/tasks/missing")
        plan = quality_gate.plan_gate("fast", quality_gate.load_config(workspace), snapshot, scope)
        result = quality_gate.run_gate("fast", quality_gate.load_config(workspace), snapshot, False, scope)
        self.assertEqual(scope["status"], "ambiguous")
        self.assertEqual(plan["checks"][0]["status"], "blocked")
        self.assertEqual(result["checks"][0]["status"], "blocked")
        self.assertIn("verification_scope_status: ambiguous", result["checks"][0]["evidence"])

    def test_output_truncation(self) -> None:
        """证据只保存有限尾部，不将无限 stdout 写入 artifact。"""
        evidence = quality_gate.tail_evidence(("x" * (quality_gate.EVIDENCE_LIMIT + 100)).encode(), b"")
        self.assertLessEqual(len(evidence), quality_gate.EVIDENCE_LIMIT + len("...<truncated>...\n"))
        self.assertIn("<truncated>", evidence)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
