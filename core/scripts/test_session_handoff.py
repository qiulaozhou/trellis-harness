"""标准库隔离自测：只写临时 Git/Task fixture，不执行 commit 或真实任务操作。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import session_handoff as helper


def invoke(workspace: Path, command: str, *args: str, code: int = 0) -> dict:
    """通过真实 CLI 检查 JSON 与退出码，防止只覆盖内部函数。"""
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(Path(helper.__file__).resolve()),
         command, *args, "--workspace", str(workspace)], capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )
    assert result.returncode == code, (command, result.returncode, result.stdout, result.stderr)
    assert "PRIVATE_FIXTURE_CONTENT" not in result.stdout + result.stderr
    return json.loads(result.stdout)


def handoff_text(task: Path, current: dict) -> str:
    """构造完整而最小的真实 Markdown 合约样例。"""
    return f"""# Session Handoff

## Identity
Task: .trellis/tasks/{task.name}
Checkpoint At: 2026-09-03T08:00:00+00:00
Source Session: fixture-session
Workspace: {current['workspace_path']}

## Current Position
Phase: implement
Current Focus: 核对交接边界

## Progress Since Previous Checkpoint
- 完成 helper

## Decisions
- 无新增决策，沿用 design.md

## Rejected Approaches
- 无

## Known Issues / Blockers
- 无

## Verification
### Fixture check
Status: pass
Command / Method: 执行隔离自测
Scope: helper
Evidence: 临时场景通过
Notes: 不覆盖实际 Session 切换

## Workspace Snapshot
Branch: {current['branch']}
HEAD: {current['head']}
Dirty: {str(current['dirty']).lower()}
Diff Fingerprint: {current['diff_fingerprint']}

## Uncommitted Work Ownership
- 临时 fixture 属于本次自测

## Next Action
Action: 检查下一条验收场景
Expected Result: 得到明确结果

