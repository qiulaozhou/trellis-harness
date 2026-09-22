"""Fixture tests for the deterministic requirement-intake helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("intake.py")
SPEC = importlib.util.spec_from_file_location("harness_intake", SCRIPT)
assert SPEC and SPEC.loader
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".trellis").mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self, slug: str = "sample") -> Path:
        args = type("Args", (), {"root": str(self.root), "slug": slug, "request": "Add a visible setting", "profile": "vue3"})()
        self.assertEqual(intake.cmd_init(args), 0)
        return self.root / ".trellis" / "harness" / "intake" / slug / "requirement-intake.md"

    def ready(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        replacements = {
            "Status: IN_PROGRESS": "Status: READY",
            "Ready For dev-start: NO": "Ready For dev-start: YES",
            "- [open] Define the user-visible goal.": "The setting has a clear user-visible goal.",
            "- [open] Identify the primary user.": "Signed-in project users.",
            "- [open] Describe the observable behavior and main flow.": "Users can view and change the setting.",
            "- [open] Define the included scope.": "The setting screen and persistence.",
            "- [open] Define explicit exclusions.": "No migration of unrelated settings.",
            "- [open] Record material loading, empty, error, and success states when applicable.": "Loading, empty, error, and success states are explicit.",
            "- [open] Record material edge cases or state none with a reason.": "No additional material edge cases.",
            "- [open] Record dependencies and external owners, or state none.": "No external dependency.",
            "- [open] Record assumptions that affect implementation.": "The existing settings API remains available.",
            "- [open] Define observable acceptance criteria.": "[ ] The setting is visible and persists after refresh.",
            "- [open] Start with the highest-impact unanswered product decision.": "- none",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")

    def test_new_intake_starts_in_progress_and_exposes_frontier(self) -> None:
        path = self.create()
        result = intake.validation(path)
        self.assertTrue(result["valid"])
        self.assertFalse(result["ready"])
        self.assertIn("Goal", result["open_sections"])
        self.assertEqual(result["profile"], "vue3")

    def test_unresolved_decision_prevents_ready(self) -> None:
        path = self.create()
        self.ready(path)
        text = path.read_text(encoding="utf-8").replace("- none\n\n##", "- [open] Choose retention period.\n\n##", 1)
        path.write_text(text, encoding="utf-8")
        result = intake.validation(path)
        self.assertFalse(result["ready"])
        self.assertTrue(any("unresolved" in error for error in result["errors"]))

    def test_nonblocking_external_unknown_can_be_recorded(self) -> None:
        path = self.create()
        self.ready(path)
        text = path.read_text(encoding="utf-8").replace("No external dependency.", "[external-unknown] owner=payments impact=medium blocking=no next=confirm API field.")
        path.write_text(text, encoding="utf-8")
        self.assertTrue(intake.validation(path)["ready"])

    def test_ready_intake_is_consumed_by_existing_task(self) -> None:
        path = self.create()
        self.ready(path)
        task = self.root / ".trellis" / "tasks" / "09-16-sample"
        task.mkdir(parents=True)
        (task / "task.json").write_text(json.dumps({"id": "sample"}), encoding="utf-8")
        args = type("Args", (), {"root": str(self.root), "intake": str(path), "task": ".trellis/tasks/09-16-sample"})()
        self.assertEqual(intake.cmd_consume(args), 0)
        fields, _, _ = intake.parse(path)
        self.assertEqual(fields["Status"], "CONSUMED")
        self.assertEqual(fields["Consumed Task"], ".trellis/tasks/09-16-sample")

    def test_consume_rejects_in_progress_and_missing_task(self) -> None:
        path = self.create()
        args = type("Args", (), {"root": str(self.root), "intake": str(path), "task": ".trellis/tasks/missing"})()
        with self.assertRaisesRegex(intake.IntakeError, "READY"):
            intake.cmd_consume(args)

    def test_missing_section_is_a_fallback_signal(self) -> None:
        path = self.create()
        text = path.read_text(encoding="utf-8").replace("## Current Focus", "## Removed Focus", 1)
        path.write_text(text, encoding="utf-8")
        result = intake.validation(path)
        self.assertFalse(result["valid"])
        self.assertIn("Current Focus", result["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
