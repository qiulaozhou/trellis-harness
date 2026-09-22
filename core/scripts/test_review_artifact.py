"""Contract and fixture tests for dev-review."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import review_artifact


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "core" / "skills" / "dev-review" / "SKILL.md"


class DevReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "user.name", "Fixture")
        (self.workspace / ".trellis" / "tasks" / "task-a").mkdir(parents=True)
        (self.workspace / ".trellis" / "harness").mkdir(parents=True)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "feature.ts").write_text("export const value = 1;\n", encoding="utf-8")
        self.write_package({"react": "^18.2.0"})
        self.write_profile("react")
        task = self.workspace / ".trellis" / "tasks" / "task-a"
        (task / "task.json").write_text(json.dumps({"id": "task-a", "status": "in_progress"}), encoding="utf-8")
        (task / "handoff.md").write_text("# Session Handoff\n\n## Current Position\nCurrent Focus: review\n", encoding="utf-8")
        (task / "verification-scope.json").write_text(json.dumps({
            "task": ".trellis/tasks/task-a", "include": ["src/feature.ts"], "exclude": [],
            "source": "explicit", "updated_at": "2026-09-11T00:00:00+00:00",
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        (self.workspace / "src" / "feature.ts").write_text("export const value = 2;\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *args: str) -> None:
        result = subprocess.run(["git", *args], cwd=self.workspace, capture_output=True, text=True, check=False)
        if result.returncode:
            raise AssertionError(result.stderr)

    def write_package(self, dependencies: dict[str, str]) -> None:
        (self.workspace / "package.json").write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")

    def write_profile(self, profile: str | None) -> None:
        payload: dict[str, object] = {"fast": [], "full": []}
        if profile:
            payload["review"] = {"profile": profile}
        (self.workspace / ".trellis" / "harness" / "quality-gates.json").write_text(json.dumps(payload), encoding="utf-8")

    def context(self) -> dict:
        return review_artifact.context(self.workspace, ".trellis/tasks/task-a")

    def artifact(self, result: str = "APPROVED", findings: list[dict] | None = None) -> dict:
        context = self.context()
        return {
            "schema_version": 1,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "profile": context["profile"],
            "task": context["task"],
            "scope_fingerprint": context["scope_fingerprint"],
            "code": context["code"],
            "result": result,
            "summary": "No material findings." if result == "APPROVED" and not findings else "Review result.",
            "findings": findings or [],
            "reviewed_files": context["review_files"],
        }

    def material_finding(self) -> dict:
        return {
            "priority": "P1", "title": "Incorrect branch", "file": "src/feature.ts", "line": 1,
            "problem": "The changed branch returns the wrong value.",
            "impact": "The primary flow fails for every request.",
            "evidence": "The diff changes the returned constant from 1 to 2 while the contract requires 1.",
            "suggested_direction": "Restore the contract value or update the caller contract.",
        }

    # 1
    def test_vue2_profile_selection_uses_actual_version(self) -> None:
        self.write_package({"vue": "^2.7.16", "vue-router": "^3.6.5"})
        self.write_profile("vue2")
        result = self.context()
        self.assertEqual((result["profile"], result["versions"]["vue"]), ("vue2", "^2.7.16"))

    # 2
    def test_vue3_profile_selection_uses_actual_version(self) -> None:
        self.write_package({"vue": "~3.4.1", "vue-router": "^4.2.0"})
        self.write_profile("vue3")
        result = self.context()
        self.assertEqual((result["profile"], result["versions"]["vue"]), ("vue3", "~3.4.1"))

    # 3
    def test_react_profile_selection_uses_actual_version(self) -> None:
        result = self.context()
        self.assertEqual((result["profile"], result["versions"]["react"]), ("react", "^18.2.0"))

    # 4
    def test_nextjs_profile_selection_records_router_and_versions(self) -> None:
        self.write_package({"next": "14.2.5", "react": "^18"})
        self.write_profile("nextjs")
        (self.workspace / "app").mkdir()
        result = self.context()
        self.assertEqual((result["profile"], result["router"]), ("nextjs", "app"))
        self.assertEqual(result["versions"], {"react": "^18", "next": "14.2.5"})

    # 5
    def test_nextjs_contract_inherits_react_rules(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("`nextjs` → 先读 `references/react.md`，再读 `references/nextjs.md`", text)

    # 6
    def test_task_scope_only(self) -> None:
        (self.workspace / "src" / "outside.ts").write_text("outside\n", encoding="utf-8")
        result = self.context()
        self.assertEqual(result["review_files"], ["src/feature.ts"])

    # 7
    def test_unrelated_dirty_file_is_excluded_and_reported(self) -> None:
        (self.workspace / "src" / "outside.ts").write_text("outside\n", encoding="utf-8")
        result = self.context()
        self.assertNotIn("src/outside.ts", result["review_files"])
        self.assertIn("src/outside.ts", result["unrelated_workspace_changes"])

    # 8
    def test_no_finding_is_approved(self) -> None:
        self.assertEqual(review_artifact.validate_artifact(self.artifact()), [])

    # 9
    def test_p1_finding_requires_changes_requested(self) -> None:
        finding = self.material_finding()
        self.assertEqual(review_artifact.validate_artifact(self.artifact("CHANGES_REQUESTED", [finding])), [])
        errors = review_artifact.validate_artifact(self.artifact("APPROVED", [finding]))
        self.assertTrue(any("APPROVED cannot" in error for error in errors))

    # 10
    def test_insufficient_context_is_blocked(self) -> None:
        (self.workspace / ".trellis" / "tasks" / "task-a" / "verification-scope.json").unlink()
        result = self.context()
        self.assertEqual((result["status"], result["result"]), ("blocked", "BLOCKED"))

    # 11
    def test_context_and_freshness_do_not_modify_business_code(self) -> None:
        source = self.workspace / "src" / "feature.ts"
        before = source.read_bytes()
        artifact = self.artifact()
        review = self.workspace / ".trellis" / "tasks" / "task-a" / "review.json"
        review.write_text(json.dumps(artifact), encoding="utf-8")
        review_artifact.check_current(review, self.workspace)
        self.assertEqual(source.read_bytes(), before)

    # 12
    def test_skill_disables_automatic_verify(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("不运行 lint、Prettier、typecheck、tests、build", text)
        self.assertNotIn("quality_gate.py run", text)

    # 13
    def test_skill_disables_next_action(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("不执行 handoff 的 Next Action", text)
        self.assertIn("然后立即 STOP", text)

    # 14
    def test_artifact_stores_scope_fingerprint(self) -> None:
        artifact = self.artifact()
        self.assertRegex(artifact["scope_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(review_artifact.validate_artifact(artifact), [])

    # 15
    def test_scope_change_makes_old_review_stale(self) -> None:
        review = self.workspace / ".trellis" / "tasks" / "task-a" / "review.json"
        review.write_text(json.dumps(self.artifact()), encoding="utf-8")
        self.assertEqual(review_artifact.check_current(review, self.workspace)["freshness"], "CURRENT")
        (self.workspace / "src" / "feature.ts").write_text("export const value = 3;\n", encoding="utf-8")
        self.assertEqual(review_artifact.check_current(review, self.workspace)["freshness"], "STALE")

if __name__ == "__main__":
    unittest.main(verbosity=2)