## Resume Constraints
- 不提交、不修改真实 Task
"""


def self_check() -> None:
    """验证所需正反场景和关键边界；TemporaryDirectory 仅清理本次创建的目录。"""
    with tempfile.TemporaryDirectory(prefix="harness-handoff-test-") as temporary:
        workspace = Path(temporary).resolve()
        helper.git(workspace, "init", "--initial-branch=harness-fixture")
        (workspace / ".git" / "info" / "exclude").write_text(".trellis/\n", encoding="utf-8")
        baseline = invoke(workspace, "snapshot")
        assert baseline["head"] == "UNBORN" and baseline["dirty"] is False
        assert baseline["diff_fingerprint"] == invoke(workspace, "snapshot")["diff_fingerprint"]

        # 源码正文只用于临时 fixture；helper 输出必须始终只包含路径与指纹。
        tracked = workspace / "tracked.txt"
        tracked.write_text("PRIVATE_FIXTURE_CONTENT staged\n", encoding="utf-8")
        helper.git(workspace, "add", "--", "tracked.txt")
        staged = invoke(workspace, "snapshot")
        assert staged["staged_changed_files"] == ["tracked.txt"]
        assert staged["diff_fingerprint"] != baseline["diff_fingerprint"]
        tracked.write_text("PRIVATE_FIXTURE_CONTENT changed\n", encoding="utf-8")
        untracked = workspace / "未跟踪.txt"
        untracked.write_text("PRIVATE_FIXTURE_CONTENT", encoding="utf-8")
        current = invoke(workspace, "snapshot")
        assert current["unstaged_changed_files"] == ["tracked.txt"]
        assert current["untracked_files"] == ["未跟踪.txt"]
        assert current["diff_fingerprint"] != staged["diff_fingerprint"]
        assert current["diff_fingerprint"] == invoke(workspace, "snapshot")["diff_fingerprint"]
        metadata = untracked.stat()
        os.utime(untracked, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        assert current["diff_fingerprint"] != invoke(workspace, "snapshot")["diff_fingerprint"]
        current = invoke(workspace, "snapshot")

        tasks = workspace / ".trellis" / "tasks"
        task = tasks / "fixture-a"
        task.mkdir(parents=True)
        metadata_path = task / "task.json"
        metadata_path.write_text('{"status":"in_progress"}', encoding="utf-8")
        handoff = task / "handoff.md"
        valid_text = handoff_text(task, current)
        handoff.write_text(valid_text, encoding="utf-8")
        assert invoke(workspace, "validate", str(handoff))["valid"]
        assert invoke(workspace, "compare", str(handoff))["same_code_state"]
        assert invoke(workspace, "candidates")["selected_task"] == ".trellis/tasks/fixture-a"

        # 合法结构的旧 snapshot 改变应返回 stale，而非验证错误或失败退出。
        for old, new, field in (
            ("HEAD: UNBORN", "HEAD: " + "a" * 40, "head_changed"),
            (current["diff_fingerprint"], "f" * 64, "diff_changed"),
            ("Branch: harness-fixture", "Branch: old-branch", "branch_changed"),
            (f"Workspace: {workspace}", f"Workspace: {workspace / 'other'}", "workspace_changed"),
        ):
            handoff.write_text(valid_text.replace(old, new), encoding="utf-8")
            assert invoke(workspace, "validate", str(handoff))["valid"]
            changed = invoke(workspace, "compare", str(handoff))
            assert changed[field] and not changed["same_code_state"]
            assert changed["message"] == "Previous verification may be stale."
            assert changed["requires_reverification"] == [{"name": "Fixture check", "status": "pass"}]

        for old, new, expected in (
            ("## Next Action", "## Lost Action", "Next Action"),
            ("Action: 检查下一条验收场景", "Action:", "Action"),
            ("Status: pass", "Status: done", "Status"),
            ("Current Focus: 核对交接边界", "Current Focus:", "Current Focus"),
            ("HEAD: UNBORN", "HEAD:", "HEAD"),
            ("Action: 检查下一条验收场景", "Action: 一\nAction: 二", "Action"),
            ("## Decisions", "## Decisions\n无\n## Decisions", "Duplicate section"),
            ("Checkpoint At: 2026-09-03T08:00:00+00:00", "Checkpoint At: yesterday", "Checkpoint At"),
            ("Task: .trellis/tasks/fixture-a", "Task: .trellis/tasks/archive/fixture-a", "Identity"),
        ):
            handoff.write_text(valid_text.replace(old, new), encoding="utf-8")
            invalid = invoke(workspace, "validate", str(handoff), code=1)
            assert any(expected in error for error in invalid["errors"]), invalid

        handoff.write_text(valid_text, encoding="utf-8")
        metadata_path.write_text('{"status":"completed"}', encoding="utf-8")
        assert "completed" in invoke(workspace, "validate", str(handoff), code=1)["errors"][0]
        assert invoke(workspace, "candidates")["selected_task"] is None
        metadata_path.write_text('{"status":"in_progress"}', encoding="utf-8")
        archived = tasks / "archive" / "old-task"
        archived.mkdir(parents=True)
        (archived / "task.json").write_text('{"status":"in_progress"}', encoding="utf-8")
        (archived / "handoff.md").write_text(valid_text, encoding="utf-8")
        invoke(workspace, "validate", str(archived / "handoff.md"), code=1)
        invoke(workspace, "validate", str(workspace / "outside-handoff.md"), code=1)
        invoke(workspace, "validate", str(tasks / "missing" / "handoff.md"), code=1)

        # 两个同身份候选即使时间不同也必须歧义；时间不能代替任务身份。
        other_task = tasks / "fixture-b"
        other_task.mkdir()
        (other_task / "task.json").write_text('{"status":"in_progress"}', encoding="utf-8")
        (other_task / "handoff.md").write_text(
            handoff_text(other_task, current).replace("08:00:00", "09:00:00"), encoding="utf-8",
        )
        multiple = invoke(workspace, "candidates")
        assert multiple["ambiguous"] and multiple["selected_task"] is None
        assert multiple["candidates"][0]["task"] == ".trellis/tasks/fixture-b"
        (other_task / "task.json").write_text('{"status":"completed"}', encoding="utf-8")
        handoff.write_text(valid_text.replace("Branch: harness-fixture", "Branch: old-branch"), encoding="utf-8")
        low_confidence = invoke(workspace, "candidates")
        assert low_confidence["selected_task"] is None
        assert low_confidence["selection_status"] == "explicit_task_required"

        # 可用时额外验证目录别名不会让外部 Task 越过真实路径边界。
        alias = tasks / "alias"
        try:
            alias.symlink_to(task, target_is_directory=True)
        except OSError:
            print("SKIP: symlink fixture unavailable on this host")
        else:
            invoke(workspace, "validate", str(alias / "handoff.md"), code=1)
            alias.unlink()
        assert not (workspace / ".trellis" / ".runtime").exists()
        assert not (workspace / ".trellis" / "workspace").exists()
        assert helper.git(workspace, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)) == b""
    print("PASS: snapshot/fingerprint, validate, compare, candidates, path boundaries, no Task/runtime/Journal/commit side effects")


if __name__ == "__main__":
    self_check()
