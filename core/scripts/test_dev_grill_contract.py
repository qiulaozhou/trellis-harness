"""Contract fixtures for the agent-facing dev-grill and dev-start rules."""

from pathlib import Path
import unittest


CORE_ROOT = Path(__file__).parents[1]
if (CORE_ROOT / "skills").is_dir():
    GRILL = (CORE_ROOT / "skills" / "dev-grill" / "SKILL.md").read_text(encoding="utf-8")
    START = (CORE_ROOT / "skills" / "dev-start" / "SKILL.md").read_text(encoding="utf-8")
    INTAKE = (CORE_ROOT / "scripts" / "intake.py").read_text(encoding="utf-8")
else:
    PROJECT_ROOT = Path(__file__).parents[3]
    GRILL = (PROJECT_ROOT / ".agents" / "skills" / "dev-grill" / "SKILL.md").read_text(encoding="utf-8")
    START = (PROJECT_ROOT / ".agents" / "skills" / "dev-start" / "SKILL.md").read_text(encoding="utf-8")
    INTAKE = (PROJECT_ROOT / ".trellis" / "scripts" / "harness" / "intake.py").read_text(encoding="utf-8")


class DevGrillContractTests(unittest.TestCase):
    def test_grill_stops_before_task_or_implementation(self) -> None:
        for phrase in ("不创建正式 Task", "不修改业务代码", "不自动创建 Task", "仍不得开始业务实现"):
            self.assertIn(phrase, GRILL + START)

    def test_grill_uses_one_question_and_fast_read_boundary(self) -> None:
        self.assertIn("每轮最多提出一个尚未解决的核心", GRILL)
        for phrase in ("不读完整 PRD/Design/Implement", "完整 Journal", "不调用 `trellis mem`", "不要 repo-wide search"):
            self.assertIn(phrase, GRILL)

    def test_start_requires_ready_and_consumes_intake(self) -> None:
        self.assertIn("status` 必须是有效 `READY`", START)
        self.assertIn("intake.py consume", START)
        self.assertIn("原有路径", START)

    def test_intake_has_explicit_lifecycle_and_fallback_markers(self) -> None:
        for status in ("IN_PROGRESS", "READY", "CONSUMED"):
            self.assertIn(status, INTAKE)
        for marker in ("[open]", "blocking", "Consumed Task"):
            self.assertIn(marker, INTAKE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
