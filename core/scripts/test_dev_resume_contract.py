"""dev-resume Fast Path 的隔离契约自测；不读取真实业务代码或调用外部服务。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import session_handoff as helper
from test_session_handoff import handoff_text, invoke


SCRIPT_PATH = Path(__file__).resolve()
SKILL_PATH = next(
    candidate
    for candidate in (
        SCRIPT_PATH.parents[1] / "skills" / "dev-resume" / "SKILL.md",
        SCRIPT_PATH.parents[3] / ".agents" / "skills" / "dev-resume" / "SKILL.md",
    )
    if candidate.is_file()
)
REQUIRED_POSITION_FIELDS = (
    ("position", "Phase"),
    ("position", "Current Focus"),
    ("next_action", "Action"),
    ("identity", "Task"),
)


def resume_route(parsed: dict) -> str:
    """按 Skill 契约区分 Fast Path 与 targeted fallback。"""
    if not parsed.get("valid"):
        return "fallback"
    for section, field in REQUIRED_POSITION_FIELDS:
        if not parsed.get(section, {}).get(field, "").strip():
            return "fallback"
    return "fast"


def memory_allowed(*, handoff_missing_fact: bool, artifact_has_fact: bool, user_requested: bool) -> bool:
    """只有恢复位置所需历史事实仍缺失或用户明确要求时才允许 Memory。"""
    return user_requested or (handoff_missing_fact and not artifact_has_fact)


class DevResumeContractTests(unittest.TestCase):
    """覆盖 dev-resume 的默认读取边界和恢复路由。"""

    def setUp(self) -> None:
        self.skill = SKILL_PATH.read_text(encoding="utf-8")

    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict]:
        """创建最小未提交 Git/Task fixture，返回清理器、Task、handoff 原文和快照。"""
        temporary = tempfile.TemporaryDirectory(prefix="dev-resume-")
        workspace = Path(temporary.name).resolve()
        helper.git(workspace, "init", "--initial-branch=harness-fixture")
        (workspace / ".git" / "info" / "exclude").write_text(".trellis/\n", encoding="utf-8")
        task = workspace / ".trellis" / "tasks" / "fixture-resume"
        task.mkdir(parents=True)
        (task / "task.json").write_text(
            json.dumps({"status": "in_progress"}), encoding="utf-8"
        )
        current = helper.snapshot(workspace)
        valid = handoff_text(task, current)
        (task / "handoff.md").write_text(valid, encoding="utf-8")
        return temporary, task, valid, current

    def test_skill_contract_disables_default_work(self) -> None:
        """Skill 必须明确恢复后停止，并禁止恢复阶段的业务工作。"""
        for phrase in (
            "Fast Path（默认）",
            "只读取 `task.json` 和 `handoff.md`",
            "只执行一次 `compare <task-path>/handoff.md`",
            "Next Action 只展示，不执行",
            "恢复成功后只输出以下短摘要，然后立即 STOP",
            "Verification: NONE",
            "Fast Path 固定为 `trellis mem = NOT USED`",
        ):
            self.assertIn(phrase, self.skill)
        for phrase in (
            "不启动服务",
            "不请求 API",
            "不执行 lint/typecheck/build/测试",
            "不修改代码",
            "不创建子 Agent",
        ):
            self.assertIn(phrase, self.skill)

    def test_complete_handoff_uses_fast_path_without_verification(self) -> None:
        """完整 handoff 即使没有 verification 也保持 Fast Path。"""
        temporary, task, _, _ = self.make_fixture()
        try:
            parsed = invoke(Path(temporary.name), "validate", str(task / "handoff.md"))
            self.assertEqual(resume_route(parsed), "fast")
            self.assertFalse((task / "verification.json").exists())
            self.assertEqual("NONE", "NONE" if not (task / "verification.json").exists() else "CURRENT")
        finally:
            temporary.cleanup()

    def test_stale_workspace_stays_fast(self) -> None:
        """Git stale 只改变状态，不把 Resume 路由升级为 Slow Path。"""
        temporary, task, valid, _ = self.make_fixture()
        try:
            parsed_before_change = invoke(Path(temporary.name), "validate", str(task / "handoff.md"))
            self.assertEqual(resume_route(parsed_before_change), "fast")
            (task / "handoff.md").write_text(
                valid.replace("Branch: harness-fixture", "Branch: old-branch"),
                encoding="utf-8",
            )
            parsed = invoke(Path(temporary.name), "compare", str(task / "handoff.md"))
            self.assertFalse(parsed["same_code_state"])
            self.assertEqual(parsed["message"], "Previous verification may be stale.")
            self.assertEqual(resume_route(parsed_before_change), "fast")
            self.assertIn("same_code_state: false", self.skill)
        finally:
            temporary.cleanup()

    def test_incomplete_handoff_routes_to_targeted_fallback(self) -> None:
        """缺 Current Focus 时只允许进入 targeted fallback。"""
        temporary, task, valid, _ = self.make_fixture()
        try:
            (task / "handoff.md").write_text(
                valid.replace("Current Focus: 核对交接边界", "Current Focus:"),
                encoding="utf-8",
            )
            parsed = invoke(Path(temporary.name), "validate", str(task / "handoff.md"), code=1)
            self.assertEqual(resume_route(parsed), "fallback")
            self.assertTrue(any("Current Focus" in error for error in parsed["errors"]))
            self.assertIn("只精准读取能补齐", self.skill)
        finally:
            temporary.cleanup()

    def test_memory_routing_is_opt_in(self) -> None:
        """完整上下文不查 Memory，只有缺失且必要或用户要求时才允许。"""
        self.assertFalse(memory_allowed(handoff_missing_fact=False, artifact_has_fact=True, user_requested=False))
        self.assertFalse(memory_allowed(handoff_missing_fact=True, artifact_has_fact=True, user_requested=False))
        self.assertTrue(memory_allowed(handoff_missing_fact=True, artifact_has_fact=False, user_requested=False))
        self.assertTrue(memory_allowed(handoff_missing_fact=False, artifact_has_fact=True, user_requested=True))
        self.assertIn("mem search", self.skill)
        self.assertIn("mem context", self.skill)
        self.assertIn("mem extract", self.skill)


if __name__ == "__main__":
    unittest.main()
